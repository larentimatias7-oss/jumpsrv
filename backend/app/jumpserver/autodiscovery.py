from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("kiosk.jumpserver.autodiscover")

DEFAULT_CACHE_PATH = "/app/data/jms_credentials.json"


def get_cache_file_path() -> Path:
    env_path = os.environ.get("JMS_CREDENTIALS_CACHE", DEFAULT_CACHE_PATH)
    return Path(env_path)


def load_cached_credentials() -> Optional[Tuple[str, str]]:
    """Load credentials from persistent cache file if it exists and is valid."""
    cache_file = get_cache_file_path()
    try:
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            key_id = data.get("key_id", "").strip()
            secret = data.get("secret", "").strip()
            if key_id and secret:
                logger.info(f"Loaded JumpServer credentials from persistent cache: {key_id}")
                return key_id, secret
    except Exception as e:
        logger.warning(f"Failed to load cached JumpServer credentials from {cache_file}: {e}")
    return None


def save_cached_credentials(key_id: str, secret: str) -> None:
    """Save discovered JumpServer credentials to persistent cache file."""
    cache_file = get_cache_file_path()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"key_id": key_id, "secret": secret}, indent=2),
            encoding="utf-8"
        )
        try:
            os.chmod(cache_file, 0o600)
        except Exception:
            pass
        logger.info(f"Saved JumpServer credentials to cache file: {cache_file}")
    except Exception as e:
        logger.warning(f"Failed to persist JumpServer credentials to {cache_file}: {e}")


def discover_from_docker_jms_core() -> Optional[Tuple[str, str]]:
    """Query or auto-create JumpServer AccessKey inside local jms_core container via Docker socket."""
    try:
        import docker
    except ImportError:
        logger.debug("docker SDK not installed; skipping docker auto-discovery.")
        return None

    socket_path = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    if socket_path.startswith("unix://"):
        sock_file = Path(socket_path.replace("unix://", ""))
        if not sock_file.exists():
            logger.debug(f"Docker socket file {sock_file} does not exist.")
            return None

    try:
        client = docker.DockerClient(base_url=socket_path, timeout=3)
    except Exception as e:
        logger.debug(f"Docker client cannot connect to {socket_path}: {e}")
        return None

    try:
        # Search for jms_core container
        containers = client.containers.list(filters={"name": "jms_core"})
        if not containers:
            for c in client.containers.list():
                if "jms_core" in c.name:
                    containers = [c]
                    break

        if not containers:
            logger.debug("No running jms_core container found on local Docker host.")
            return None

        core_c = containers[0]
        logger.info(f"Detected JumpServer core container ({core_c.name}). Querying AccessKey...")

        python_snippet = (
            "from authentication.models import AccessKey\n"
            "from users.models import User\n"
            "admin = User.objects.filter(is_superuser=True).first()\n"
            "if admin:\n"
            "    ak = AccessKey.objects.filter(user=admin).first()\n"
            "    if not ak:\n"
            "        ak = AccessKey.objects.create(user=admin)\n"
            "    print(f'__JMS_AUTOKEY__:{ak.id}:{ak.secret}')\n"
            "else:\n"
            "    print('__JMS_NO_ADMIN__')\n"
        )

        exec_res = core_c.exec_run([
            "/opt/py3/bin/python",
            "/opt/jumpserver/apps/manage.py",
            "shell",
            "-c",
            python_snippet,
        ])

        if exec_res.exit_code == 0 and exec_res.output:
            text = exec_res.output.decode("utf-8", errors="ignore")
            for line in text.splitlines():
                if line.startswith("__JMS_AUTOKEY__:"):
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        key_id = parts[1].strip()
                        secret = parts[2].strip()
                        if key_id and secret:
                            logger.info(f"Auto-discovered JumpServer AccessKey ID: {key_id}")
                            save_cached_credentials(key_id, secret)
                            return key_id, secret

        logger.warning(f"jms_core shell query returned exit code {exec_res.exit_code}: {exec_res.output}")
    except Exception as e:
        logger.warning(f"Could not auto-discover JumpServer credentials from Docker: {e}")

    return None


def get_or_discover_credentials(
    configured_key_id: Optional[str] = None,
    configured_secret: Optional[str] = None,
) -> Tuple[str, str]:
    """Retrieve JumpServer credentials from configuration, persistent cache, or Docker discovery."""
    key_id = (configured_key_id or "").strip()
    secret = (configured_secret or "").strip()

    if key_id and secret:
        return key_id, secret

    # 1. Try loading from persistent cache file
    cached = load_cached_credentials()
    if cached:
        cached_id, cached_secret = cached
        if not key_id:
            key_id = cached_id
        if not secret:
            secret = cached_secret
        if key_id and secret:
            return key_id, secret

    # 2. Try auto-discovery via local Docker socket
    discovered = discover_from_docker_jms_core()
    if discovered:
        disc_id, disc_secret = discovered
        if not key_id:
            key_id = disc_id
        if not secret:
            secret = disc_secret
        if key_id and secret:
            return key_id, secret

    return key_id, secret
