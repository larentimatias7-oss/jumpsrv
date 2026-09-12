import json
import pytest
from app.jumpserver.autodiscovery import (
    load_cached_credentials,
    save_cached_credentials,
    get_or_discover_credentials,
)
from app.jumpserver.exceptions import JumpServerAuthError
from app.jumpserver.client import JumpServerClient
from app.jumpserver.config import JumpServerConfig
from app.provisioning.provisioner import detect_host_ip


def test_save_and_load_cached_credentials(tmp_path, monkeypatch):
    cache_file = tmp_path / "jms_cred.json"
    monkeypatch.setenv("JMS_CREDENTIALS_CACHE", str(cache_file))

    # Before saving
    assert load_cached_credentials() is None

    # Save
    save_cached_credentials("key-123", "secret-456")
    assert cache_file.exists()

    # Load
    loaded = load_cached_credentials()
    assert loaded == ("key-123", "secret-456")


def test_get_or_discover_credentials_explicit():
    k_id, sec = get_or_discover_credentials("explicit-key", "explicit-sec")
    assert k_id == "explicit-key"
    assert sec == "explicit-sec"


def test_get_or_discover_credentials_from_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "jms_cred2.json"
    monkeypatch.setenv("JMS_CREDENTIALS_CACHE", str(cache_file))
    cache_file.write_text(json.dumps({"key_id": "cached-k", "secret": "cached-s"}))

    k_id, sec = get_or_discover_credentials("", "")
    assert k_id == "cached-k"
    assert sec == "cached-s"


def test_client_raises_auth_error_when_no_credentials(tmp_path, monkeypatch):
    # Ensure no cache and no env
    cache_file = tmp_path / "empty_cache.json"
    monkeypatch.setenv("JMS_CREDENTIALS_CACHE", str(cache_file))
    monkeypatch.setenv("DOCKER_HOST", "unix:///nonexistent/docker.sock")

    cfg = JumpServerConfig(
        base_url="http://127.0.0.1:80",
        key_id="",
        secret_value="",
        secret_file=None,
    )
    client = JumpServerClient(settings=cfg)
    with pytest.raises(JumpServerAuthError) as exc_info:
        client._headers("GET", "/api/v1/assets/nodes/")

    assert "JumpServer AccessKey is not configured" in str(exc_info.value)


def test_detect_host_ip():
    ip = detect_host_ip()
    assert isinstance(ip, str)
    assert len(ip.split(".")) == 4
