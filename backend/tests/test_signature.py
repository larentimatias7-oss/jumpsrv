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
