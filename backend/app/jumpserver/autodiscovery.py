from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("kiosk.jumpserver.autodiscover")

DEFAULT_CACHE_PATH = "/app/data/jms_credentials.json"

JMS_CORE_PYTHON_SNIPPET = (
    "import json\n"
    "from authentication.models import AccessKey\n"
    "from users.models import User\n"
    "\n"
    "user = None\n"
    "\n"
    "# JumpServer v4 role-based admin resolution\n"
    "if hasattr(User, 'role'):\n"
    "    try:\n"
    "        user = User.objects.filter(role__name__icontains='Admin').first()\n"
    "    except Exception:\n"
    "        pass\n"
    "\n"
    "# JumpServer v3 legacy superuser fallback\n"
    "if not user:\n"
    "    try:\n"
    "        user = User.objects.filter(is_superuser=True).first()\n"
    "    except Exception:\n"
    "        pass\n"
    "\n"
    "# Fallback by default accounts\n"
    "if not user:\n"
    "    try:\n"
    "        user = User.objects.filter(username='admin').first()\n"
    "    except Exception:\n"
    "        pass\n"
    "if not user:\n"
    "    try:\n"
    "        user = User.objects.filter(is_active=True).first()\n"
    "    except Exception:\n"
    "        pass\n"
    "\n"
    "if not user:\n"
    "    err_payload = {'error': 'No active user found in JumpServer'}\n"
    "    print(f'JMS_AUTODISCOVER_RESULT:{json.dumps(err_payload)}')\n"
    "else:\n"
    "    try:\n"
    "        ak = AccessKey.objects.filter(user=user, is_active=True).first()\n"
    "        if not ak:\n"
    "            ak = AccessKey.objects.create(user=user)\n"
    "        payload = {'key_id': str(ak.id), 'secret': str(ak.secret), 'user': user.username}\n"
    "        print(f'JMS_AUTODISCOVER_RESULT:{json.dumps(payload)}')\n"
    "    except Exception as exc:\n"
    "        err_payload = {'error': str(exc)}\n"
    "        print(f'JMS_AUTODISCOVER_RESULT:{json.dumps(err_payload)}')\n"
)


def get_cache_file_path() -> Path:
    """Return the filesystem path for JumpServer credentials cache."""
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
            encoding="utf-8",
        )
        try:
            os.chmod(cache_file, 0o600)
        except Exception:
            pass
        logger.info(f"Saved JumpServer credentials to cache file: {cache_file}")
    except Exception as e:
        logger.warning(f"Failed to persist JumpServer credentials to {cache_file}: {e}")


def parse_autodiscover_output(output_text: str) -> Optional[Tuple[str, str]]:
    """Parse stdout/stderr output from JumpServer manage.py shell execution.

    Scans lines for the prefix `JMS_AUTODISCOVER_RESULT:` and parses the JSON payload.
    Supports legacy `__JMS_AUTOKEY__:` format as fallback.

    Args:
        output_text: Command output string from jms_core.

    Returns:
        Tuple[str, str] containing (key_id, secret) if valid, None otherwise.
    """
    if not output_text:
        return None

    for line in output_text.splitlines():
        line = line.strip()
        if line.startswith("JMS_AUTODISCOVER_RESULT:"):
            payload_str = line[len("JMS_AUTODISCOVER_RESULT:"):].strip()
            try:
                payload = json.loads(payload_str)
                if not isinstance(payload, dict):
                    logger.warning(f"Unexpected non-dict JSON in autodiscovery output: {payload_str}")
                    return None
                if "error" in payload:
                    logger.warning(f"JumpServer autodiscovery returned error: {payload['error']}")
                    return None
                key_id = str(payload.get("key_id", "")).strip()
                secret = str(payload.get("secret", "")).strip()
                user_name = payload.get("user", "unknown")
                if key_id and secret:
                    logger.info(f"Auto-discovered JumpServer AccessKey ID: {key_id} (user: {user_name})")
                    return key_id, secret
                logger.warning(f"Autodiscovery payload missing key_id or secret: {payload}")
                return None
            except json.JSONDecodeError as jde:
                logger.warning(f"Failed to parse JMS_AUTODISCOVER_RESULT JSON '{payload_str}': {jde}")
                return None
        elif line.startswith("__JMS_AUTOKEY__:"):
            parts = line.split(":", 2)
            if len(parts) == 3:
                key_id = parts[1].strip()
                secret = parts[2].strip()
                if key_id and secret:
                    logger.info(f"Auto-discovered JumpServer AccessKey ID (legacy format): {key_id}")
                    return key_id, secret
    return None


def autodiscover_from_core() -> Optional[Tuple[str, str]]:
    """Query or auto-create JumpServer AccessKey inside local jms_core container via Docker socket.

    Connects to the Docker daemon via UNIX socket, finds the running `jms_core` container,
    and executes manage.py shell with hierarchical admin user resolution (supporting JumpServer v4
    RBAC role models and v3 superuser flags).

    Returns:
        Tuple[str, str] containing (key_id, secret) if successful, None otherwise.
    """
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

        exec_cmds = [
            ["/opt/py3/bin/python", "/opt/jumpserver/apps/manage.py", "shell", "-c", JMS_CORE_PYTHON_SNIPPET],
            ["python", "/opt/jumpserver/apps/manage.py", "shell", "-c", JMS_CORE_PYTHON_SNIPPET],
        ]

        exec_res = None
        for cmd in exec_cmds:
            try:
                res = core_c.exec_run(cmd)
                exec_res = res
                if res.exit_code == 0:
                    break
            except Exception as e:
                logger.debug(f"Execution failed with command {cmd[0]}: {e}")

        if exec_res and exec_res.output:
            text = exec_res.output.decode("utf-8", errors="ignore")
            creds = parse_autodiscover_output(text)
            if creds:
                save_cached_credentials(creds[0], creds[1])
                return creds

        exit_code = exec_res.exit_code if exec_res else "None"
        output_sample = exec_res.output[:200] if exec_res and exec_res.output else "None"
        logger.warning(f"jms_core shell query returned exit code {exit_code}: {output_sample}")
    except Exception as e:
        logger.warning(f"Could not auto-discover JumpServer credentials from Docker: {e}")

    return None


# Backward-compatible alias
discover_from_docker_jms_core = autodiscover_from_core


def get_or_discover_credentials(
    configured_key_id: Optional[str] = None,
    configured_secret: Optional[str] = None,
) -> Tuple[str, str]:
    """Retrieve JumpServer credentials from configuration, environment, persistent cache, or Docker discovery."""
    key_id = (configured_key_id or "").strip()
    secret = (configured_secret or "").strip()

    if key_id and secret:
        return key_id, secret

    # Environment variables check (supports both JMS_ and JUMPSERVER_ prefixes)
    if not key_id:
        key_id = os.getenv("JMS_KEY_ID", os.getenv("JUMPSERVER_KEY_ID", "")).strip()
    if not secret:
        secret = os.getenv(
            "JMS_SECRET_KEY",
            os.getenv(
                "JMS_SECRET",
                os.getenv(
                    "JMS_SECRET_VALUE",
                    os.getenv("JUMPSERVER_KEY_SECRET", os.getenv("JUMPSERVER_SECRET", "")),
                ),
            ),
        ).strip()

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
    discovered = autodiscover_from_core()
    if discovered:
        disc_id, disc_secret = discovered
        if not key_id:
            key_id = disc_id
        if not secret:
            secret = disc_secret
        if key_id and secret:
            return key_id, secret

    return key_id, secret
