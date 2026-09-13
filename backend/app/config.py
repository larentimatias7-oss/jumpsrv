from __future__ import annotations
import logging
import os
from typing import Optional
from pydantic import BaseModel, Field

"""JumpServer and application configuration re-exports for transparent compatibility."""
from app.jumpserver.config import (
    JumpServerSettings,
    JumpServerConfig,
    get_jms_settings,
)

logger = logging.getLogger("kiosk.config")

# Environment defaults for session lifecycle and RAM conservation
DEFAULT_DISCONNECT_GRACE_SECONDS = int(os.getenv("KIOSK_DISCONNECT_GRACE_SECONDS", "30"))
DEFAULT_IDLE_TIMEOUT_SECONDS = int(os.getenv("KIOSK_IDLE_TIMEOUT_SECONDS", "900"))
DEFAULT_MAX_SESSION_LIFETIME_SECONDS = int(os.getenv("KIOSK_MAX_SESSION_LIFETIME_SECONDS", "14400"))
DEFAULT_MAX_CONCURRENT_SESSIONS = int(os.getenv("KIOSK_MAX_CONCURRENT_SESSIONS", "4"))


class SessionLifecycleSettings(BaseModel):
    disconnect_grace_seconds: int = Field(
        default=DEFAULT_DISCONNECT_GRACE_SECONDS,
        ge=5,
        le=86400,
        description="Grace period in seconds after last disconnect before stopping container",
    )
    idle_timeout_seconds: int = Field(
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
        ge=30,
        le=86400,
        description="Session idle traffic timeout in seconds before force stopping container",
    )
    max_session_lifetime_seconds: int = Field(
        default=DEFAULT_MAX_SESSION_LIFETIME_SECONDS,
        ge=60,
        le=604800,
        description="Absolute maximum lifetime of a continuous session in seconds",
    )
    max_concurrent_sessions: int = Field(
        default=DEFAULT_MAX_CONCURRENT_SESSIONS,
        ge=1,
        le=100,
        description="Maximum concurrent active kiosk sessions allowed on host",
    )


def get_lifecycle_settings(db_factory=None) -> SessionLifecycleSettings:
    """Retrieve active session lifecycle settings from database with fallback to env vars."""
    if db_factory is None:
        from app.models.database import init_db
        db_factory = init_db()

    grace = int(os.getenv("KIOSK_DISCONNECT_GRACE_SECONDS", str(DEFAULT_DISCONNECT_GRACE_SECONDS)))
    idle = int(os.getenv("KIOSK_IDLE_TIMEOUT_SECONDS", str(DEFAULT_IDLE_TIMEOUT_SECONDS)))
    max_life = int(os.getenv("KIOSK_MAX_SESSION_LIFETIME_SECONDS", str(DEFAULT_MAX_SESSION_LIFETIME_SECONDS)))
    max_concurrent = int(os.getenv("KIOSK_MAX_CONCURRENT_SESSIONS", str(DEFAULT_MAX_CONCURRENT_SESSIONS)))

    try:
        from app.models.database import SystemSettingModel
        with db_factory() as session:
            records = session.query(SystemSettingModel).filter(
                SystemSettingModel.key.in_([
                    "disconnect_grace_seconds",
                    "idle_timeout_seconds",
                    "max_session_lifetime_seconds",
                    "max_concurrent_sessions",
                ])
            ).all()
            for r in records:
                if r.key == "disconnect_grace_seconds":
                    grace = int(r.value)
                elif r.key == "idle_timeout_seconds":
                    idle = int(r.value)
                elif r.key == "max_session_lifetime_seconds":
                    max_life = int(r.value)
                elif r.key == "max_concurrent_sessions":
                    max_concurrent = int(r.value)
    except Exception as e:
        logger.warning(f"Could not load lifecycle settings from database, using defaults: {e}")

    return SessionLifecycleSettings(
        disconnect_grace_seconds=grace,
        idle_timeout_seconds=idle,
        max_session_lifetime_seconds=max_life,
        max_concurrent_sessions=max_concurrent,
    )


def save_lifecycle_settings(settings: SessionLifecycleSettings, db_factory=None) -> SessionLifecycleSettings:
    """Persist session lifecycle settings to database."""
    if db_factory is None:
        from app.models.database import init_db
        db_factory = init_db()

    try:
        from app.models.database import SystemSettingModel
        with db_factory() as session:
            data = {
                "disconnect_grace_seconds": str(settings.disconnect_grace_seconds),
                "idle_timeout_seconds": str(settings.idle_timeout_seconds),
                "max_session_lifetime_seconds": str(settings.max_session_lifetime_seconds),
                "max_concurrent_sessions": str(settings.max_concurrent_sessions),
            }
            for k, v in data.items():
                rec = session.query(SystemSettingModel).filter(SystemSettingModel.key == k).first()
                if rec:
                    rec.value = v
                else:
                    session.add(SystemSettingModel(key=k, value=v))
            session.commit()
            logger.info(f"Saved updated lifecycle settings to database: {data}")
    except Exception as e:
        logger.error(f"Failed to save lifecycle settings to database: {e}")
        raise

    return settings


__all__ = [
    "JumpServerSettings",
    "JumpServerConfig",
    "get_jms_settings",
    "SessionLifecycleSettings",
    "get_lifecycle_settings",
    "save_lifecycle_settings",
    "DEFAULT_DISCONNECT_GRACE_SECONDS",
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_SESSION_LIFETIME_SECONDS",
    "DEFAULT_MAX_CONCURRENT_SESSIONS",
]
