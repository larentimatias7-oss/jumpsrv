from __future__ import annotations
import pytest
import httpx
from unittest.mock import patch

from app.jumpserver.config import JumpServerConfig, JumpServerSettings
from app.jumpserver.client import JumpServerClient


def test_url_normalization_strips_default_ports():
    """Verify that default HTTP (80) and HTTPS (443) ports are normalized in base_url."""
    # HTTP port 80 normalized
    cfg_http = JumpServerConfig(
        base_url="http://172.30.20.62:80",
        key_id="test-key",
        secret_value="test-secret",
    )
    client_http = JumpServerClient(settings=cfg_http)
    assert client_http._base == "http://172.30.20.62"
    assert client_http._target_host == "172.30.20.62"

    # HTTPS port 443 normalized
    cfg_https = JumpServerConfig(
        base_url="https://172.30.20.62:443",
        key_id="test-key",
        secret_value="test-secret",
    )
    client_https = JumpServerClient(settings=cfg_https)
    assert client_https._base == "https://172.30.20.62"

    # Custom port preserved
    cfg_custom = JumpServerConfig(
        base_url="https://172.30.20.62:8443",
        key_id="test-key",
        secret_value="test-secret",
    )
    client_custom = JumpServerClient(settings=cfg_custom)
    assert client_custom._base == "https://172.30.20.62:8443"


def test_jms_url_env_alias(monkeypatch):
    """Verify that JMS_URL is recognized as an alias for base_url."""
    monkeypatch.delenv("JMS_BASE_URL", raising=False)
    monkeypatch.delenv("JUMPSERVER_BASE_URL", raising=False)
    monkeypatch.setenv("JMS_URL", "http://172.30.20.62:8000")
    cfg = JumpServerConfig()
    assert cfg.base_url == "http://172.30.20.62:8000"


def test_client_follows_307_redirect_and_preserves_auth_headers():
    """
    Verify that when JumpServer returns a 307 Temporary Redirect from http:// to https://,
    JumpServerClient follows the redirect, preserves auth headers, and updates _base.
    """
    target_host = "172.30.20.62"
    captured_requests = []

    def mock_handler(req: httpx.Request) -> httpx.Response:
        captured_requests.append({
            "url": str(req.url),
            "scheme": req.url.scheme,
            "host": req.url.host,
            "auth": req.headers.get("authorization"),
            "org": req.headers.get("x-jms-org"),
            "accept": req.headers.get("accept"),
        })

        # If HTTP, redirect to HTTPS 307
        if req.url.scheme == "http":
            loc = str(req.url.copy_with(scheme="https"))
            return httpx.Response(307, headers={"Location": loc}, text="<html>307 Redirect</html>")

        # When HTTPS, return JSON response
        return httpx.Response(
            200,
            json=[{"id": "app-1", "name": "Agregar Sitio WEB", "type": "web"}],
        )

    transport = httpx.MockTransport(mock_handler)

    cfg = JumpServerConfig(
        base_url="http://172.30.20.62",
        key_id="dummy-key-id",
        secret_value="dummy-secret-value",
        org_id="00000000-0000-0000-0000-000000000002",
        verify_ssl=False,
    )
    client = JumpServerClient(settings=cfg)

    # Patch httpx.Client in client._request to use our mock transport
    original_client_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_client_init(self, *args, **kwargs)

    with patch.object(httpx.Client, "__init__", patched_init):
        res = client.get("/api/v1/applications/applications/", type="web")

    # Verify response is valid JSON parsed
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0]["id"] == "app-1"

    # Verify both requests happened (initial HTTP and redirected HTTPS)
    assert len(captured_requests) == 2
    req_http = captured_requests[0]
    req_https = captured_requests[1]

    assert req_http["scheme"] == "http"
    assert req_https["scheme"] == "https"
    assert req_https["auth"] is not None
    assert "Signature" in req_https["auth"]
    assert req_https["org"] == "00000000-0000-0000-0000-000000000002"

    # Verify client auto-upgraded _base to https://
    assert client._base == "https://172.30.20.62"


def test_ensure_web_application_handles_non_json_or_empty_response():
    """
    Verify that if the endpoint returns a non-JSON or empty response (e.g. 204 or unparseable),
    ensure_web_application_asset handles it safely without crashing.
    """
    cfg = JumpServerConfig(
        base_url="https://172.30.20.62",
        key_id="dummy-key-id",
        secret_value="dummy-secret-value",
    )
    client = JumpServerClient(settings=cfg)

    # list_web_applications returns empty
    with patch.object(client, "list_web_applications", return_value=[]):
        # create_web_application returns empty dict (e.g. 204 No Content or parsed fallback)
        with patch.object(client, "create_web_application", return_value={}):
            result = client.ensure_web_application_asset("Agregar Sitio WEB", "http://172.30.20.62:8000")
            assert result == {}


def test_handle_response_safely_catches_invalid_json():
    """
    Verify that _handle_response doesn't crash with JSONDecodeError when server
    returns 200/201 but with non-JSON text.
    """
    cfg = JumpServerConfig(
        base_url="https://172.30.20.62",
        key_id="dummy-key-id",
        secret_value="dummy-secret-value",
    )
    client = JumpServerClient(settings=cfg)

    # Simulated response with text/html body on 200 OK
    raw_resp = httpx.Response(
        200,
        content=b"<html>Unexpected HTML</html>",
        request=httpx.Request("GET", "https://172.30.20.62/api/v1/test"),
    )

    res = client._handle_response(raw_resp, "GET", "/api/v1/test")
    assert res == {}
