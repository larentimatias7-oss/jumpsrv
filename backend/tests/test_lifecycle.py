import asyncio
import base64
import time
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import (
    SessionLifecycleSettings,
    get_lifecycle_settings,
    save_lifecycle_settings,
)
from app.dispatcher.service import KioskDispatcher
from app.docker_runtime.client import DockerRuntime
from app.models.database import KioskModel, init_db


@pytest.fixture
def in_memory_db():
    return init_db("sqlite:///:memory:")


@pytest.fixture
def auth_headers():
    token = base64.b64encode(b"admin:admin").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_settings_model_and_persistence(in_memory_db):
    # Initial settings should match defaults
    settings = get_lifecycle_settings(in_memory_db)
    assert settings.disconnect_grace_seconds == 30
    assert settings.idle_timeout_seconds == 900
    assert settings.max_session_lifetime_seconds == 14400

    # Save custom settings
    custom = SessionLifecycleSettings(
        disconnect_grace_seconds=45,
        idle_timeout_seconds=600,
        max_session_lifetime_seconds=7200,
    )
    save_lifecycle_settings(custom, in_memory_db)

    # Re-fetch and verify persistence
    updated = get_lifecycle_settings(in_memory_db)
    assert updated.disconnect_grace_seconds == 45
    assert updated.idle_timeout_seconds == 600
    assert updated.max_session_lifetime_seconds == 7200


def test_settings_api_get_and_put(auth_headers):
    client = TestClient(app)

    # 1. GET /api/settings
    res = client.get("/api/settings", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "disconnect_grace_seconds" in data
    assert "idle_timeout_seconds" in data
    assert "max_session_lifetime_seconds" in data

    # 2. PUT with invalid values (below bounds) should return 422
    invalid_res = client.put(
        "/api/settings",
        headers=auth_headers,
        json={"disconnect_grace_seconds": 1, "idle_timeout_seconds": 10, "max_session_lifetime_seconds": 5},
    )
    assert invalid_res.status_code == 422

    # 3. PUT with valid values
    valid_payload = {
        "disconnect_grace_seconds": 50,
        "idle_timeout_seconds": 1200,
        "max_session_lifetime_seconds": 18000,
    }
    put_res = client.put("/api/settings", headers=auth_headers, json=valid_payload)
    assert put_res.status_code == 200
    assert put_res.json()["disconnect_grace_seconds"] == 50
    assert put_res.json()["idle_timeout_seconds"] == 1200
    assert put_res.json()["max_session_lifetime_seconds"] == 18000

    # 4. Verify GET reflects the changes
    get_again = client.get("/api/settings", headers=auth_headers)
    assert get_again.status_code == 200
    assert get_again.json()["disconnect_grace_seconds"] == 50


def test_dispatcher_lifecycle_configuration(in_memory_db):
    mock_docker = Mock(spec=DockerRuntime)
    dispatcher = KioskDispatcher(
        db_factory=in_memory_db,
        docker_runtime=mock_docker,
        disconnect_grace_seconds=15,
        idle_timeout_seconds=300,
        max_session_lifetime_seconds=3600,
    )

    assert dispatcher.disconnect_grace_seconds == 15
    assert dispatcher.idle_timeout_seconds == 300
    assert dispatcher.max_session_lifetime_seconds == 3600

    dispatcher.update_lifecycle_settings(
        disconnect_grace_seconds=20,
        idle_timeout_seconds=600,
        max_session_lifetime_seconds=7200,
    )
    assert dispatcher.disconnect_grace_seconds == 20
    assert dispatcher.idle_timeout_seconds == 600
    assert dispatcher.max_session_lifetime_seconds == 7200


@pytest.mark.asyncio
async def test_dispatcher_disconnect_grace_stops_container_and_sets_idle(in_memory_db):
    mock_docker = Mock(spec=DockerRuntime)
    dispatcher = KioskDispatcher(
        db_factory=in_memory_db,
        docker_runtime=mock_docker,
        disconnect_grace_seconds=1,  # Short grace window for test
    )
    dispatcher.disconnect_grace_seconds = 0.05

    # Insert test kiosk
    with in_memory_db() as session:
        k = KioskModel(
            id="test-kiosk-grace",
            name="TEST-GRACE",
            device_type="generic",
            target_url="http://192.168.1.50",
            target_ip="192.168.1.50",
            target_port=80,
            rdp_port=33891,
            rdp_username="kiosk",
            container_name="kiosk-test-grace",
            volume_name="rdp_test_grace",
            status="RUNNING",
        )
        session.add(k)
        session.commit()

    dispatcher.active_connections[33891] = 0
    dispatcher._schedule_disconnect_grace("test-kiosk-grace", "kiosk-test-grace", 33891)

    # Wait for grace to expire
    await asyncio.sleep(0.1)

    mock_docker.stop_container.assert_called_once_with("kiosk-test-grace")

    # Verify status transitioned to IDLE
    with in_memory_db() as session:
        updated_k = session.query(KioskModel).get("test-kiosk-grace")
        assert updated_k.status == "IDLE"


@pytest.mark.asyncio
async def test_dispatcher_disconnect_grace_cancelled_by_reconnect(in_memory_db):
    mock_docker = Mock(spec=DockerRuntime)
    dispatcher = KioskDispatcher(
        db_factory=in_memory_db,
        docker_runtime=mock_docker,
    )
    dispatcher.disconnect_grace_seconds = 0.15

    with in_memory_db() as session:
        k = KioskModel(
            id="test-kiosk-recon",
            name="TEST-RECON",
            device_type="generic",
            target_url="http://192.168.1.51",
            target_ip="192.168.1.51",
            target_port=80,
            rdp_port=33892,
            rdp_username="kiosk",
            container_name="kiosk-test-recon",
            volume_name="rdp_test_recon",
            status="RUNNING",
        )
        session.add(k)
        session.commit()

    dispatcher.active_connections[33892] = 0
    dispatcher._schedule_disconnect_grace("test-kiosk-recon", "kiosk-test-recon", 33892)

    # Simulate reconnect within grace window
    await asyncio.sleep(0.05)
    dispatcher.active_connections[33892] = 1
    if 33892 in dispatcher.idle_tasks:
        dispatcher.idle_tasks[33892].cancel()

    # Wait past the original grace window
    await asyncio.sleep(0.15)

    # Container should NOT be stopped because reconnect intervened
    mock_docker.stop_container.assert_not_called()
    with in_memory_db() as session:
        updated_k = session.query(KioskModel).get("test-kiosk-recon")
        assert updated_k.status == "RUNNING"


@pytest.mark.asyncio
async def test_dispatcher_idle_traffic_watchdog_termination(in_memory_db):
    mock_docker = Mock(spec=DockerRuntime)
    dispatcher = KioskDispatcher(
        db_factory=in_memory_db,
        docker_runtime=mock_docker,
        idle_timeout_seconds=0.08,
        max_session_lifetime_seconds=10.0,
    )

    with in_memory_db() as session:
        k = KioskModel(
            id="test-kiosk-idle",
            name="TEST-IDLE",
            device_type="generic",
            target_url="http://192.168.1.52",
            target_ip="192.168.1.52",
            target_port=80,
            rdp_port=33893,
            rdp_username="kiosk",
            container_name="kiosk-test-idle",
            volume_name="rdp_test_idle",
            status="RUNNING",
        )
        session.add(k)
        session.commit()

    # Simulate active session with watchdog
    session_info = {
        "start_time": time.time(),
        "last_traffic_time": time.time(),
        "termination_reason": None,
    }
    session_active = True

    async def session_watchdog():
        nonlocal session_active
        while session_active:
            await asyncio.sleep(0.02)
            now = time.time()
            if now - session_info["last_traffic_time"] >= dispatcher.idle_timeout_seconds:
                session_info["termination_reason"] = "idle_timeout"
                session_active = False
                break

    watchdog_task = asyncio.create_task(session_watchdog())
    await asyncio.sleep(0.12)
    session_active = False
    await watchdog_task

    assert session_info["termination_reason"] == "idle_timeout"

    dispatcher._stop_and_set_idle("test-kiosk-idle", "kiosk-test-idle", 33893, reason="idle_timeout")
    mock_docker.stop_container.assert_called_once_with("kiosk-test-idle")
    with in_memory_db() as session:
        updated_k = session.query(KioskModel).get("test-kiosk-idle")
        assert updated_k.status == "IDLE"


@pytest.mark.asyncio
async def test_dispatcher_max_lifetime_watchdog_termination(in_memory_db):
    mock_docker = Mock(spec=DockerRuntime)
    dispatcher = KioskDispatcher(
        db_factory=in_memory_db,
        docker_runtime=mock_docker,
        idle_timeout_seconds=10.0,
        max_session_lifetime_seconds=0.08,
    )

    with in_memory_db() as session:
        k = KioskModel(
            id="test-kiosk-max",
            name="TEST-MAX",
            device_type="generic",
            target_url="http://192.168.1.53",
            target_ip="192.168.1.53",
            target_port=80,
            rdp_port=33894,
            rdp_username="kiosk",
            container_name="kiosk-test-max",
            volume_name="rdp_test_max",
            status="RUNNING",
        )
        session.add(k)
        session.commit()

    session_info = {
        "start_time": time.time(),
        "last_traffic_time": time.time(),
        "termination_reason": None,
    }
    session_active = True

    async def session_watchdog():
        nonlocal session_active
        while session_active:
            await asyncio.sleep(0.02)
            now = time.time()
            if now - session_info["start_time"] >= dispatcher.max_session_lifetime_seconds:
                session_info["termination_reason"] = "max_lifetime_exceeded"
                session_active = False
                break

    watchdog_task = asyncio.create_task(session_watchdog())
    await asyncio.sleep(0.12)
    session_active = False
    await watchdog_task

    assert session_info["termination_reason"] == "max_lifetime_exceeded"

    dispatcher._stop_and_set_idle("test-kiosk-max", "kiosk-test-max", 33894, reason="max_lifetime_exceeded")
    mock_docker.stop_container.assert_called_once_with("kiosk-test-max")
    with in_memory_db() as session:
        updated_k = session.query(KioskModel).get("test-kiosk-max")
        assert updated_k.status == "IDLE"
