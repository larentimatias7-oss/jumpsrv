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
        
        # Normalize netloc: strip default port 80 for http, 443 for https
        port = parsed.port
        host = parsed.hostname or parsed.netloc
        if (parsed.scheme == "http" and port in (80, None)) or (parsed.scheme == "https" and port in (443, None)):
            netloc = host
        else:
            netloc = f"{host}:{port}" if port else host

        self._base = f"{parsed.scheme}://{netloc}".rstrip("/")
        self._target_host = host
        self._secret = self.config.load_secret()
        self._verify = str(self.config.ca_bundle) if self.config.ca_bundle else self.config.verify_ssl
        logger.debug("JumpServerClient initialized: base_url=%s, verify_ssl=%s", self._base, self._verify)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        # If active session token exists, prioritize Bearer token auth
        if getattr(self, "_token", None):
            return {
                "Authorization": f"Bearer {self._token}",
                "X-JMS-ORG": self.config.org_id,
                "Accept": "application/json",
            }

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

    def authenticate_token(self, username: str | None = None, password: str | None = None) -> str | None:
        """Execute authentication via /api/v1/authentication/auth/ to obtain and cache session token."""
        user = username or os.getenv("JMS_USERNAME") or os.getenv("JUMPSERVER_USERNAME")
        pwd = password or os.getenv("JMS_PASSWORD") or os.getenv("JUMPSERVER_PASSWORD")
        if not user or not pwd:
            return None
        try:
            auth_headers = {"X-JMS-ORG": self.config.org_id, "Accept": "application/json"}

            def _redirect_token_hook(req: httpx.Request) -> None:
                if getattr(self, "_target_host", None) and req.url.host == self._target_host:
                    for k, v in auth_headers.items():
                        if k not in req.headers and v:
                            req.headers[k] = v

            with httpx.Client(
                base_url=self._base,
                verify=self._verify,
                timeout=self.config.timeout,
                follow_redirects=True,
                event_hooks={"request": [_redirect_token_hook]},
            ) as http:
                resp = http.post(
                    "/api/v1/authentication/auth/",
                    json={"username": user, "password": pwd},
                    headers=auth_headers,
                )
                if resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                    except Exception:
                        data = {}
                    tok = data.get("token") or data.get("access_token") or data.get("keyword")
                    if tok:
                        self._token = tok
                        logger.info("Successfully refreshed session token via /api/v1/authentication/auth/")
                        return tok
        except Exception as e:
            logger.warning("Token re-authentication via /api/v1/authentication/auth/ failed: %s", e)
        return None

    def refresh_authentication(self) -> bool:
        """
        Invalidates cached tokens and credentials.
        Attempts re-authentication via /api/v1/authentication/auth/ if user/pass configured,
        otherwise refreshes AccessKey from cache or Docker autodiscovery.
        """
        self._token = None
        tok = self.authenticate_token()
        if tok:
            return True

        try:
            from .autodiscovery import invalidate_cached_credentials
            invalidate_cached_credentials()
            self.config.key_id = ""
            self.config.secret_value = ""
            k_id = self.config.get_key_id()
            sec = self.config.load_secret()
            self._secret = sec
            logger.info("Refreshed JumpServer authentication credentials: key_id=%s", k_id)
            return bool(k_id and sec)
        except Exception as e:
            logger.warning("Failed to refresh JumpServer authentication: %s", e)
            return False

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
                headers = self._headers(method, signed_path)

                def _redirect_hook(r: httpx.Request) -> None:
                    if getattr(self, "_target_host", None) and r.url.host == self._target_host:
                        for k, v in headers.items():
                            if k not in r.headers and v:
                                r.headers[k] = v

                with httpx.Client(
                    base_url=self._base,
                    verify=self._verify,
                    timeout=self.config.timeout,
                    follow_redirects=True,
                    event_hooks={"request": [_redirect_hook]},
                    headers={
                        "Accept": "application/json",
                        "X-JMS-ORG": self.config.org_id,
                    },
                ) as http:
                    resp = http.request(
                        method,
                        signed_path,
                        headers=headers,
                        json=json_body,
                    )

                # If redirected on the same host (e.g. 307 http -> https), normalize base URL for future requests
                if resp.history and getattr(self, "_target_host", None) and resp.url.host == self._target_host:
                    scheme = resp.url.scheme
                    port = resp.url.port
                    host = resp.url.host
                    if (scheme == "https" and port in (443, None)) or (scheme == "http" and port in (80, None)):
                        new_base = f"{scheme}://{host}"
                    else:
                        new_base = f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"
                    if new_base != self._base:
                        logger.info("Auto-updating JumpServer base URL after redirect: %s -> %s", self._base, new_base)
                        self._base = new_base

                # 1. Check for transient gateway errors (502, 503, 504)
                if resp.status_code in (502, 503, 504) and attempt < self.config.max_retries:
                    backoff = min(1.0 * (2 ** (attempt - 1)), 4.0)
                    logger.warning(
                        "JumpServer returned HTTP %d on attempt %d/%d for %s %s. Retrying in %.1fs...",
                        resp.status_code, attempt, self.config.max_retries, method, signed_path, backoff
                    )
                    time.sleep(backoff)
                    continue

                # 2. Check for auth errors (401, 403) requiring token/credentials renewal
                if resp.status_code in (401, 403) and attempt < self.config.max_retries:
                    logger.warning(
                        "JumpServer returned HTTP %d on attempt %d/%d for %s %s. Refreshing auth credentials...",
                        resp.status_code, attempt, self.config.max_retries, method, signed_path
                    )
                    refreshed = self.refresh_authentication()
                    if refreshed:
                        time.sleep(0.5)
                        continue

                return self._handle_response(resp, method, signed_path)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = JumpServerNetworkError(
                    f"{method} {signed_path}: {e}", attempt=attempt
                )
                backoff = min(1.0 * (2 ** (attempt - 1)), 4.0)
                logger.warning(
                    "retry %d/%d %s %s: %s (backing off %.1fs)",
                    attempt, self.config.max_retries, method, signed_path, e, backoff
                )
                time.sleep(backoff)
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
        if resp.status_code == 404:
            raise JumpServerError(f"{method} {path}: 404 Not Found")
        if resp.status_code >= 400:
            raise JumpServerError(
                f"{method} {path}: {resp.status_code} Error: {resp.text[:500]}"
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except Exception as e:
            logger.warning(
                "%s %s: Non-JSON response (%s) with status %d: %s",
                method, path, e, resp.status_code, resp.text[:200]
            )
            return {}

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

    def list_nodes(self) -> list[dict[str, Any]]:
        """Fetch all asset nodes from /api/v1/assets/nodes/."""
        res = self.get("/api/v1/assets/nodes/")
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            return res.get("results", [])
        return []

    def get_node_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a node matching `name` case-insensitively by its value or name."""
        if not name:
            return None
        target = name.strip().lower()
        nodes = self.list_nodes()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            val = str(node.get("value", "")).strip().lower()
            nm = str(node.get("name", "")).strip().lower()
            if val == target or nm == target:
                return node
        return None

    def create_node(self, value: str, parent_id: str | None = None) -> dict[str, Any]:
        """Create a new asset node via POST /api/v1/assets/nodes/."""
        clean_value = value.strip()
        payload: dict[str, Any] = {"value": clean_value}

        if parent_id:
            payload["parent"] = parent_id
        else:
            # Resolve default root node if available
            root_id = None
            nodes = self.list_nodes()
            for node in nodes:
                if isinstance(node, dict):
                    v = str(node.get("value", "")).strip().upper()
                    n = str(node.get("name", "")).strip().upper()
                    if v == "DEFAULT" or n == "DEFAULT" or v == "/" or n == "/":
                        root_id = node.get("id")
                        break
            if not root_id and nodes and isinstance(nodes[0], dict):
                for node in nodes:
                    if isinstance(node, dict) and not node.get("parent"):
                        root_id = node.get("id")
                        break
                if not root_id:
                    root_id = nodes[0].get("id")
            if root_id:
                payload["parent"] = str(root_id)

        return self.post("/api/v1/assets/nodes/", payload)

    def ensure_node(self, name: str) -> str:
        """Verify if node exists by name; return its UUID. If missing, create dynamically and return UUID."""
        if not name or not name.strip():
            name = getattr(self.config, "default_node_name", "SWITCHES ROSARIO")

        clean_name = name.strip()

        # Check static default node id if configured and names match
        configured_default_name = getattr(self.config, "default_node_name", "SWITCHES ROSARIO")
        configured_default_id = getattr(self.config, "default_node_id", None)
        if configured_default_id and clean_name.lower() == configured_default_name.strip().lower():
            return str(configured_default_id)

        # 1. Look for existing node
        existing = self.get_node_by_name(clean_name)
        if existing and existing.get("id"):
            return str(existing["id"])

        # 2. Try creating dynamically
        try:
            created = self.create_node(value=clean_name)
            node_id = created.get("id")
            if node_id:
                return str(node_id)
        except JumpServerValidationError as ve:
            logger.info("Node creation returned validation error, re-checking nodes: %s", ve)
            existing = self.get_node_by_name(clean_name)
            if existing and existing.get("id"):
                return str(existing["id"])
            raise
        except Exception as e:
            logger.warning("Failed to create node '%s', retrying lookup: %s", clean_name, e)
            existing = self.get_node_by_name(clean_name)
            if existing and existing.get("id"):
                return str(existing["id"])
            raise

        raise JumpServerError(f"Unable to ensure node with name '{clean_name}'")

    def delete_node(self, node_id: str) -> bool:
        """Safely delete node if it has no active assets; log warning if deletion fails."""
        try:
            self.delete(f"/api/v1/assets/nodes/{node_id}/")
            return True
        except Exception as e:
            logger.warning("Could not delete JumpServer node %s (may contain assets or insufficient permissions): %s", node_id, e)
            return False

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create asset in JumpServer via /api/v1/assets/assets/."""
        return self.post("/api/v1/assets/assets/", payload)

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Safely update an asset in JumpServer, trying /api/v1/assets/assets/{asset_id}/ first,
        falling back to /api/v1/assets/hosts/{asset_id}/."""
        if not asset_id:
            raise ValueError("asset_id is required to update asset")
        try:
            return self.patch(f"/api/v1/assets/assets/{asset_id}/", data)
        except Exception as e:
            logger.debug("PATCH /api/v1/assets/assets/%s/ failed (%s), falling back to /hosts/", asset_id, e)
            return self.patch(f"/api/v1/assets/hosts/{asset_id}/", data)

    def delete_asset(self, asset_id: str) -> bool:
        """Safely and idempotently delete asset in JumpServer via /api/v1/assets/assets/{asset_id}/.
        Treats 404 Not Found as success (already deleted)."""
        if not asset_id:
            return True
        try:
            self.delete(f"/api/v1/assets/assets/{asset_id}/")
            return True
        except JumpServerError as jse:
            err_msg = str(jse)
            if "404" in err_msg or "Not Found" in err_msg:
                logger.info("Asset %s already deleted or not found in JumpServer (idempotent)", asset_id)
                return True
            logger.warning("Failed to delete JumpServer asset %s: %s", asset_id, jse)
            return False
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "Not Found" in err_msg:
                return True
            logger.warning("Unexpected error deleting JumpServer asset %s: %s", asset_id, e)
            return False

    def list_web_applications(self, name: str | None = None) -> list[dict[str, Any]]:
        """List web applications registered in JumpServer via /api/v1/applications/applications/."""
        params: dict[str, Any] = {"type": "web"}
        if name:
            params["name"] = name
        try:
            res = self.get("/api/v1/applications/applications/", **params)
            if isinstance(res, list):
                return [item for item in res if isinstance(item, dict)]
            if isinstance(res, dict):
                results = res.get("results", [])
                if isinstance(results, list):
                    return [item for item in results if isinstance(item, dict)]
                if res.get("id") or res.get("name"):
                    return [res]
        except JumpServerError as jse:
            if "404" in str(jse) or "Not Found" in str(jse):
                raise
            logger.warning("Failed to list web applications from JumpServer: %s", jse)
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                raise
            logger.warning("Failed to list web applications from JumpServer: %s", e)
        return []

    def get_web_application_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a web application by its exact name."""
        if not name:
            return None
        target = name.strip().lower()
        apps = self.list_web_applications(name=name)
        for app in apps:
            if isinstance(app, dict) and app.get("name", "").strip().lower() == target:
                return app
        return None

    def create_web_application(
        self,
        name: str,
        url: str,
        comment: str = "Acceso directo a la plataforma Kiosk Manager",
    ) -> dict[str, Any]:
        """Create a new Web Application in JumpServer."""
        payload = {
            "name": name,
            "type": "web",
            "category": "web",
            "attrs": {
                "url": url,
            },
            "comment": comment,
        }
        res = self.post("/api/v1/applications/applications/", payload)
        if isinstance(res, dict):
            return res
        return {}

    def ensure_web_application_asset(
        self,
        name: str = "Agregar Sitio WEB",
        public_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Idempotently ensure that the Kiosk Manager web application exists in JumpServer.
        If already present, returns the existing record. If missing, registers it.
        If the JumpServer edition does not support the /api/v1/applications/applications/
        endpoint (404 Not Found), logs cleanly at INFO level and skips without retries.
        """
        if not getattr(self.config, "sync_web_app_enabled", True):
            logger.debug("JumpServer web application sync disabled (JMS_SYNC_WEB_APP_ENABLED=false)")
            return {}

        url = public_url or getattr(self.config, "public_url", "http://172.30.20.62:8000")
        try:
            existing = self.get_web_application_by_name(name)
            if existing and (existing.get("id") or existing.get("name")):
                logger.info("JumpServer Web Application '%s' already registered (idempotent): id=%s", name, existing.get("id"))
                return existing

            logger.info("Registering JumpServer Web Application '%s' with URL %s", name, url)
            created = self.create_web_application(name=name, url=url)
            if isinstance(created, dict) and (created.get("id") or created.get("name")):
                logger.info("JumpServer Web Application '%s' created successfully: id=%s", name, created.get("id"))
                return created
            elif isinstance(created, dict):
                logger.info("JumpServer Web Application '%s' registration completed: %s", name, created)
                return created
            else:
                logger.warning("JumpServer Web Application '%s' registration returned unexpected response type %s", name, type(created))
                return {}
        except JumpServerError as jse:
            if "404" in str(jse) or "Not Found" in str(jse):
                logger.info("JumpServer applications endpoint not supported on this edition, skipping automated web app registration")
                return {}
            logger.warning("Failed to ensure Web Application '%s' in JumpServer: %s", name, jse)
            return {}
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                logger.info("JumpServer applications endpoint not supported on this edition, skipping automated web app registration")
                return {}
            logger.warning("Failed to ensure Web Application '%s' in JumpServer: %s", name, e)
            return {}
