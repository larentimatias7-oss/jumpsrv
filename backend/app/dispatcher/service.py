from __future__ import annotations
import asyncio
import logging
import os
import socket
import time
from typing import Any, Dict, Optional
from ..config import (
    DEFAULT_DISCONNECT_GRACE_SECONDS,
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_MAX_SESSION_LIFETIME_SECONDS,
    DEFAULT_MAX_CONCURRENT_SESSIONS,
)
from ..docker_runtime.client import DockerRuntime
from ..models.database import KioskModel, init_db
from ..provisioning.provisioner import wait_for_rdp_ready

logger = logging.getLogger("kiosk.dispatcher")
DEFAULT_KIOSK_IMAGE = os.getenv("KIOSK_DOCKER_IMAGE", "ghcr.io/larentimatias7-oss/jumpsrv/pam-web-kiosk:latest")

__all__ = ["KioskDispatcher", "wait_for_rdp_ready"]


class KioskDispatcher:
    """
    Transparent TCP RDP Relay and Session Lifecycle Manager for on-demand (ephemeral) kiosks.
    Listens on the host RDP port assigned to each asset.

    Upon TCP connection:
      1. Starts the kiosk Docker container (if not running).
      2. Waits for container internal XRDP port to respond.
      3. Sets asset status to RUNNING in database.
      4. Relays traffic bidirectionally and tracks activity.

    Lifecycle and RAM Conservation Policies:
      - Disconnect Grace: When active_connections == 0, waits configurable grace period
        (default 30s) before stopping container, tolerating page reloads (F5) or network blips.
      - Idle Traffic Timeout: If no RDP traffic is observed for idle_timeout_seconds (default 15m),
        forces socket closure, stops container, and marks asset IDLE.
      - Max Session Lifetime: If continuous session duration reaches max_session_lifetime_seconds
        (default 4h), terminates session and stops container to prevent orphan memory usage.
      - Max Concurrent Sessions: Enforces host limit (default 4) of simultaneously running containers
        to prevent memory exhaustion / OOM crashes.
    """

    def __init__(
        self,
        db_factory=None,
        docker_runtime: Optional[DockerRuntime] = None,
        disconnect_grace_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        max_session_lifetime_seconds: Optional[int] = None,
        max_concurrent_sessions: Optional[int] = None,
        idle_timeout: Optional[int] = None,  # Backward compatibility
    ):
        self.db_factory = db_factory or init_db()
        self.docker = docker_runtime or DockerRuntime()

        # Prioritize explicit disconnect_grace_seconds over legacy idle_timeout
        if disconnect_grace_seconds is not None:
            self.disconnect_grace_seconds = int(disconnect_grace_seconds)
        elif idle_timeout is not None:
            self.disconnect_grace_seconds = int(idle_timeout)
        else:
            self.disconnect_grace_seconds = DEFAULT_DISCONNECT_GRACE_SECONDS

        self.idle_timeout_seconds = (
            int(idle_timeout_seconds)
            if idle_timeout_seconds is not None
            else DEFAULT_IDLE_TIMEOUT_SECONDS
        )
        self.max_session_lifetime_seconds = (
            int(max_session_lifetime_seconds)
            if max_session_lifetime_seconds is not None
            else DEFAULT_MAX_SESSION_LIFETIME_SECONDS
        )
        self.max_concurrent_sessions = (
            int(max_concurrent_sessions)
            if max_concurrent_sessions is not None
            else DEFAULT_MAX_CONCURRENT_SESSIONS
        )

        # Backward compatibility attribute
        self.idle_timeout = self.disconnect_grace_seconds

        self.servers: Dict[int, asyncio.Server] = {}
        self.active_connections: Dict[int, int] = {}
        self.idle_tasks: Dict[int, asyncio.Task] = {}

    def update_lifecycle_settings(
        self,
        disconnect_grace_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        max_session_lifetime_seconds: Optional[int] = None,
        max_concurrent_sessions: Optional[int] = None,
    ):
        """Update lifecycle timer thresholds and limits dynamically in running dispatcher."""
        if disconnect_grace_seconds is not None:
            self.disconnect_grace_seconds = int(disconnect_grace_seconds)
            self.idle_timeout = self.disconnect_grace_seconds
        if idle_timeout_seconds is not None:
            self.idle_timeout_seconds = int(idle_timeout_seconds)
        if max_session_lifetime_seconds is not None:
            self.max_session_lifetime_seconds = int(max_session_lifetime_seconds)
        if max_concurrent_sessions is not None:
            self.max_concurrent_sessions = int(max_concurrent_sessions)

        logger.info(
            f"Dispatcher lifecycle policies updated: disconnect_grace={self.disconnect_grace_seconds}s, "
            f"idle_timeout={self.idle_timeout_seconds}s, max_session_lifetime={self.max_session_lifetime_seconds}s, "
            f"max_concurrent_sessions={self.max_concurrent_sessions}"
        )

    def _update_kiosk_status(self, kiosk_id: str, new_status: str):
        """Safely update kiosk status in database."""
        try:
            with self.db_factory() as session:
                k = session.get(KioskModel, kiosk_id)
                if k and k.status != new_status:
                    k.status = new_status
                    session.commit()
                    logger.info(f"Updated kiosk {kiosk_id} DB status to {new_status}")
        except Exception as e:
            logger.warning(f"Failed to update kiosk {kiosk_id} status to {new_status}: {e}")

    def _stop_and_set_idle(self, kiosk_id: str, container_name: str, port: int, reason: str):
        """Stop container to release RAM and mark status as IDLE with structured logging."""
        logger.info(
            f"Session lifecycle event: {reason} [kiosk_id={kiosk_id}, port={port}, container={container_name}] - "
            f"stopping container to free RAM and setting status to IDLE"
        )
        try:
            self.docker.stop_container(container_name)
        except Exception as e:
            logger.warning(f"Error stopping container {container_name} on {reason}: {e}")
        self._update_kiosk_status(kiosk_id, "IDLE")

    def _schedule_disconnect_grace(self, kiosk_id: str, container_name: str, port: int):
        """Schedule delayed shutdown after client disconnect to tolerate micro-cuts and reloads."""
        async def grace_shutdown():
            grace_secs = self.disconnect_grace_seconds
            logger.info(
                f"Starting disconnect grace timer ({grace_secs}s) for {container_name} on port {port}..."
            )
            await asyncio.sleep(grace_secs)
            if self.active_connections.get(port, 0) == 0:
                self._stop_and_set_idle(kiosk_id, container_name, port, reason="grace_expired")

        task = asyncio.create_task(grace_shutdown())
        self.idle_tasks[port] = task

    def reconcile_running_containers(self) -> Dict[str, Any]:
        """
        Periodically garbage-collects orphan, abandoned, or idle kiosk containers:
        1. Queries all kiosks currently registered in the database.
        2. Inspects all Docker containers carrying label 'managed-by=jumpserver-kiosk-manager'.
        3. If a managed container does not correspond to any registered kiosk in DB -> remove it.
        4. If a managed container is 'running', but:
           - The dispatcher has 0 active connections for this kiosk's port, AND
           - There is no active disconnect grace timer (or grace expired)
           -> Stop container to release 768MB RAM and update status to IDLE.
        """
        stopped_count = 0
        removed_orphan_count = 0

        try:
            managed_containers = self.docker.list_managed_containers(all=True)
        except Exception as e:
            logger.error(f"Failed to list managed containers for reconciliation: {e}")
            return {"stopped": 0, "removed": 0, "error": str(e)}

        with self.db_factory() as session:
            kiosks = session.query(KioskModel).all()
            known_by_container = {k.container_name: k for k in kiosks if k.container_name}
            known_by_id = {k.id: k for k in kiosks if k.id}

        for c in managed_containers:
            try:
                c_name = getattr(c, "name", "")
                c_status = getattr(c, "status", "")
                labels = getattr(c, "labels", {}) or {}
                kiosk_id = labels.get("kiosk-id")

                matched_kiosk = known_by_container.get(c_name) or known_by_id.get(kiosk_id)

                # 1. Orphan container without DB record
                if not matched_kiosk:
                    logger.warning(
                        f"Found orphan kiosk container without DB record: {c_name} (status={c_status}). Cleaning up..."
                    )
                    self.docker.remove_orphan_container(c_name)
                    removed_orphan_count += 1
                    continue

                # 2. Running container with 0 connections and no grace period
                port = matched_kiosk.rdp_port
                if c_status == "running":
                    active_conn = self.active_connections.get(port, 0) if port else 0
                    is_in_grace = (
                        port in self.idle_tasks and not self.idle_tasks[port].done()
                        if port
                        else False
                    )

                    if active_conn == 0 and not is_in_grace:
                        logger.info(
                            f"Container GC: container {c_name} on port {port} is running with 0 connections. "
                            f"Stopping to free 768MB RAM and setting status IDLE..."
                        )
                        self._stop_and_set_idle(
                            matched_kiosk.id,
                            c_name,
                            port or 0,
                            reason="orphan_running_reconciliation",
                        )
                        stopped_count += 1
            except Exception as item_err:
                logger.warning(f"Error inspecting managed container for GC: {item_err}")

        return {
            "stopped": stopped_count,
            "removed": removed_orphan_count,
        }

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
        # Cancel any pending grace shutdown for this kiosk port (e.g. reconnect or page reload)
        if port in self.idle_tasks and not self.idle_tasks[port].done():
            logger.info(f"Cancelling pending grace shutdown on port {port} due to new incoming connection")
            self.idle_tasks[port].cancel()
            self.idle_tasks.pop(port, None)

        self.active_connections[port] = self.active_connections.get(port, 0) + 1
        logger.info(f"[RDP-SYN received] on port {port}. Active connections: {self.active_connections[port]}")

        # Retrieve kiosk details from DB
        with self.db_factory() as session:
            kiosk = session.get(KioskModel, kiosk_id)
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

        # Prevent host memory exhaustion: enforce max concurrent running sessions
        if not self.docker.is_container_running(container_name):
            running_count = self.docker.count_running_containers()
            if running_count >= self.max_concurrent_sessions:
                logger.warning(
                    f"[Concurrency Limit Exceeded] Rejecting connection to {container_name} on port {port}. "
                    f"Active running sessions ({running_count}) reached maximum allowed ({self.max_concurrent_sessions})."
                )
                client_writer.close()
                try:
                    await client_writer.wait_closed()
                except Exception:
                    pass
                self.active_connections[port] -= 1
                return

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
        self._update_kiosk_status(kiosk_id, "RUNNING")

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
            if self.active_connections[port] == 0:
                self._stop_and_set_idle(kiosk_id, container_name, port, reason="ip_resolution_failed")
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
            if self.active_connections[port] == 0:
                self._stop_and_set_idle(kiosk_id, container_name, port, reason="xrdp_probe_timeout")
            return

        logger.info(f"[Piping traffic] Relaying traffic between JumpServer and {container_name} ({container_ip}:3389)...")

        # 3. Session state and activity tracking
        session_start_time = time.time()
        session_info: Dict[str, Any] = {
            "start_time": session_start_time,
            "last_traffic_time": session_start_time,
            "termination_reason": None,
        }
        session_active = True

        async def session_watchdog():
            """Monitors idle traffic timeout and max absolute session lifetime."""
            nonlocal session_active
            while session_active:
                check_interval = min(
                    1.0,
                    max(0.05, self.idle_timeout_seconds / 10.0),
                    max(0.05, self.max_session_lifetime_seconds / 10.0),
                )
                await asyncio.sleep(check_interval)
                now = time.time()

                # Condition 3: Maximum Absolute Session Lifetime (e.g. 4 hours)
                if now - session_info["start_time"] >= self.max_session_lifetime_seconds:
                    session_info["termination_reason"] = "max_lifetime_exceeded"
                    logger.warning(
                        f"Session terminated: max_lifetime_exceeded [kiosk_id={kiosk_id}, port={port}, "
                        f"duration={now - session_info['start_time']:.1f}s, limit={self.max_session_lifetime_seconds}s]"
                    )
                    session_active = False
                    try:
                        client_writer.close()
                    except Exception:
                        pass
                    try:
                        target_writer.close()
                    except Exception:
                        pass
                    break

                # Condition 2: Inactivity due to lack of traffic (e.g. 15 minutes)
                if now - session_info["last_traffic_time"] >= self.idle_timeout_seconds:
                    session_info["termination_reason"] = "idle_timeout"
                    logger.warning(
                        f"Session terminated: idle_timeout [kiosk_id={kiosk_id}, port={port}, "
                        f"idle_duration={now - session_info['last_traffic_time']:.1f}s, limit={self.idle_timeout_seconds}s]"
                    )
                    session_active = False
                    try:
                        client_writer.close()
                    except Exception:
                        pass
                    try:
                        target_writer.close()
                    except Exception:
                        pass
                    break

        async def forward(source: asyncio.StreamReader, destination: asyncio.StreamWriter, direction: str):
            nonlocal session_active
            try:
                while session_active:
                    data = await source.read(65536)
                    if not data:
                        break
                    session_info["last_traffic_time"] = time.time()
                    destination.write(data)
                    await destination.drain()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug(f"Forward exception ({direction}) on port {port}: {exc}")
            finally:
                try:
                    destination.close()
                    await destination.wait_closed()
                except Exception:
                    pass

        watchdog_task = asyncio.create_task(session_watchdog())
        t1 = asyncio.create_task(forward(client_reader, target_writer, "client->container"))
        t2 = asyncio.create_task(forward(target_reader, client_writer, "container->client"))

        try:
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            session_active = False
            for p in pending:
                p.cancel()
        finally:
            session_active = False
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass

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
            remaining = self.active_connections[port]
            logger.info(f"Connection ended on port {port}. Remaining active: {remaining}")

            term_reason = session_info.get("termination_reason")
            if remaining == 0:
                if term_reason in ("idle_timeout", "max_lifetime_exceeded"):
                    self._stop_and_set_idle(kiosk_id, container_name, port, reason=term_reason)
                else:
                    # Normal disconnect / tab closed: start grace period
                    self._schedule_disconnect_grace(kiosk_id, container_name, port)
