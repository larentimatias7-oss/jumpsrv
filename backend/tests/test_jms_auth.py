from __future__ import annotations
import httpx
import pytest
from unittest.mock import Mock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.jms_auth import verify_jumpserver_session, get_current_user
from app.jumpserver.client import JumpServerClient
from app.jumpserver.config import JumpServerSettings
from app.jumpserver.operations import JumpServerOperations
from app.main import app


@pytest.fixture
def test_jms_settings():
    return JumpServerSettings(
        base_url="http://mock-jms:80",
        key_id="test-key-id",
        secret_value="test-secret-value",
        org_id="00000000-0000-0000-0000-000000000002",
        verify_ssl=False,
        public_url="http://172.30.20.62:8000",
    )


# ==============================================================================
# 1. Tests for Delegated Session Verification (jms_auth.py)
# ==============================================================================

def test_verify_session_with_valid_cookie(test_jms_settings):
    mock_request = Mock()
    mock_request.cookies = {"jms_sessionid": "valid-session-123"}
    mock_request.headers = {}

    fake_profile = {
        "id": "user-uuid-1",
        "username": "operador.redes",
        "name": "Operador Redes",
        "email": "operador@milicic.com.ar",
        "roles": [{"id": "r1", "name": "Auditor"}, {"id": "r2", "name": "User"}],
        "is_service_account": False,
    }

    mock_resp = httpx.Response(
        200,
        json=fake_profile,
        request=httpx.Request("GET", "http://mock-jms:80/api/v1/users/profile/"),
    )

    with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
        user = verify_jumpserver_session(mock_request, settings=test_jms_settings)
        assert user["id"] == "user-uuid-1"
        assert user["username"] == "operador.redes"
        assert user["name"] == "Operador Redes"
        assert user["email"] == "operador@milicic.com.ar"
        assert "Auditor" in user["roles"]
        assert user["is_service_account"] is False

        mock_get.assert_called_once()
        headers = mock_get.call_args[1].get("headers", {})
        assert headers["Cookie"] == "jms_sessionid=valid-session-123"
        assert headers["X-JMS-ORG"] == test_jms_settings.org_id


def test_verify_session_with_valid_bearer_token(test_jms_settings):
    mock_request = Mock()
    mock_request.cookies = {}
    mock_request.headers = {"Authorization": "Bearer jwt-token-abc"}

    fake_profile = {
        "id": "user-uuid-2",
        "username": "admin.infra",
        "name": "Admin Infra",
        "roles": ["Administrator"],
    }

    mock_resp = httpx.Response(
        200,
        json=fake_profile,
        request=httpx.Request("GET", "http://mock-jms:80/api/v1/users/profile/"),
    )

    with patch("httpx.Client.get", return_value=mock_resp):
        user = verify_jumpserver_session(mock_request, settings=test_jms_settings)
        assert user["username"] == "admin.infra"
        assert "Administrator" in user["roles"]


def test_verify_session_expired_cookie_raises_401(test_jms_settings):
    mock_request = Mock()
    mock_request.cookies = {"jms_sessionid": "expired-cookie-999"}
    mock_request.headers = {}

    mock_resp = httpx.Response(
        401,
        json={"detail": "Authentication credentials were not provided or expired."},
        request=httpx.Request("GET", "http://mock-jms:80/api/v1/users/profile/"),
    )

    with patch("httpx.Client.get", return_value=mock_resp):
        with pytest.raises(HTTPException) as exc_info:
            verify_jumpserver_session(mock_request, settings=test_jms_settings)
        assert exc_info.value.status_code == 401
        assert "JumpServer session not found or expired" in exc_info.value.detail


def test_verify_session_missing_credentials_raises_401(test_jms_settings):
    mock_request = Mock()
    mock_request.cookies = {}
    mock_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        verify_jumpserver_session(mock_request, settings=test_jms_settings)
    assert exc_info.value.status_code == 401


def test_verify_session_basic_auth_fallback(test_jms_settings):
    mock_request = Mock()
    mock_request.cookies = {}
    # Base64 for admin:admin
    mock_request.headers = {"Authorization": "Basic YWRtaW46YWRtaW4="}

    user = verify_jumpserver_session(mock_request, settings=test_jms_settings)
    assert user["username"] == "admin"
    assert "Admin" in user["roles"]


# ==============================================================================
# 2. Tests for Protected API Endpoints (/api/auth/me, /api/kiosks)
# ==============================================================================

def test_api_auth_me_endpoint_with_valid_session():
    client = TestClient(app)

    fake_user = {
        "id": "operator-id",
        "username": "operador.redes",
        "name": "Operador Redes",
        "email": "operador@milicic.com.ar",
        "roles": ["Auditor"],
        "is_service_account": False,
    }

    with patch("app.auth.jms_auth.verify_jumpserver_session", return_value=fake_user):
        resp = client.get("/api/auth/me", cookies={"jms_sessionid": "valid-session-test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "operador.redes"
        assert data["name"] == "Operador Redes"
        assert "Auditor" in data["roles"]


def test_api_endpoints_blocked_without_session():
    client = TestClient(app)
    # Call without cookies or headers
    resp = client.get("/api/kiosks")
    assert resp.status_code == 401

    resp_auth = client.get("/api/auth/me")
    assert resp_auth.status_code == 401


# ==============================================================================
# 3. Tests for Web Application Registration ("Agregar Sitio WEB")
# ==============================================================================

def test_ensure_web_application_creates_new(test_jms_settings):
    client = JumpServerClient(test_jms_settings)

    # 1. First search returns empty list
    with patch.object(client, "list_web_applications", return_value=[]):
        with patch.object(client, "create_web_application", return_value={"id": "app-new-1", "name": "Agregar Sitio WEB"}) as mock_create:
            res = client.ensure_web_application_asset("Agregar Sitio WEB", "http://172.30.20.62:8000")
            assert res.get("id") == "app-new-1"
            mock_create.assert_called_once_with(
                name="Agregar Sitio WEB",
                url="http://172.30.20.62:8000",
            )


def test_ensure_web_application_idempotent_existing(test_jms_settings):
    client = JumpServerClient(test_jms_settings)

    existing_app = {
        "id": "app-existing-99",
        "name": "Agregar Sitio WEB",
        "attrs": {"url": "http://172.30.20.62:8000"},
    }

    # Search finds existing application
    with patch.object(client, "list_web_applications", return_value=[existing_app]):
        with patch.object(client, "create_web_application") as mock_create:
            res = client.ensure_web_application_asset("Agregar Sitio WEB", "http://172.30.20.62:8000")
            assert res.get("id") == "app-existing-99"
            mock_create.assert_not_called()


def test_create_web_application_payload_format(test_jms_settings):
    client = JumpServerClient(test_jms_settings)

    with patch.object(client, "post", return_value={"id": "app-created-1"}) as mock_post:
        res = client.create_web_application("Agregar Sitio WEB", "http://172.30.20.62:8000")
        assert res["id"] == "app-created-1"
        mock_post.assert_called_once_with(
            "/api/v1/applications/applications/",
            {
                "name": "Agregar Sitio WEB",
                "type": "web",
                "category": "web",
                "attrs": {
                    "url": "http://172.30.20.62:8000",
                },
                "comment": "Acceso directo a la plataforma Kiosk Manager",
            },
        )


def test_create_kiosk_injects_operator_in_forensic_metadata():
    client = TestClient(app)

    fake_user = {
        "id": "operator-xyz",
        "username": "matias.larenti",
        "name": "Matias Larenti",
        "roles": ["Admin"],
    }

    mock_provision_result = {
        "id": "new-kiosk-id",
        "name": "TEST-FORENSIC",
        "rdp_port": 33895,
        "status": "RUNNING",
    }

    payload = {
        "name": "TEST-FORENSIC",
        "device_type": "generic",
        "target_ip": "10.10.10.10",
        "target_protocol": "https",
        "target_port": 443,
    }

    with patch("app.auth.jms_auth.verify_jumpserver_session", return_value=fake_user):
        with patch("app.api.routes.provisioner.provision", return_value=mock_provision_result) as mock_prov:
            with patch("app.main.dispatcher.start_listening_for_kiosk") as mock_listen:
                resp = client.post(
                    "/api/kiosks",
                    json=payload,
                    cookies={"jms_sessionid": "valid-session"},
                )
                assert resp.status_code == 201
                mock_prov.assert_called_once()
                # Verify created_by was passed as the operator username
                _, kwargs = mock_prov.call_args
                assert kwargs.get("created_by") == "matias.larenti"


def test_effective_base_url_auto_upgrades_standard_http():
    from app.auth.jms_auth import get_effective_base_url, _effective_base_urls
    _effective_base_urls.clear()

    cfg_prod = JumpServerSettings(
        base_url="http://172.30.20.62",
        key_id="test-key",
        secret_value="test-secret",
    )
    # Production IP without mock prefix should be upgraded to https
    effective = get_effective_base_url(cfg_prod)
    assert effective == "https://172.30.20.62"


def test_effective_base_url_preserves_mock_and_caches_redirect():
    from app.auth.jms_auth import get_effective_base_url, _cache_redirect_url, _effective_base_urls
    _effective_base_urls.clear()

    cfg_mock = JumpServerSettings(
        base_url="http://mock-jms:80",
        key_id="test-key",
        secret_value="test-secret",
    )
    # Mock stays http
    effective = get_effective_base_url(cfg_mock)
    assert effective == "http://mock-jms:80"

    # Simulate receiving a 307 redirect to https
    mock_resp = httpx.Response(
        200,
        request=httpx.Request("GET", "https://mock-jms/api/v1/users/profile/"),
        history=[httpx.Response(307, headers={"Location": "https://mock-jms/api/v1/users/profile/"})],
    )
    _cache_redirect_url("mock-jms", mock_resp)

    # Subsequent call should use the cached https URL
    effective_after = get_effective_base_url(cfg_mock)
    assert effective_after == "https://mock-jms"

