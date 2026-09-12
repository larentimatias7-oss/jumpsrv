from __future__ import annotations
import os
import secrets
import string
import socket
import time
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from ..models.database import KioskModel, init_db
from ..docker_runtime.client import DockerRuntime
from ..jumpserver.client import JumpServerClient
from ..jumpserver.operations import JumpServerOperations
from ..jumpserver.config import get_jms_settings

logger = logging.getLogger("kiosk.provisioner")


class KioskCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    device_type: str = Field(default="generic")
    target_ip: str
    target_protocol: str = Field(default="http")
    target_port: int = Field(default=80)
    target_url: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    user_group_ids: Optional[List[str]] = None


class KioskProvisioner:
    """Orchestrates safe, non-destructive provisioning between Docker Rootless and JumpServer."""

    def __init__(
        self,
        db_session_factory=None,
        docker_runtime: Optional[DockerRuntime] = None,
        jms_ops: Optional[JumpServerOperations] = None,
        host_ip: str = "192.168.1.220",
        port_range: tuple[int, int] = (33891, 33920),
        image_tag: str = "pam-web-kiosk:v1",
    ):
        self.db_factory = db_session_factory or init_db()
        self.docker = docker_runtime or DockerRuntime()
        self.jms = jms_ops or JumpServerOperations(JumpServerClient(get_jms_settings()))
        self.host_ip = os.environ.get("KIOSK_HOST_IP", host_ip)
        self.port_min = int(os.environ.get("KIOSK_PORT_RANGE_START", port_range[0]))
        self.port_max = int(os.environ.get("KIOSK_PORT_RANGE_END", port_range[1]))
        self.image_tag = os.environ.get("KIOSK_IMAGE_TAG", image_tag)

    def _generate_password(self, length: int = 32) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _allocate_port(self, session) -> int:
        used_ports = {k.rdp_port for k in session.query(KioskModel.rdp_port).all()}
        for port in range(self.port_min, self.port_max + 1):
            if port not in used_ports:
                # Double check socket on host
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    res = s.connect_ex((self.host_ip, port))
                    if res != 0:
                        return port
        raise RuntimeError(f"No available RDP ports in range {self.port_min}-{self.port_max}")

    def list_all(self) -> List[Dict[str, Any]]:
        with self.db_factory() as session:
            kiosks = session.query(KioskModel).order_by(KioskModel.name).all()
            out = []
            for k in kiosks:
                c_status = self.docker.get_container_status(k.container_name)
                out.append({
                    "id": k.id,
                    "name": k.name,
                    "device_type": k.device_type,
                    "target_url": k.target_url,
                    "target_ip": k.target_ip,
                    "rdp_port": k.rdp_port,
                    "rdp_username": k.rdp_username,
                    "status": k.status,
                    "container_status": c_status["status"],
                    "container_health": c_status["health"],
                    "last_error": k.last_error,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                })
            return out

    def provision(self, req: KioskCreateRequest) -> Dict[str, Any]:
        clean_name = req.name.strip().upper()
        if not req.target_url:
            target_url = f"{req.target_protocol.lower()}://{req.target_ip}:{req.target_port}"
        else:
            target_url = req.target_url

        with self.db_factory() as session:
            # 1. Duplicate check
            existing = session.query(KioskModel).filter(KioskModel.name == clean_name).first()
            if existing:
                raise ValueError(f"Kiosk with name {clean_name} already exists.")

            # 2. Allocate port & RDP credentials
            port = self._allocate_port(session)
            sanitized_suffix = "".join(ch if ch.isalnum() else "_" for ch in clean_name.lower())
            rdp_user = f"kiosk_{sanitized_suffix}"
            rdp_password = self._generate_password(32)
            container_name = f"kiosk-{sanitized_suffix}"
            volume_name = f"rdp_{sanitized_suffix}"

            # 3. Create record in PENDING
            kiosk = KioskModel(
                name=clean_name,
                device_type=req.device_type,
                target_url=target_url,
                target_ip=req.target_ip,
                target_protocol=req.target_protocol,
                target_port=req.target_port,
                rdp_port=port,
                rdp_username=rdp_user,
                container_name=container_name,
                volume_name=volume_name,
                status="PENDING",
            )
            session.add(kiosk)
            session.commit()
            session.refresh(kiosk)
            kiosk_id = kiosk.id

        created_resources: List[tuple[str, Any]] = []

        try:
            # 4. Create volume in Rootless Docker
            vol = self.docker.create_volume(volume_name, kiosk_id)
            created_resources.append(("volume", volume_name))

            # 5. Register Kiosk container (stopped / on-demand)
            # Volume vol_rdp_<asset_id> is already created above and mounted to /home/kiosk/.config/chromium
            # Container remains stopped until Dispatcher receives first connection
            pass

            # 6. JumpServer: Register RDP Asset
            jms_asset = self.jms.create_rdp_asset(
                name=clean_name,
                ip=self.host_ip,
                port=port,
                node_id=req.node_id,
                platform_id=5,
            )
            jms_asset_id = jms_asset.get("id")
            created_resources.append(("jms_asset", jms_asset_id))

            # 7. JumpServer: Register RDP Account
            jms_account = self.jms.create_account(
                asset_id=jms_asset_id,
                username=rdp_user,
                secret=rdp_password,
            )
            jms_account_id = jms_account.get("id")
            created_resources.append(("jms_account", jms_account_id))

            # 8. JumpServer: Assign permissions
            perm_name = f"AUT-KIOSK-{clean_name}"
            jms_perm = self.jms.assign_permission(
                name=perm_name,
                asset_id=jms_asset_id,
                account_username=rdp_user,
                user_group_ids=req.user_group_ids,
            )
            jms_perm_id = jms_perm.get("id")
            created_resources.append(("jms_permission", jms_perm_id))

            # 9. Update DB to RUNNING
            with self.db_factory() as session:
                k = session.query(KioskModel).get(kiosk_id)
                k.jms_asset_id = jms_asset_id
                k.jms_account_id = jms_account_id
                k.jms_permission_id = jms_perm_id
                k.status = "RUNNING"
                k.last_error = None
                session.commit()

            return {
                "id": kiosk_id,
                "name": clean_name,
                "status": "RUNNING",
                "rdp_port": port,
                "jms_asset_id": jms_asset_id,
            }

        except Exception as e:
            logger.error(f"Provisioning failed for {clean_name}: {e}. Executing safe rollback...")
            self._rollback(created_resources)
            with self.db_factory() as session:
                k = session.query(KioskModel).get(kiosk_id)
                if k:
                    k.status = "FAILED"
                    k.last_error = str(e)
                    session.commit()
            raise

    def _rollback(self, resources: List[tuple[str, Any]]) -> None:
        """Executes safe, non-destructive rollback in reverse order."""
        for res_type, res_val in reversed(resources):
            try:
                if res_type == "jms_permission" and res_val:
                    self.jms.delete_permission(res_val)
                elif res_type == "jms_account" and res_val:
                    self.jms.delete_account(res_val)
                elif res_type == "jms_asset" and res_val:
                    self.jms.delete_asset(res_val)
                elif res_type == "container" and res_val:
                    self.docker.stop_and_remove_container(res_val)
                elif res_type == "volume" and res_val:
                    self.docker.remove_volume(res_val)
            except Exception as rb_err:
                logger.warning(f"Rollback error for {res_type} ({res_val}): {rb_err}")

    def deprovision(self, kiosk_id: str) -> bool:
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                return False

            if k.jms_permission_id:
                try:
                    self.jms.delete_permission(k.jms_permission_id)
                except Exception:
                    pass
            if k.jms_account_id:
                try:
                    self.jms.delete_account(k.jms_account_id)
                except Exception:
                    pass
            if k.jms_asset_id:
                try:
                    self.jms.delete_asset(k.jms_asset_id)
                except Exception:
                    pass

            self.docker.stop_and_remove_container(k.container_name)
            self.docker.remove_volume(k.volume_name)

            session.delete(k)
            session.commit()
            return True

    def restart(self, kiosk_id: str) -> bool:
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                return False
            return self.docker.restart_container(k.container_name)
