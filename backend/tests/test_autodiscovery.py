import json
import pytest
from app.jumpserver.autodiscovery import (
    load_cached_credentials,
    save_cached_credentials,
    get_or_discover_credentials,
    autodiscover_from_core,
    parse_autodiscover_output,
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


def test_parse_autodiscover_output_v4_success():
    raw_output = (
        "Some debug logs...\n"
        'JMS_AUTODISCOVER_RESULT:{"key_id": "v4-key-id", "secret": "v4-secret-key", "user": "admin"}\n'
        "Done.\n"
    )
    result = parse_autodiscover_output(raw_output)
    assert result == ("v4-key-id", "v4-secret-key")


def test_parse_autodiscover_output_legacy_format():
    raw_output = (
        "Some debug logs...\n"
        "__JMS_AUTOKEY__:legacy-key-id:legacy-secret-key\n"
    )
    result = parse_autodiscover_output(raw_output)
    assert result == ("legacy-key-id", "legacy-secret-key")


def test_parse_autodiscover_output_error():
    raw_output = 'JMS_AUTODISCOVER_RESULT:{"error": "No active user found in JumpServer"}\n'
    result = parse_autodiscover_output(raw_output)
    assert result is None


def test_parse_autodiscover_output_invalid_json():
    raw_output = 'JMS_AUTODISCOVER_RESULT:{invalid json\n'
    result = parse_autodiscover_output(raw_output)
    assert result is None


def test_parse_autodiscover_output_empty():
    assert parse_autodiscover_output("") is None


def test_config_transparent_env_variables(monkeypatch):
    monkeypatch.setenv("JUMPSERVER_BASE_URL", "https://jms.internal:8443")
    monkeypatch.setenv("JUMPSERVER_KEY_ID", "jumpserver-key-abc")
    monkeypatch.setenv("JUMPSERVER_KEY_SECRET", "jumpserver-secret-xyz")
    # Ensure JMS_* variants are not set
    monkeypatch.delenv("JMS_BASE_URL", raising=False)
    monkeypatch.delenv("JMS_KEY_ID", raising=False)
    monkeypatch.delenv("JMS_SECRET_KEY", raising=False)
    monkeypatch.delenv("JMS_SECRET", raising=False)
    monkeypatch.delenv("JMS_SECRET_VALUE", raising=False)

    cfg = JumpServerConfig()
    assert cfg.base_url == "https://jms.internal:8443"
    assert cfg.get_key_id() == "jumpserver-key-abc"
    assert cfg.load_secret() == "jumpserver-secret-xyz"
