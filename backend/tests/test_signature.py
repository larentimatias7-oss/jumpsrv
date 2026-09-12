import pytest
from app.jumpserver.signature import build_signature_header, signed_headers


def test_signature_header_generation():
    method = "GET"
    path = "/api/v1/assets/assets/?limit=3"
    date = "Fri, 11 Sep 2026 14:00:00 GMT"
    org_id = "00000000-0000-0000-0000-000000000002"
    key_id = "test-key-id-123"
    secret = "secret-key-for-test"

    header = build_signature_header(
        method=method,
        path=path,
        date_rfc1123=date,
        org_id=org_id,
        key_id=key_id,
        secret=secret,
    )

    assert header.startswith('Signature keyid="test-key-id-123",algorithm="hmac-sha256",headers="(request-target) date x-jms-org",signature="')
    assert header.endswith('"')


def test_signed_headers():
    headers = signed_headers(
        method="POST",
        path="/api/v1/assets/assets/",
        key_id="test-key",
        secret="test-secret",
        org_id="00000000-0000-0000-0000-000000000002",
    )
    assert "Date" in headers
    assert "X-JMS-ORG" in headers
    assert "Authorization" in headers
    assert headers["X-JMS-ORG"] == "00000000-0000-0000-0000-000000000002"


def test_jumpserver_config_org_id(monkeypatch):
    from app.jumpserver.config import JumpServerConfig

    # Default
    cfg = JumpServerConfig()
    assert cfg.org_id == "00000000-0000-0000-0000-000000000002"

    # From JUMPSERVER_ORG_ID
    monkeypatch.setenv("JUMPSERVER_ORG_ID", "11111111-2222-3333-4444-555555555555")
    cfg_custom = JumpServerConfig()
    assert cfg_custom.org_id == "11111111-2222-3333-4444-555555555555"


def test_client_x_jms_org_header():
    from app.jumpserver.client import JumpServerClient
    from app.jumpserver.config import JumpServerConfig

    cfg = JumpServerConfig(
        base_url="https://127.0.0.1:80",
        key_id="key-1",
        secret_value="secret-val",
        org_id="custom-org-uuid",
    )
    client = JumpServerClient(settings=cfg)
    headers = client._headers("GET", "/api/v1/assets/nodes/")
    assert headers["X-JMS-ORG"] == "custom-org-uuid"

