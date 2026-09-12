from __future__ import annotations
import os
import logging
from typing import Any, Optional
import docker
from docker.errors import NotFound, APIError

logger = logging.getLogger("kiosk.docker")

LABEL_MANAGED_BY = "managed-by"
LABEL_VALUE = "jumpserver-kiosk-manager"
LABEL_KIOSK_ID = "kiosk-id"
LABEL_KIOSK_NAME = "kiosk-name"


class DockerRuntime:
    """Manages containers exclusively via Rootless Docker daemon."""

    def __init__(self, socket_path: Optional[str] = None):
        if not socket_path:
            xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
            if xdg_runtime:
                socket_path = f"unix://{xdg_runtime}/docker.sock"
            else:
                # Default rootless socket fallback for kiosk-runtime
                socket_path = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")

        # Ensure we never touch rootful socket if running under kiosk-runtime
        logger.info(f"Connecting to Docker socket: {socket_path}")
        self.socket_path = socket_path
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                self._client = docker.DockerClient(base_url=self.socket_path)
            except Exception as e:
                logger.warning(f"Docker daemon not yet available on {self.socket_path}: {e}")
                raise
        return self._client

    def is_managed_by_us(self, labels: dict[str, str]) -> bool:
        return labels.get(LABEL_MANAGED_BY) == LABEL_VALUE

    def create_volume(self, volume_name: str, kiosk_id: str) -> str:
        labels = {
            LABEL_MANAGED_BY: LABEL_VALUE,
            LABEL_KIOSK_ID: kiosk_id,
        }
        try:
            vol = self.client.volumes.get(volume_name)
            return vol.name
        except NotFound:
            vol = self.client.volumes.create(name=volume_name, labels=labels)
            return vol.name

    def remove_volume(self, volume_name: str) -> bool:
        try:
            vol = self.client.volumes.get(volume_name)
            if self.is_managed_by_us(vol.attrs.get("Labels", {}) or {}):
                vol.remove(force=True)
                return True
        except Exception as e:
            logger.warning(f"Could not remove volume {volume_name}: {e}")
        return False

    def run_kiosk_container(
        self,
        container_name: str,
        image: str,
        volume_name: str,
        host_ip: str,
        host_port: int,
        target_url: str,
        kiosk_id: str,
        kiosk_name: str,
        rdp_username: str = "kiosk",
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> str:
        labels = {
            LABEL_MANAGED_BY: LABEL_VALUE,
            LABEL_KIOSK_ID: kiosk_id,
            LABEL_KIOSK_NAME: kiosk_name,
        }

        # Check existing
        try:
            existing = self.client.containers.get(container_name)
            if self.is_managed_by_us(existing.labels):
                existing.remove(force=True)
        except NotFound:
            pass

        ports = {}
        if host_port > 0:
            # Container internal exposure or isolated bridge
            pass
        volumes = {
            volume_name: {"bind": "/home/kiosk/.config/chromium", "mode": "rw"}
        }
        environment = {
            "TARGET_URL": target_url,
            "SCREEN_WIDTH": str(screen_width),
            "SCREEN_HEIGHT": str(screen_height),
            "KIOSK_NAME": kiosk_name,
            "RDP_USERNAME": rdp_username,
        }

        container = self.client.containers.run(
            image=image,
            name=container_name,
            detach=True,
            restart_policy={"Name": "no"},
            shm_size="256m",
            mem_limit="768m",
            nano_cpus=1000000000,
            volumes=volumes,
            environment=environment,
            labels=labels,
        )
        return container.id

    def ensure_container_running(
        self,
        container_name: str,
        image: str,
        volume_name: str,
        host_ip: str,
        host_port: int,
        target_url: str,
        kiosk_id: str,
        kiosk_name: str,
        rdp_username: str = "kiosk",
    ) -> bool:
        try:
            c = self.client.containers.get(container_name)
            if c.status != "running":
                c.start()
            return True
        except NotFound:
            self.run_kiosk_container(
                container_name=container_name,
                image=image,
                volume_name=volume_name,
                host_ip=host_ip,
                host_port=host_port,
                target_url=target_url,
                kiosk_id=kiosk_id,
                kiosk_name=kiosk_name,
                rdp_username=rdp_username,
            )
            return True
        except Exception as e:
            logger.error(f"Error ensuring container {container_name} is running: {e}")
            return False

    def stop_container(self, container_name: str) -> bool:
        try:
            c = self.client.containers.get(container_name)
            if c.status == "running":
                c.stop(timeout=5)
            return True
        except NotFound:
            return True
        except Exception as e:
            logger.warning(f"Error stopping container {container_name}: {e}")
            return False

    def stop_and_remove_container(self, container_name: str) -> bool:
        try:
            c = self.client.containers.get(container_name)
            if self.is_managed_by_us(c.labels):
                c.remove(force=True)
                return True
        except NotFound:
            return True
        except Exception as e:
            logger.error(f"Error removing container {container_name}: {e}")
        return False

    def restart_container(self, container_name: str) -> bool:
        try:
            c = self.client.containers.get(container_name)
            c.restart(timeout=10)
            return True
        except Exception as e:
            logger.error(f"Failed to restart {container_name}: {e}")
            return False

    def get_container_status(self, container_name: str) -> dict[str, Any]:
        try:
            c = self.client.containers.get(container_name)
            c.reload()
            health = c.attrs.get("State", {}).get("Health", {}).get("Status", "none")
            status = c.status
            return {
                "exists": True,
                "status": status,
                "health": health,
                "is_running": status == "running",
            }
        except NotFound:
            return {"exists": False, "status": "not_found", "health": "none", "is_running": False}
        except Exception as e:
            logger.debug(f"Docker connection unavailable when inspecting {container_name}: {e}")
            return {"exists": False, "status": "docker_offline", "health": "unknown", "is_running": False}
