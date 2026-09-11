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
        self._s = settings or get_jms_settings()
        parsed = urlparse(self._s.base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid base_url scheme: {parsed.scheme}")
        self._base = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        self._secret = self._s.load_secret()
        self._verify = str(self._s.ca_bundle) if self._s.ca_bundle else self._s.verify_ssl

    def _headers(self, method: str, path: str) -> dict[str, str]:
        return signed_headers(
            method=method,
            path=path,
            key_id=self._s.key_id,
            secret=self._secret,
            org_id=self._s.org_id,
        )

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
        for attempt in range(1, self._s.max_retries + 1):
            try:
                with httpx.Client(
                    base_url=self._base,
                    verify=self._verify,
                    timeout=self._s.timeout,
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
                    attempt, self._s.max_retries, method, signed_path, e,
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

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", path, json_body=body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)
