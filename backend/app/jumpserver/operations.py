from __future__ import annotations
import logging
import uuid
from typing import Any
from .client import JumpServerClient

logger = logging.getLogger("kiosk.jumpserver.ops")


def is_valid_uuid(val: Any) -> bool:
    if not val or not isinstance(val, (str, uuid.UUID)):
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class JumpServerOperations:
    """High level operations for JumpServer REST API v1."""

    def __init__(self, client: JumpServerClient):
        self.client = client
        self._cached_default_node_id: str | None = None
        self._cached_windows_platform_id: int | None = None

    def list_nodes(self) -> list[dict[str, Any]]:
        result = self.client.get("/api/v1/assets/nodes/")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    def list_platforms(self) -> list[dict[str, Any]]:
        result = self.client.get("/api/v1/assets/platforms/")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    def get_default_node_id(self) -> str | None:
        """Dynamically resolve root/default node UUID and cache it."""
        if self._cached_default_node_id:
            return self._cached_default_node_id

        try:
            nodes = self.list_nodes()
            # 1. Search for node with value == "DEFAULT" or name == "DEFAULT"
            for node in nodes:
                if isinstance(node, dict):
                    if node.get("value") == "DEFAULT" or node.get("name") == "DEFAULT":
                        n_id = node.get("id")
                        if is_valid_uuid(n_id):
                            self._cached_default_node_id = str(n_id)
                            return self._cached_default_node_id
            # 2. Or take the first returned node (results[0]["id"])
            if nodes and isinstance(nodes[0], dict):
                first_id = nodes[0].get("id")
                if is_valid_uuid(first_id):
                    self._cached_default_node_id = str(first_id)
                    return self._cached_default_node_id
        except Exception as e:
            logger.warning(f"Failed to dynamically resolve default node ID: {e}")

        return None

    def resolve_node_id(self, node_id: str | None = None) -> str | None:
        """Validate and resolve node UUID. If empty/default/invalid, dynamically look up default node."""
        if node_id and node_id not in ("", "/DEFAULT", "DEFAULT") and is_valid_uuid(node_id):
            return str(node_id)
        return self.get_default_node_id()

    def resolve_platform_id(self, platform: int | str | None = 5) -> int:
        """Resolve numeric platform ID for Windows (defaults to 5)."""
        if isinstance(platform, int):
            return platform
        if isinstance(platform, str):
            if platform.isdigit():
                return int(platform)
            if self._cached_windows_platform_id:
                return self._cached_windows_platform_id
            try:
                platforms = self.list_platforms()
                for p in platforms:
                    if isinstance(p, dict) and p.get("name", "").strip().lower() == platform.strip().lower():
                        p_id = p.get("id")
                        if p_id is not None:
                            resolved_id = int(p_id)
                            if platform.strip().lower() == "windows":
                                self._cached_windows_platform_id = resolved_id
                            return resolved_id
            except Exception as e:
                logger.warning(f"Failed to dynamically resolve platform ID for '{platform}': {e}")
        return 5

    def get_asset_by_name(self, name: str) -> dict[str, Any] | None:
        result = self.client.get("/api/v1/assets/assets/", name=name)
        results = result.get("results", []) if isinstance(result, dict) else result
        for item in results:
            if item.get("name") == name:
                return item
        return None

    def create_rdp_asset(
        self,
        name: str,
        ip: str,
        port: int,
        node_id: str | None = None,
        platform: int | str = 5,
        platform_id: int | None = None,
        comment: str = "Managed by JumpServer Kiosk Manager",
        **kwargs: Any,
    ) -> dict[str, Any]:
        actual_platform = self.resolve_platform_id(platform_id if platform_id is not None else platform)
        payload: dict[str, Any] = {
            "name": name,
            "address": ip,
            "platform": actual_platform,
            "protocols": [{"name": "rdp", "port": port}],
            "is_active": True,
        }
        if comment:
            payload["comment"] = comment

        resolved_node = self.resolve_node_id(node_id)
        if resolved_node and is_valid_uuid(resolved_node):
            payload["nodes"] = [str(resolved_node)]

        return self.client.post("/api/v1/assets/hosts/", payload)

    def create_account(
        self,
        asset_id: str,
        username: str,
        secret: str,
        has_secret: bool = True,
        privileged: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "name": username,
            "username": username,
            "secret": secret,
            "has_secret": has_secret,
            "asset": asset_id,
            "privileged": privileged,
            "is_active": True,
        }
        return self.client.post("/api/v1/accounts/accounts/", payload)

    def assign_permission(
        self,
        name: str,
        asset_id: str,
        account_username: str,
        user_group_ids: list[str] | None = None,
        user_ids: list[str] | None = None,
        actions: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "assets": [asset_id],
            "accounts": ["@ALL", account_username],
            "actions": actions or ["connect", "copy", "paste"],
            "is_active": True,
        }
        if user_group_ids:
            payload["user_groups"] = user_group_ids
        if user_ids:
            payload["users"] = user_ids

        return self.client.post("/api/v1/perms/asset-permissions/", payload)

    def delete_asset(self, asset_id: str) -> Any:
        return self.client.delete(f"/api/v1/assets/assets/{asset_id}/")

    def delete_account(self, account_id: str) -> Any:
        return self.client.delete(f"/api/v1/accounts/accounts/{account_id}/")

    def delete_permission(self, perm_id: str) -> Any:
        return self.client.delete(f"/api/v1/perms/asset-permissions/{perm_id}/")
