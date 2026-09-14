from __future__ import annotations
import logging
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from .config import JumpServerSettings, get_jms_settings
from .signature import signed_headers
from .exceptions import (
    JumpServerAuthError,
    JumpServerError,
    JumpServerNetworkError,
    JumpServerValidationError,
)

logger = logging.getLogger("kiosk.jumpserver")


class JumpServerClient:
    def __init__(self, settings: JumpServerSettings | None = None) -> None:
        self.config = settings or get_jms_settings()
        self._s = self.config
        parsed = urlparse(self.config.base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid base_url scheme: {parsed.scheme}")
        self._base = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        self._secret = self.config.load_secret()
        self._verify = str(self.config.ca_bundle) if self.config.ca_bundle else self.config.verify_ssl
        logger.debug("JumpServerClient initialized: base_url=%s, verify_ssl=%s", self._base, self._verify)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        key_id = self.config.get_key_id()
        secret = self.config.load_secret()

        if not key_id or not secret:
            raise JumpServerAuthError(
                "JumpServer AccessKey is not configured (missing JMS_KEY_ID / JMS_SECRET_KEY). "
                "Please configure credentials in /opt/jumpsrv/.env or ensure /var/run/docker.sock is mounted."
            )

        headers = signed_headers(
            method=method,
            path=path,
            key_id=key_id,
            secret=secret,
            org_id=self.config.org_id,
        )
        headers["X-JMS-ORG"] = self.config.org_id
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        if not path.startswith("/"):
            path = "/" + path

        req = httpx.Request(method, self._base + path, params=params or {})
        signed_path = req.url.raw_path.decode("ascii")

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                with httpx.Client(
                    base_url=self._base,
                    verify=self._verify,
                    timeout=self.config.timeout,
                    headers={
                        "Accept": "application/json",
                        "X-JMS-ORG": self.config.org_id,
                    },
                ) as http:
                    headers = self._headers(method, signed_path)
                    resp = http.request(
                        method,
                        signed_path,
                        headers=headers,
                        json=json_body,
                    )
                return self._handle_response(resp, method, signed_path)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = JumpServerNetworkError(
                    f"{method} {signed_path}: {e}", attempt=attempt
                )
                logger.warning(
                    "retry %d/%d %s %s: %s",
                    attempt, self.config.max_retries, method, signed_path, e,
                )
                time.sleep(min(2 ** attempt, 8))
        if last_exc:
            raise last_exc
        raise JumpServerError(f"Request failed unexpectedly: {method} {path}")

    def _handle_response(
        self, resp: httpx.Response, method: str, path: str
    ) -> dict[str, Any] | list[Any]:
        if resp.status_code == 401:
            raise JumpServerAuthError(f"{method} {path}: 401 Unauthorized - check Access Key & Secret")
        if resp.status_code == 400:
            raise JumpServerValidationError(
                f"{method} {path}: 400 Bad Request: {resp.text[:500]}"
            )
        if resp.status_code >= 400:
            raise JumpServerError(
                f"{method} {path}: {resp.status_code} Error: {resp.text[:500]}"
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json_body=body or {})

    def put(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("PUT", path, json_body=body or {})

    def patch(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, json_body=body or {})

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)
