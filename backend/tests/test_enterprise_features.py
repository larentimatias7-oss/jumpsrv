import asyncio
import socket
import threading
import time
from unittest.mock import Mock, patch
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.jumpserver.client import JumpServerClient, JumpServerAuthError
from app.jumpserver.config import JumpServerSettings
from app.jumpserver.operations import JumpServerOperations
from app.provisioning.provisioner import (
    KioskProvisioner,
    KioskCreateRequest,
    wait_for_rdp_ready,
    check_socket_ready_sync,
)
from app.models.database import Base, KioskModel, CategoryModel


@pytest.fixture
def mock_jms_settings():
    return JumpServerSettings(
        base_url="http://127.0.0.1:8080",
        key_id="test-key-id-12345",
        secret_value="test-secret-value-abcdef1234567890",
        org_id="00000000-0000-0000-0000-000000000002",
        timeout=1.0,
        max_retries=3,
    )


@pytest.fixture
def in_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


# ==============================================================================
# 1. Tests for delete_asset and Idempotence (204 vs 404)
# ==============================================================================

def test_delete_asset_success_204(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)

    mock_resp = httpx.Response(204, request=httpx.Request("DELETE", "http://test/api/v1/assets/assets/asset-1/"))
    with patch("httpx.Client.request", return_value=mock_resp):
        res = client.delete_asset("asset-1")
        assert res is True


def test_delete_asset_idempotent_404(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)

    mock_resp = httpx.Response(404, text="Not Found", request=httpx.Request("DELETE", "http://test/api/v1/assets/assets/asset-missing/"))
    with patch("httpx.Client.request", return_value=mock_resp):
        res = client.delete_asset("asset-missing")
        assert res is True


def test_delete_asset_handles_empty_id(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)
    assert client.delete_asset("") is True
    assert client.delete_asset(None) is True


# ==============================================================================
# 2. Tests for wait_for_rdp_ready and Socket Readiness Gate
# ==============================================================================

@pytest.mark.asyncio
async def test_wait_for_rdp_ready_open_socket():
    # Start a real temporary TCP server on loopback
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        is_ready = await wait_for_rdp_ready("127.0.0.1", port, timeout=2.0, interval=0.1)
        assert is_ready is True


@pytest.mark.asyncio
async def test_wait_for_rdp_ready_timeout():
    # Port 59999 unlikely to be open
    is_ready = await wait_for_rdp_ready("127.0.0.1", 59999, timeout=0.3, interval=0.1)
    assert is_ready is False


def test_check_socket_ready_sync_open_and_timeout():
    # 1. Test timeout on closed port
    assert check_socket_ready_sync("127.0.0.1", 59998, timeout=0.2, interval=0.05) is False

    # 2. Test open port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert check_socket_ready_sync("127.0.0.1", port, timeout=1.0, interval=0.05) is True
    finally:
        sock.close()


def test_readiness_gate_fails_provisioning_with_provision_failed_status(mock_jms_settings, in_memory_db, monkeypatch):
    monkeypatch.setenv("KIOSK_HOST_IP", "127.0.0.1")
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    mock_client.ensure_node.return_value = "00000000-0000-0000-0000-000000000001"

    mock_docker = Mock()
    mock_docker.create_volume.return_value = "rdp_fail_test"
    mock_docker.get_container_status.return_value = {"status": "stopped", "health": "unknown"}

    jms_ops = JumpServerOperations(mock_client)
    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=mock_docker,
        jms_ops=jms_ops,
        host_ip="127.0.0.1",
    )

    req = KioskCreateRequest(
        name="READINESS-FAIL-01",
        target_ip="10.0.0.1",
        verify_rdp=True,
    )

    # Use a closed port for readiness gate to ensure timeout
    with pytest.raises(RuntimeError, match="readiness probe failed"):
        provisioner.provision(
            req,
            verify_rdp=True,
            rdp_probe_timeout=0.2,
            rdp_host="127.0.0.1",
            rdp_port=59997,
        )

    # Verify kiosk is recorded as PROVISION_FAILED
    with in_memory_db() as session:
        kiosk = session.query(KioskModel).filter(KioskModel.name == "READINESS-FAIL-01").first()
        assert kiosk is not None
        assert kiosk.status == "PROVISION_FAILED"
        assert "readiness probe failed" in kiosk.last_error

    # Verify no JumpServer asset was created
    mock_client.post.assert_not_called()


# ==============================================================================
# 3. Tests for HTTP Resilience: 401 Retry & Token Renewal, and 502/503 Backoff
# ==============================================================================

def test_client_http_retry_on_401_with_refresh(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)

    req = httpx.Request("GET", "http://127.0.0.1:8080/api/v1/assets/assets/")
    resp_401 = httpx.Response(401, text="Unauthorized", request=req)
    resp_200 = httpx.Response(200, json={"results": [{"id": "asset-1"}]}, request=req)

    call_count = 0

    def mock_request_impl(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return resp_401
        return resp_200

    refresh_called = False

    def mock_refresh():
        nonlocal refresh_called
        refresh_called = True
        return True

    client.refresh_authentication = mock_refresh

    with patch("httpx.Client.request", side_effect=mock_request_impl):
        result = client.get("/api/v1/assets/assets/")
        assert result == {"results": [{"id": "asset-1"}]}
        assert call_count == 2
        assert refresh_called is True


def test_client_http_retry_on_502_backoff(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)

    req = httpx.Request("GET", "http://127.0.0.1:8080/api/v1/assets/nodes/")
    resp_502 = httpx.Response(502, text="Bad Gateway", request=req)
    resp_200 = httpx.Response(200, json=[{"id": "node-1"}], request=req)

    call_count = 0

    def mock_request_impl(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return resp_502
        return resp_200

    with patch("httpx.Client.request", side_effect=mock_request_impl), patch("time.sleep") as mock_sleep:
        result = client.get("/api/v1/assets/nodes/")
        assert result == [{"id": "node-1"}]
        assert call_count == 3
        assert mock_sleep.call_count == 2


# ==============================================================================
# 4. Tests for Audit Tags and Comments in Asset Creation
# ==============================================================================

def test_audit_tags_and_comment_injected_in_create_rdp_asset():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "asset-audit-1", "name": "AUDIT-DEVICE"}

    ops = JumpServerOperations(mock_client)
    res = ops.create_rdp_asset(
        name="AUDIT-DEVICE",
        ip="10.10.10.10",
        port=33895,
        category_name="INFRAESTRUCTURA",
        created_by="admin-matias",
    )

    assert res["id"] == "asset-audit-1"
    post_call = mock_client.post.call_args
    payload = post_call[0][1]

    assert "Managed by Kiosk-Manager | Device: AUDIT-DEVICE | CreatedBy: admin-matias" in payload["comment"]
    assert "kiosk-manager" in payload["tags"]
    assert "ephemeral" in payload["tags"]
    assert "category:INFRAESTRUCTURA" in payload["tags"]


def test_audit_tags_and_comment_injected_in_create_asset():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.create_asset.return_value = {"id": "asset-audit-2"}

    ops = JumpServerOperations(mock_client)
    ops.create_asset({
        "name": "GENERIC-KIOSK-02",
        "address": "10.10.10.11",
        "category_name": "SWITCHES",
        "created_by": "ops-bot",
    })

    create_call = mock_client.create_asset.call_args[0][0]
    assert "Managed by Kiosk-Manager | Device: GENERIC-KIOSK-02 | CreatedBy: ops-bot" in create_call["comment"]
    assert "kiosk-manager" in create_call["tags"]
    assert "category:SWITCHES" in create_call["tags"]


# ==============================================================================
# 5. Tests for Garbage Collection and Reconciliation Job
# ==============================================================================

def test_reconcile_with_jumpserver_purges_orphans(mock_jms_settings, in_memory_db):
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings

    # JumpServer has 3 assets:
    # 1. Active kiosk in DB (ID: "asset-active")
    # 2. Orphan managed kiosk (ID: "asset-orphan-1", comment has "Managed by Kiosk-Manager")
    # 3. Unmanaged external asset (ID: "asset-manual-switch", comment "Manually created")
    mock_client.get.return_value = {
        "results": [
            {
                "id": "asset-active",
                "name": "ACTIVE-KIOSK",
                "comment": "Managed by Kiosk-Manager | Device: ACTIVE-KIOSK",
                "tags": ["kiosk-manager", "ephemeral"],
            },
            {
                "id": "asset-orphan-1",
                "name": "GHOST-KIOSK-99",
                "comment": "Managed by Kiosk-Manager | Device: GHOST-KIOSK-99",
                "tags": ["kiosk-manager", "ephemeral"],
            },
            {
                "id": "asset-manual-switch",
                "name": "CORE-CISCO-PROD",
                "comment": "Enterprise core switch",
                "tags": ["production"],
            },
        ]
    }
    mock_client.delete_asset.return_value = True

    # In local DB, only ACTIVE-KIOSK exists
    with in_memory_db() as session:
        kiosk = KioskModel(
            name="ACTIVE-KIOSK",
            device_type="generic",
            target_url="http://10.0.0.1",
            target_ip="10.0.0.1",
            rdp_port=33891,
            rdp_username="kiosk_active",
            container_name="kiosk-active",
            volume_name="rdp_active",
            jms_asset_id="asset-active",
            status="RUNNING",
        )
        session.add(kiosk)
        session.commit()

    ops = JumpServerOperations(mock_client)
    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=Mock(),
        jms_ops=ops,
    )

    res = provisioner.reconcile_with_jumpserver()

    assert res["total_jms_assets"] == 3
    assert res["managed_jms_assets"] == 2
    assert res["local_kiosks_count"] == 1
    assert res["purged_count"] == 1
    assert res["purged_assets"] == [{"id": "asset-orphan-1", "name": "GHOST-KIOSK-99"}]

    # delete_asset should be called for the orphan, NOT for active or manual switch
    mock_client.delete_asset.assert_called_once_with("asset-orphan-1")


def test_deprovision_calls_delete_asset(mock_jms_settings, in_memory_db):
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    mock_client.delete_asset.return_value = True

    mock_docker = Mock()

    with in_memory_db() as session:
        kiosk = KioskModel(
            id="kiosk-to-deprovision",
            name="DEPROV-KIOSK",
            device_type="generic",
            target_url="http://10.0.0.1",
            target_ip="10.0.0.1",
            rdp_port=33892,
            rdp_username="kiosk_deprov",
            container_name="kiosk-deprov",
            volume_name="rdp_deprov",
            jms_asset_id="asset-to-delete-123",
            jms_account_id="acc-to-delete-123",
            jms_permission_id="perm-to-delete-123",
            status="RUNNING",
        )
        session.add(kiosk)
        session.commit()

    ops = JumpServerOperations(mock_client)
    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=mock_docker,
        jms_ops=ops,
    )

    success = provisioner.deprovision("kiosk-to-deprovision")
    assert success is True

    mock_client.delete_asset.assert_called_once_with("asset-to-delete-123")
    mock_docker.stop_and_remove_container.assert_called_once_with("kiosk-deprov")
    mock_docker.remove_volume.assert_called_once_with("rdp_deprov")

    with in_memory_db() as session:
        assert session.query(KioskModel).get("kiosk-to-deprovision") is None


def test_reconcile_api_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.basic_auth import verify_credentials

    app.dependency_overrides[verify_credentials] = lambda: "admin"

    mock_res = {
        "total_jms_assets": 5,
        "managed_jms_assets": 2,
        "local_kiosks_count": 1,
        "purged_count": 1,
        "purged_assets": [{"id": "orphan-1", "name": "ORPHAN-1"}],
    }

    with patch("app.api.routes.provisioner.reconcile_with_jumpserver", return_value=mock_res):
        client = TestClient(app)
        resp1 = client.post("/api/kiosks/reconcile-jms")
        assert resp1.status_code == 200
        assert resp1.json()["purged_count"] == 1

        resp2 = client.post("/api/kiosk/reconcile-jms")
        assert resp2.status_code == 200
        assert resp2.json()["purged_count"] == 1

    app.dependency_overrides.clear()


def test_stop_session_frees_ram(mock_jms_settings, in_memory_db):
    mock_docker = Mock()
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings

    with in_memory_db() as session:
        kiosk = KioskModel(
            id="kiosk-to-stop",
            name="RUNNING-KIOSK",
            device_type="generic",
            target_url="http://10.0.0.1",
            target_ip="10.0.0.1",
            rdp_port=33893,
            rdp_username="kiosk_running",
            container_name="kiosk-running",
            volume_name="rdp_running",
            status="RUNNING",
        )
        session.add(kiosk)
        session.commit()

    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=mock_docker,
        jms_ops=JumpServerOperations(mock_client),
    )

    success = provisioner.stop_session("kiosk-to-stop")
    assert success is True

    mock_docker.stop_container.assert_called_once_with("kiosk-running")

    with in_memory_db() as session:
        k = session.query(KioskModel).get("kiosk-to-stop")
        assert k.status == "IDLE"


def test_stop_session_api_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.basic_auth import verify_credentials

    app.dependency_overrides[verify_credentials] = lambda: "admin"

    with patch("app.api.routes.provisioner.stop_session", return_value=True):
        client = TestClient(app)
        resp = client.post("/api/kiosks/test-kiosk-1/stop")
        assert resp.status_code == 200
        assert resp.json() == {"status": "stopped", "kiosk_id": "test-kiosk-1"}

    app.dependency_overrides.clear()


