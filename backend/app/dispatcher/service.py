import asyncio
import logging
import os
import socket
import time
from typing import Dict, Optional
from ..docker_runtime.client import DockerRuntime
from ..models.database import KioskModel, init_db

logger = logging.getLogger("kiosk.dispatcher")
DEFAULT_KIOSK_IMAGE = os.getenv("KIOSK_DOCKER_IMAGE", "ghcr.io/larentimatias7-oss/jumpsrv/pam-web-kiosk:latest")


class KioskDispatcher:
    """
    Transparent TCP RDP Relay and Lifecycle Manager for on-demand (ephemeral) kiosks.
    Listens on the host RDP port assigned to each asset.
    Upon TCP connection:
      1. Starts the kiosk Docker container (if not running).
      2. Waits for container internal XRDP port to respond.
      3. Relays traffic bidirectionally.
    Upon connection termination:
      4. Waits for idle grace period (e.g. 120s), and stops the container if inactive.
    """

    def __init__(
        self,
        db_factory=None,
        docker_runtime: Optional[DockerRuntime] = None,
        idle_timeout: int = 120,
    ):
        self.db_factory = db_factory or init_db()
        self.docker = docker_runtime or DockerRuntime()
        self.idle_timeout = idle_timeout
        self.servers: Dict[int, asyncio.Server] = {}
        self.active_connections: Dict[int, int] = {}
        self.idle_tasks: Dict[int, asyncio.Task] = {}

    async def start_listening_for_kiosk(self, kiosk_id: str, host_ip: str, port: int):
        """Starts an asyncio TCP server for the given kiosk port."""
        if port in self.servers:
            return

        self.active_connections[port] = 0

        async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
            await self._handle_connection(kiosk_id, host_ip, port, client_reader, client_writer)

        try:
            server = await asyncio.start_server(handle_client, "0.0.0.0", port)
            self.servers[port] = server
            logger.info(f"Dispatcher listening on 0.0.0.0:{port} for kiosk {kiosk_id}")
        except Exception as e:
            logger.error(f"Failed to start dispatcher on 0.0.0.0:{port}: {e}")

    async def stop_listening(self, port: int):
        if port in self.servers:
            server = self.servers.pop(port)
            server.close()
            await server.wait_closed()
            logger.info(f"Dispatcher stopped listening on port {port}")

    async def _handle_connection(
        self,
        kiosk_id: str,
        host_ip: str,
        port: int,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        # Cancel any pending idle shutdown for this kiosk port
        if port in self.idle_tasks and not self.idle_tasks[port].done():
            self.idle_tasks[port].cancel()
            self.idle_tasks.pop(port, None)

        self.active_connections[port] = self.active_connections.get(port, 0) + 1
        logger.info(f"[RDP-SYN received] on port {port}. Active connections: {self.active_connections[port]}")

        # Retrieve kiosk details from DB
        with self.db_factory() as session:
            kiosk = session.query(KioskModel).get(kiosk_id)
            if not kiosk:
                logger.error(f"Kiosk {kiosk_id} not found in DB")
                client_writer.close()
                await client_writer.wait_closed()
                self.active_connections[port] -= 1
                return
            container_name = kiosk.container_name
            volume_name = kiosk.volume_name
            target_url = kiosk.target_url
            rdp_user = kiosk.rdp_username
            clean_name = kiosk.name

        # 1. Just-In-Time container start
        logger.info(f"[Container starting...] Ensuring container {container_name} is running for {clean_name}...")
        self.docker.ensure_container_running(
            container_name=container_name,
            image=DEFAULT_KIOSK_IMAGE,
            volume_name=volume_name,
            host_ip=host_ip,
            host_port=port,
            target_url=target_url,
            kiosk_id=kiosk_id,
            kiosk_name=clean_name,
            rdp_username=rdp_user,
        )

        # 2. Wait for XRDP to accept connections inside the container
        container_ip = None
        for _ in range(50):
            try:
                c = self.docker.client.containers.get(container_name)
                c.reload()
                if c.status == "running":
                    networks = c.attrs.get("NetworkSettings", {}).get("Networks", {})
                    if "bridge" in networks:
                        container_ip = networks["bridge"].get("IPAddress")
                    if not container_ip:
                        container_ip = c.attrs.get("NetworkSettings", {}).get("IPAddress")
                    if container_ip:
                        break
            except Exception:
                pass
            await asyncio.sleep(0.1)

        if not container_ip:
            logger.error(f"Could not get container IP for {container_name}")
            client_writer.close()
            await client_writer.wait_closed()
            self.active_connections[port] -= 1
            return

        # Poll container port 3389 with short backoff (every 100ms, timeout 30s for cold starts)
        logger.info(f"Probing XRDP on {container_ip}:3389 for {clean_name}...")
        target_reader, target_writer = None, None
        for attempt in range(300):
            try:
                target_reader, target_writer = await asyncio.open_connection(container_ip, 3389)
                logger.info(f"[XRDP port open and verified] Connected on attempt {attempt+1}")
                break
            except Exception:
                await asyncio.sleep(0.1)

        if not target_writer:
            logger.error(f"Timeout waiting for XRDP on {container_ip}:3389")
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except Exception:
                pass
            self.active_connections[port] -= 1
            return

        logger.info(f"[Piping traffic] Relaying traffic between JumpServer and {container_name} ({container_ip}:3389)...")

        # 3. Bidirectional Relay with immediate mutual teardown
        async def forward(source: asyncio.StreamReader, destination: asyncio.StreamWriter):
            try:
                while True:
                    data = await source.read(65536)
                    if not data:
                        break
                    destination.write(data)
                    await destination.drain()
            except Exception:
                pass
            finally:
                try:
                    destination.close()
                    await destination.wait_closed()
                except Exception:
                    pass

        try:
            t1 = asyncio.create_task(forward(client_reader, target_writer))
            t2 = asyncio.create_task(forward(target_reader, client_writer))
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            try:
                target_writer.close()
                await target_writer.wait_closed()
            except Exception:
                pass
            self.active_connections[port] = max(0, self.active_connections.get(port, 1) - 1)
            logger.info(f"Connection ended on port {port}. Remaining: {self.active_connections[port]}")
            if self.active_connections[port] == 0:
                self._schedule_idle_shutdown(kiosk_id, container_name, port)

    def _schedule_idle_shutdown(self, kiosk_id: str, container_name: str, port: int):
        async def shutdown():
            logger.info(f"Starting {self.idle_timeout}s idle timer for {container_name} on port {port}...")
            await asyncio.sleep(self.idle_timeout)
            if self.active_connections.get(port, 0) == 0:
                logger.info(f"Idle timeout reached for {container_name}. Stopping container to free RAM...")
                self.docker.stop_container(container_name)

        task = asyncio.create_task(shutdown())
        self.idle_tasks[port] = task
