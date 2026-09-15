from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class JumpServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JMS_",
        env_file=Path("/opt/kiosk-portal/config/jms.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(
        default_factory=lambda: os.getenv("JMS_BASE_URL", os.getenv("JUMPSERVER_BASE_URL", "http://127.0.0.1:80")),
        description="Base URL of JumpServer",
    )
    key_id: str = Field(
        default_factory=lambda: os.getenv("JMS_KEY_ID", os.getenv("JUMPSERVER_KEY_ID", "")),
        description="Access Key ID",
    )
    secret_file: Path | None = Field(default=None, description="Path to 600 file with secret")
    secret_value: str | None = Field(
        default_factory=lambda: os.getenv(
            "JMS_SECRET_KEY",
            os.getenv(
                "JMS_SECRET",
                os.getenv(
                    "JMS_SECRET_VALUE",
                    os.getenv("JUMPSERVER_KEY_SECRET", os.getenv("JUMPSERVER_SECRET", "")),
                ),
            ),
        ),
        description="Direct secret in memory or test env",
    )
    org_id: str = Field(
        default_factory=lambda: os.getenv("JUMPSERVER_ORG_ID", os.getenv("JMS_ORG_ID", "00000000-0000-0000-0000-000000000002")),
        description="Default org UUID in JumpServer 4.x",
    )
    verify_ssl: bool = Field(
        default_factory=lambda: os.getenv("JMS_VERIFY_SSL", os.getenv("JUMPSERVER_VERIFY_SSL", "true")).strip().lower() in ("1", "true", "yes", "on", "t"),
        description="Verify SSL certificate",
    )
    ca_bundle: Path | None = Field(default=None, description="Custom CA bundle")
    timeout: float = Field(default=30.0, description="HTTP timeout seconds")
    max_retries: int = Field(default=3, description="Max HTTP retries")
    default_node_name: str = Field(
        default_factory=lambda: os.getenv("JMS_DEFAULT_NODE_NAME", os.getenv("JUMPSERVER_DEFAULT_NODE_NAME", "SWITCHES ROSARIO")),
        description="Default JumpServer node name for grouping kiosk assets",
    )
    default_node_id: str | None = Field(
        default_factory=lambda: os.getenv("JMS_DEFAULT_NODE_ID", os.getenv("JUMPSERVER_DEFAULT_NODE_ID", None)),
        description="Optional static JumpServer node UUID",
    )
    public_url: str = Field(
        default_factory=lambda: os.getenv("KIOSK_MANAGER_PUBLIC_URL", "http://172.30.20.62:8000"),
        description="Public URL for kiosk manager web application in JumpServer",
    )
    sync_web_app_enabled: bool = Field(
        default_factory=lambda: os.getenv("JMS_SYNC_WEB_APP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on", "t"),
        description="Whether to register the kiosk manager web app in JumpServer at startup",
    )
    login_url: str = Field(
        default_factory=lambda: os.getenv("JMS_LOGIN_URL", "https://172.30.20.62/ui/#/login"),
        description="JumpServer login portal URL for redirecting unauthenticated users",
    )
    logout_url: str = Field(
        default_factory=lambda: os.getenv("JMS_LOGOUT_URL", "https://172.30.20.62/ui/#/logout"),
        description="JumpServer logout URL",
    )

    @field_validator("verify_ssl", mode="before")
    @classmethod
    def _validate_verify_ssl(cls, v: Any) -> bool:
        if v is None:
            raw = os.getenv("JMS_VERIFY_SSL", os.getenv("JUMPSERVER_VERIFY_SSL", "true"))
            v = raw
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on", "t")
        return bool(v)

    @field_validator("org_id", mode="before")
    @classmethod
    def _validate_org_id(cls, v: Any) -> str:
        env_val = os.getenv("JUMPSERVER_ORG_ID")
        if env_val:
            return env_val.strip()
        if v:
            return str(v).strip()
        return os.getenv("JMS_ORG_ID", "00000000-0000-0000-0000-000000000002")

    @field_validator("secret_file")
    @classmethod
    def _check_secret_file(cls, v: Path | None) -> Path | None:
        if v is None:
            return v
        if not v.exists():
            return v
        mode = v.stat().st_mode & 0o777
        if mode & 0o077:
            # File should not be accessible by group or others
            pass
        return v

    def get_key_id(self) -> str:
        """Return configured AccessKey ID, falling back to cache or Docker autodiscovery."""
        if self.key_id and self.key_id.strip():
            return self.key_id.strip()
        from .autodiscovery import get_or_discover_credentials
        k_id, sec = get_or_discover_credentials(self.key_id, self.secret_value)
        if k_id:
            self.key_id = k_id
            if sec and not self.secret_value:
                self.secret_value = sec
            return k_id
        return ""

    def load_secret(self) -> str:
        """Return secret from value, file, cache, or Docker autodiscovery."""
        if self.secret_value and self.secret_value.strip():
            return self.secret_value.strip()
        if self.secret_file and self.secret_file.exists():
            content = self.secret_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        from .autodiscovery import get_or_discover_credentials
        k_id, sec = get_or_discover_credentials(self.key_id, self.secret_value)
        if sec:
            self.secret_value = sec
            if k_id and not self.key_id:
                self.key_id = k_id
            return sec
        return ""


JumpServerConfig = JumpServerSettings


@lru_cache
def get_jms_settings() -> JumpServerSettings:
    return JumpServerSettings()

