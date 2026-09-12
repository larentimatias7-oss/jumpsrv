from __future__ import annotations
from typing import Any
from .client import JumpServerClient


class JumpServerOperations:
    """High level operations for JumpServer REST API v1."""

    def __init__(self, client: JumpServerClient):
        self.client = client

    def list_nodes(self) -> list[dict[str, Any]]:
        result = self.client.get("/api/v1/assets/nodes/")
        if isinstance(result, list):
            return result
        return result.get("results", [])

    def list_platforms(self) -> list[dict[str, Any]]:
        result = self.client.get("/api/v1/assets/platforms/")
        if isinstance(result, list):
            return result
        return result.get("results", [])

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
        platform_id: int = 5,
        comment: str = "Managed by JumpServer Kiosk Manager",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "address": ip,
            "platform": platform_id,
            "protocols": [{
                "name": "rdp",
                "port": port,
                "setting": {"security": "any", "ignore_cert": True, "console": False}
            }],
            "is_active": True,
            "comment": comment,
        }
        if node_id:
            payload["nodes"] = [node_id]

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
