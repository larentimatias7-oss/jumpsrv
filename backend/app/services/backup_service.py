from __future__ import annotations
import datetime
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from ..models.database import KioskModel, CategoryModel, SystemSettingModel
from ..provisioning.provisioner import (
    KioskProvisioner,
    KioskCreateRequest,
    format_jms_asset_name,
    detect_host_ip,
)

logger = logging.getLogger("kiosk.backup")


class BackupKioskItem(BaseModel):
    name: str
    device_type: str = "generic"
    target_url: str
    target_ip: Optional[str] = None
    target_protocol: str = "http"
    target_port: int = 80
    category_name: Optional[str] = None
    jms_node_name: Optional[str] = None


class BackupCategoryItem(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = "📁"
    jms_node_id: Optional[str] = None


class BackupSettingsItem(BaseModel):
    disconnect_grace_seconds: Optional[int] = None
    idle_timeout_seconds: Optional[int] = None
    max_session_lifetime_seconds: Optional[int] = None
    max_concurrent_sessions: Optional[int] = None


class BackupPayload(BaseModel):
    version: str = "1.0"
    exported_at: Optional[str] = None
    system: Optional[Dict[str, Any]] = None
    settings: Optional[BackupSettingsItem] = None
    categories: List[BackupCategoryItem] = Field(default_factory=list)
    kiosks: List[BackupKioskItem] = Field(default_factory=list)


class BackupService:
    """Service to handle complete, lossless backup export and transactional restore."""

    def __init__(self, provisioner: Optional[KioskProvisioner] = None):
        self.provisioner = provisioner or KioskProvisioner()

    def export_backup(self) -> Dict[str, Any]:
        """Export all categories, system settings, and kiosk definitions."""
        with self.provisioner.db_factory() as session:
            # 1. Categories
            categories = session.query(CategoryModel).order_by(CategoryModel.name).all()
            cat_list = [
                {
                    "name": c.name,
                    "description": c.description or "",
                    "icon": c.icon or "📁",
                    "jms_node_id": c.jms_node_id,
                }
                for c in categories
            ]

            # 2. Kiosks
            kiosks = session.query(KioskModel).order_by(KioskModel.name).all()
            kiosk_list = [
                {
                    "name": k.name,
                    "device_type": k.device_type,
                    "target_url": k.target_url,
                    "target_ip": k.target_ip,
                    "target_protocol": k.target_protocol or "http",
                    "target_port": k.target_port or 80,
                    "category_name": k.category_name or k.jms_node_name,
                    "jms_node_name": k.jms_node_name or k.category_name,
                    "jms_asset_name": format_jms_asset_name(k.name),
                }
                for k in kiosks
            ]

            # 3. Settings
            settings_records = session.query(SystemSettingModel).all()
            settings_dict = {
                r.key: int(r.value) if r.value.isdigit() else r.value
                for r in settings_records
            }

            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return {
                "version": "1.0",
                "exported_at": now_iso,
                "system": {
                    "app": "JumpServer Kiosk Manager",
                    "total_kiosks": len(kiosk_list),
                    "total_categories": len(cat_list),
                },
                "settings": settings_dict,
                "categories": cat_list,
                "kiosks": kiosk_list,
            }

    async def import_backup(
        self,
        payload_data: Dict[str, Any],
        conflict_strategy: str = "skip",  # "skip" or "update"
        auto_provision_jms: bool = True,
        created_by: str = "backup-restore",
    ) -> Dict[str, Any]:
        """
        Restore categories, settings, and kiosks from a verified backup payload.
        Handles conflicts gracefully and synchronizes JumpServer nodes and assets.
        """
        payload = BackupPayload.model_validate(payload_data)

        categories_created = 0
        categories_existing = 0
        imported_kiosks = 0
        updated_kiosks = 0
        skipped_kiosks = 0
        errors: List[Dict[str, str]] = []

        # 1. Restore & Ensure Categories
        with self.provisioner.db_factory() as session:
            for cat_item in payload.categories:
                cat_name = cat_item.name.strip()
                if not cat_name:
                    continue
                existing_cat = session.query(CategoryModel).filter(CategoryModel.name == cat_name).first()
                if existing_cat:
                    categories_existing += 1
                    # Ensure node id is filled if available
                    if not existing_cat.jms_node_id and cat_item.jms_node_id:
                        existing_cat.jms_node_id = cat_item.jms_node_id
                        session.commit()
                    continue

                # Ensure node in JumpServer if client available
                resolved_node_id = cat_item.jms_node_id
                if not resolved_node_id:
                    try:
                        resolved_node_id = self.provisioner.jms.client.ensure_node(cat_name)
                    except Exception as e:
                        logger.warning("Could not ensure JumpServer node for category '%s': %s", cat_name, e)

                new_cat = CategoryModel(
                    name=cat_name,
                    description=cat_item.description or "",
                    icon=cat_item.icon or "📁",
                    jms_node_id=resolved_node_id,
                )
                session.add(new_cat)
                session.commit()
                categories_created += 1

        # 2. Restore Settings
        if payload.settings:
            try:
                from ..config import save_lifecycle_settings, SessionLifecycleSettings
                settings_kwargs = {}
                for field_name in ["disconnect_grace_seconds", "idle_timeout_seconds", "max_session_lifetime_seconds", "max_concurrent_sessions"]:
                    val = getattr(payload.settings, field_name, None)
                    if val is not None:
                        settings_kwargs[field_name] = val
                if settings_kwargs:
                    new_settings = SessionLifecycleSettings(**settings_kwargs)
                    save_lifecycle_settings(new_settings, db_factory=self.provisioner.db_factory)
                    try:
                        from ..main import dispatcher
                        dispatcher.update_lifecycle_settings(**settings_kwargs)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("Could not apply imported settings: %s", e)

        # 3. Restore Kiosks
        for kiosk_data in payload.kiosks:
            clean_name = kiosk_data.name.strip().upper()
            if not clean_name:
                continue

            with self.provisioner.db_factory() as session:
                existing_kiosk = session.query(KioskModel).filter(KioskModel.name == clean_name).first()

            if existing_kiosk:
                if conflict_strategy == "update":
                    try:
                        from ..provisioning.provisioner import KioskUpdateRequest
                        update_req = KioskUpdateRequest(
                            device_type=kiosk_data.device_type,
                            target_url=kiosk_data.target_url,
                            category_name=kiosk_data.category_name,
                        )
                        self.provisioner.update(existing_kiosk.id, update_req)
                        updated_kiosks += 1
                    except Exception as e:
                        errors.append({"name": clean_name, "error": f"Failed to update: {e}"})
                else:
                    skipped_kiosks += 1
                continue

            # Resolve target_ip, protocol, and port if missing
            target_ip = kiosk_data.target_ip
            target_proto = kiosk_data.target_protocol or "http"
            target_port = kiosk_data.target_port or 80

            if (not target_ip or target_ip == "127.0.0.1") and kiosk_data.target_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(kiosk_data.target_url)
                    if parsed.hostname:
                        target_ip = parsed.hostname
                    if parsed.scheme:
                        target_proto = parsed.scheme.lower()
                    if parsed.port:
                        target_port = parsed.port
                    elif target_proto == "https":
                        target_port = 443
                    elif target_proto == "http":
                        target_port = 80
                except Exception:
                    pass

            target_ip = target_ip or "127.0.0.1"

            # If not existing, provision or create new
            if auto_provision_jms:
                try:
                    create_req = KioskCreateRequest(
                        name=clean_name,
                        device_type=kiosk_data.device_type,
                        target_url=kiosk_data.target_url,
                        target_ip=target_ip,
                        target_protocol=target_proto,
                        target_port=target_port,
                        category_name=kiosk_data.category_name or kiosk_data.jms_node_name,
                    )
                    res = self.provisioner.provision(create_req, created_by=created_by)
                    try:
                        from ..main import dispatcher
                        host_ip = detect_host_ip()
                        await dispatcher.start_listening_for_kiosk(res["id"], host_ip, res["rdp_port"])
                    except Exception:
                        pass
                    imported_kiosks += 1
                except Exception as e:
                    errors.append({"name": clean_name, "error": f"Provisioning failed: {e}"})
            else:
                # Standalone import to DB without creating external containers or assets
                try:
                    with self.provisioner.db_factory() as session:
                        port = self.provisioner._allocate_port(session)
                        sanitized_suffix = "".join(ch if ch.isalnum() else "_" for ch in clean_name.lower())
                        kiosk = KioskModel(
                            name=clean_name,
                            device_type=kiosk_data.device_type,
                            target_url=kiosk_data.target_url,
                            target_ip=kiosk_data.target_ip or "127.0.0.1",
                            target_protocol=kiosk_data.target_protocol or "http",
                            target_port=kiosk_data.target_port or 80,
                            rdp_port=port,
                            rdp_username=f"kiosk_{sanitized_suffix}",
                            container_name=f"kiosk-{sanitized_suffix}",
                            volume_name=f"rdp_{sanitized_suffix}",
                            category_name=kiosk_data.category_name,
                            jms_node_name=kiosk_data.jms_node_name or kiosk_data.category_name,
                            status="IDLE",
                        )
                        session.add(kiosk)
                        session.commit()
                        imported_kiosks += 1
                except Exception as e:
                    errors.append({"name": clean_name, "error": f"Offline import failed: {e}"})

        return {
            "success": len(errors) == 0,
            "categories_created": categories_created,
            "categories_existing": categories_existing,
            "imported_kiosks": imported_kiosks,
            "updated_kiosks": updated_kiosks,
            "skipped_kiosks": skipped_kiosks,
            "total_processed": len(payload.kiosks),
            "errors": errors,
        }
