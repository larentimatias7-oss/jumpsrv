from __future__ import annotations
import os
import secrets
import string
import socket
import time
import asyncio
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from ..models.database import KioskModel, CategoryModel, init_db
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
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    user_group_ids: Optional[List[str]] = None
    verify_rdp: Optional[bool] = Field(default=False, description="Check RDP socket readiness before JumpServer registration")


class KioskUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    device_type: Optional[str] = None
    target_url: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None


DEFAULT_KIOSK_IMAGE = os.getenv("KIOSK_DOCKER_IMAGE", "ghcr.io/larentimatias7-oss/jumpsrv/pam-web-kiosk:latest")


def detect_host_ip(fallback: str = "127.0.0.1") -> str:
    env_ip = os.environ.get("KIOSK_HOST_IP", "").strip()
    if env_ip and env_ip not in ("127.0.0.1", "localhost", "0.0.0.0"):
        return env_ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            detected = s.getsockname()[0]
            if detected:
                return detected
    except Exception:
        pass
    return env_ip or fallback


async def wait_for_rdp_ready(
    host: str,
    port: int,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> bool:
    """
    Asynchronously probes a host and port until an XRDP/TCP socket connection succeeds
    or timeout expires.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            time_left = max(0.05, min(interval, deadline - time.time()))
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=time_left,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            await asyncio.sleep(interval)
    return False


def check_socket_ready_sync(
    host: str,
    port: int,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> bool:
    """Synchronous socket check with timeout for non-async provisioning callers."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            time_left = max(0.05, min(interval, deadline - time.time()))
            with socket.create_connection((host, port), timeout=time_left):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(interval)
    return False


class KioskProvisioner:
    """Orchestrates safe, non-destructive provisioning between Docker Engine and JumpServer."""

    def __init__(
        self,
        db_session_factory=None,
        docker_runtime: Optional[DockerRuntime] = None,
        jms_ops: Optional[JumpServerOperations] = None,
        host_ip: str = "127.0.0.1",
        port_range: tuple[int, int] = (33891, 33920),
        image_tag: str = DEFAULT_KIOSK_IMAGE,
    ):
        self.db_factory = db_session_factory or init_db()
        self.docker = docker_runtime or DockerRuntime()
        self.jms = jms_ops or JumpServerOperations(JumpServerClient(get_jms_settings()))
        self.host_ip = detect_host_ip(host_ip)
        self.port_min = int(os.environ.get("KIOSK_PORT_RANGE_START", port_range[0]))
        self.port_max = int(os.environ.get("KIOSK_PORT_RANGE_END", port_range[1]))
        self.image_tag = os.environ.get("KIOSK_DOCKER_IMAGE", os.environ.get("KIOSK_IMAGE_TAG", image_tag))

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
                    "jms_asset_id": k.jms_asset_id,
                    "jms_account_id": k.jms_account_id,
                    "jms_node_name": k.jms_node_name or k.category_name or getattr(self.jms.client.config, "default_node_name", "SWITCHES ROSARIO"),
                    "jms_node_id": k.jms_node_id,
                    "category_id": k.category_id,
                    "category_name": k.category_name or k.jms_node_name or getattr(self.jms.client.config, "default_node_name", "SWITCHES ROSARIO"),
                    "status": k.status,
                    "container_status": c_status["status"],
                    "container_health": c_status["health"],
                    "last_error": k.last_error,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                })
            return out

    def provision(
        self,
        req: KioskCreateRequest,
        verify_rdp: bool = False,
        rdp_probe_timeout: float = 10.0,
        rdp_host: Optional[str] = None,
        rdp_port: Optional[int] = None,
        created_by: str = "kiosk-manager",
    ) -> Dict[str, Any]:
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

            # 2. Resolve Category & JumpServer Node UUID
            cat_name = req.category_name or req.node_name
            cat_id = req.category_id
            if cat_id and not cat_name:
                cat_obj = session.query(CategoryModel).filter(CategoryModel.id == cat_id).first()
                if cat_obj:
                    cat_name = cat_obj.name

            if not cat_name:
                cat_name = getattr(self.jms.client.config, "default_node_name", "SWITCHES ROSARIO")

            resolved_node_id = req.node_id
            if not resolved_node_id:
                try:
                    resolved_node_id = self.jms.client.ensure_node(cat_name)
                except Exception as e:
                    logger.warning("Could not ensure JumpServer node for '%s': %s", cat_name, e)

            # 3. Allocate port & RDP credentials
            port = self._allocate_port(session)
            sanitized_suffix = "".join(ch if ch.isalnum() else "_" for ch in clean_name.lower())
            rdp_user = f"kiosk_{sanitized_suffix}"
            rdp_password = self._generate_password(32)
            container_name = f"kiosk-{sanitized_suffix}"
            volume_name = f"rdp_{sanitized_suffix}"

            # 4. Create record in PENDING
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
                category_id=cat_id,
                category_name=cat_name,
                jms_node_name=cat_name,
                jms_node_id=resolved_node_id,
                status="PENDING",
            )
            session.add(kiosk)
            session.commit()
            session.refresh(kiosk)
            kiosk_id = kiosk.id

        created_resources: List[tuple[str, Any]] = []

        try:
            # 5. Create volume in Docker
            vol = self.docker.create_volume(volume_name, kiosk_id)
            created_resources.append(("volume", volume_name))

            # Readiness Gate (Healthcheck de Contenedor previo al registro en JumpServer)
            should_verify = (
                verify_rdp
                or getattr(req, "verify_rdp", False)
                or os.environ.get("KIOSK_VERIFY_RDP_READINESS", "").strip().lower() in ("true", "1", "yes")
            )
            if should_verify:
                probe_target_host = rdp_host or self.host_ip
                probe_target_port = rdp_port or port
                logger.info(
                    "Readiness gate: probing RDP socket on %s:%s (timeout=%.1fs)...",
                    probe_target_host, probe_target_port, rdp_probe_timeout,
                )
                is_ready = check_socket_ready_sync(probe_target_host, probe_target_port, timeout=rdp_probe_timeout)
                if not is_ready:
                    err_msg = f"RDP socket readiness probe failed on {probe_target_host}:{probe_target_port} after {rdp_probe_timeout}s"
                    logger.error("[Readiness Gate Failed] %s. Aborting JumpServer asset creation.", err_msg)
                    with self.db_factory() as session:
                        k = session.query(KioskModel).get(kiosk_id)
                        if k:
                            k.status = "PROVISION_FAILED"
                            k.last_error = err_msg
                            session.commit()
                    self._rollback(created_resources)
                    raise RuntimeError(err_msg)

            # 6. JumpServer: Register RDP Asset with Node UUID and Audit Metadata
            jms_asset = self.jms.create_rdp_asset(
                name=clean_name,
                ip=self.host_ip,
                port=port,
                node_id=resolved_node_id,
                platform_id=5,
                category_name=cat_name,
                created_by=created_by,
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
                    if k.status != "PROVISION_FAILED":
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

    def stop_session(self, kiosk_id: str) -> bool:
        """Manually stop the active container to free RAM and set status to IDLE."""
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                return False
            try:
                self.docker.stop_container(k.container_name)
            except Exception as e:
                logger.warning("Error stopping container %s: %s", k.container_name, e)
            k.status = "IDLE"
            session.commit()
            logger.info("Manually stopped session for kiosk %s (%s). RAM freed.", k.name, kiosk_id)
            return True

    def update(self, kiosk_id: str, req: KioskUpdateRequest) -> Dict[str, Any]:
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                raise ValueError("Kiosk not found")

            if req.name and req.name.strip():
                new_name = req.name.strip().upper()
                if new_name != k.name:
                    dup = session.query(KioskModel).filter(KioskModel.name == new_name, KioskModel.id != kiosk_id).first()
                    if dup:
                        raise ValueError(f"Kiosk with name {new_name} already exists")
                    k.name = new_name
                    if k.jms_asset_id:
                        try:
                            self.jms.client.put(f"/api/v1/assets/assets/{k.jms_asset_id}/", {"name": new_name})
                        except Exception as e:
                            logger.warning(f"Could not rename JumpServer asset: {e}")

            if req.device_type:
                k.device_type = req.device_type

            if req.target_url and req.target_url.strip():
                k.target_url = req.target_url.strip()
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(k.target_url)
                    if parsed.hostname:
                        k.target_ip = parsed.hostname
                except Exception:
                    pass

            if req.category_name or req.category_id:
                new_cat_name = req.category_name
                new_cat_id = req.category_id
                if new_cat_id and not new_cat_name:
                    c = session.query(CategoryModel).filter(CategoryModel.id == new_cat_id).first()
                    if c:
                        new_cat_name = c.name

                if new_cat_name:
                    new_node_id = None
                    try:
                        new_node_id = self.jms.client.ensure_node(new_cat_name)
                    except Exception as e:
                        logger.warning("Could not ensure node '%s' on update: %s", new_cat_name, e)

                    k.category_id = new_cat_id
                    k.category_name = new_cat_name
                    k.jms_node_name = new_cat_name
                    if new_node_id:
                        k.jms_node_id = new_node_id
                        if k.jms_asset_id:
                            try:
                                self.jms.client.patch(f"/api/v1/assets/assets/{k.jms_asset_id}/", {"nodes": [new_node_id]})
                            except Exception as patch_err:
                                logger.warning("Could not update asset node in JumpServer: %s", patch_err)

            session.commit()

            # Remove existing container so next connection uses updated URL
            self.docker.stop_and_remove_container(k.container_name)

            return {
                "id": k.id,
                "name": k.name,
                "device_type": k.device_type,
                "target_url": k.target_url,
                "target_ip": k.target_ip,
                "rdp_port": k.rdp_port,
                "status": k.status,
            }

    def test_connectivity(self, kiosk_id: str) -> Dict[str, Any]:
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                raise ValueError("Kiosk not found")
            target_url = k.target_url

        import urllib.request
        start = time.time()
        try:
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "Mozilla/5.0 (JumpServer-Kiosk-Probe)"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                latency = round((time.time() - start) * 1000, 1)
                return {
                    "ok": True,
                    "status_code": resp.status,
                    "latency_ms": latency,
                    "url": target_url,
                }
        except Exception as e:
            latency = round((time.time() - start) * 1000, 1)
            return {
                "ok": False,
                "error": str(e),
                "latency_ms": latency,
                "url": target_url,
            }

    def clear_cache(self, kiosk_id: str) -> bool:
        with self.db_factory() as session:
            k = session.query(KioskModel).get(kiosk_id)
            if not k:
                return False
            self.docker.stop_and_remove_container(k.container_name)
            self.docker.remove_volume(k.volume_name)
            self.docker.create_volume(k.volume_name, k.id)
            return True

    def reconcile_with_jumpserver(self) -> Dict[str, Any]:
        """
        Periodically garbage-collects orphaned JumpServer assets.
        1. Fetches all managed assets in JumpServer (tagged kiosk-manager or with managed comment).
        2. Compares against active kiosks in local DB.
        3. Purgues any orphan assets from JumpServer whose containers/records no longer exist.
        """
        raw_assets = self.jms.client.get("/api/v1/assets/assets/")
        all_assets = (
            raw_assets.get("results", [])
            if isinstance(raw_assets, dict)
            else (raw_assets if isinstance(raw_assets, list) else [])
        )

        with self.db_factory() as session:
            active_kiosks = session.query(KioskModel).all()
            known_asset_ids = {k.jms_asset_id for k in active_kiosks if k.jms_asset_id}
            known_names = {k.name.strip().upper() for k in active_kiosks if k.name}

        managed_assets = []
        purged_assets = []
        for asset in all_assets:
            if not isinstance(asset, dict):
                continue
            comment = str(asset.get("comment", "")).lower()
            tags = [str(t).lower() for t in asset.get("tags", [])]
            is_managed = (
                "managed by kiosk-manager" in comment
                or "managed by jumpserver kiosk manager" in comment
                or "kiosk-manager" in tags
                or "ephemeral" in tags
            )
            if not is_managed:
                continue

            managed_assets.append(asset)
            asset_id = asset.get("id")
            asset_name = str(asset.get("name", "")).strip().upper()

            # If asset is not associated with any active local kiosk record, it's an orphan
            if asset_id not in known_asset_ids and asset_name not in known_names:
                logger.info(
                    "[Garbage Collection] Found orphan JumpServer asset: %s (ID: %s). Purging...",
                    asset_name, asset_id,
                )
                deleted = self.jms.delete_asset(asset_id)
                if deleted:
                    purged_assets.append({"id": asset_id, "name": asset.get("name")})

        return {
            "total_jms_assets": len(all_assets),
            "managed_jms_assets": len(managed_assets),
            "local_kiosks_count": len(active_kiosks),
            "purged_count": len(purged_assets),
            "purged_assets": purged_assets,
        }
