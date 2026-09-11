from __future__ import annotations
import base64
import hashlib
import hmac
from email.utils import formatdate

SIGN_HEADERS = ("(request-target)", "date", "x-jms-org")


def build_signature_header(
    method: str,
    path: str,
    date_rfc1123: str,
    org_id: str,
    key_id: str,
    secret: str,
    algorithm: str = "hmac-sha256",
) -> str:
    """Builds RFC compliant Signature authorization header for JumpServer 4.x.
    
    Verified in JumpServer core apps/common/auth/signature.py
    """
    lines = [
        f"(request-target): {method.lower()} {path}",
        f"date: {date_rfc1123}",
        f"x-jms-org: {org_id}",
    ]
    signing_string = "\n".join(lines)

    digest = hmac.new(
        secret.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = base64.b64encode(digest).decode("ascii")

    headers_spec = " ".join(SIGN_HEADERS)
    return (
        f'Signature keyid="{key_id}",'
        f'algorithm="{algorithm}",'
        f'headers="{headers_spec}",'
        f'signature="{signature_b64}"'
    )


def signed_headers(
    method: str,
    path: str,
    key_id: str,
    secret: str,
    org_id: str,
) -> dict[str, str]:
    """Generates standard request headers with signature and GMT timestamp."""
    date = formatdate(usegmt=True)
    return {
        "Date": date,
        "X-JMS-ORG": org_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": build_signature_header(
            method=method,
            path=path,
            date_rfc1123=date,
            org_id=org_id,
            key_id=key_id,
            secret=secret,
        ),
    }
