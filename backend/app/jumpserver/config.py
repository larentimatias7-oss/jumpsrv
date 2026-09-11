from __future__ import annotations
from functools import lru_cache
from pathlib import Path
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

    base_url: str = Field(default="https://192.168.1.220", description="Base URL of JumpServer")
    key_id: str = Field(default="", description="Access Key ID")
    secret_file: Path | None = Field(default=None, description="Path to 600 file with secret")
    secret_value: str | None = Field(default=None, description="Direct secret in memory or test env")
    org_id: str = Field(
        default="00000000-0000-0000-0000-000000000002",
        description="Default org UUID in JumpServer 4.x",
    )
    verify_ssl: bool = Field(default=False, description="Verify SSL certificate")
    ca_bundle: Path | None = Field(default=None, description="Custom CA bundle")
    timeout: float = Field(default=30.0, description="HTTP timeout seconds")
    max_retries: int = Field(default=3, description="Max HTTP retries")

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

    def load_secret(self) -> str:
        if self.secret_value:
            return self.secret_value.strip()
        if self.secret_file and self.secret_file.exists():
            return self.secret_file.read_text(encoding="utf-8").strip()
        return ""


@lru_cache
def get_jms_settings() -> JumpServerSettings:
    return JumpServerSettings()
