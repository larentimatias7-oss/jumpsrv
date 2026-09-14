import pytest
from pathlib import Path
from app.jumpserver.config import JumpServerConfig, JumpServerSettings
from app.jumpserver.client import JumpServerClient


def test_verify_ssl_default():
    """Verify that SSL verification defaults to True for secure operations."""
    cfg = JumpServerConfig()
    assert cfg.verify_ssl is True


@pytest.mark.parametrize("val,expected", [
    ("false", False),
    ("False", False),
    ("0", False),
    ("no", False),
    ("off", False),
    ("true", True),
    ("True", True),
    ("1", True),
    ("yes", True),
    ("on", True),
])
def test_verify_ssl_env_parsing(monkeypatch, val, expected):
    """Test environment variable string parsing for JMS_VERIFY_SSL."""
    monkeypatch.setenv("JMS_VERIFY_SSL", val)
    cfg = JumpServerConfig()
    assert cfg.verify_ssl is expected


def test_verify_ssl_jumpserver_alias(monkeypatch):
    """Test that JUMPSERVER_VERIFY_SSL alias is also supported."""
    monkeypatch.delenv("JMS_VERIFY_SSL", raising=False)
    monkeypatch.setenv("JUMPSERVER_VERIFY_SSL", "false")
    cfg = JumpServerConfig()
    assert cfg.verify_ssl is False


def test_client_verify_propagation():
    """Test that JumpServerClient correctly sets _verify based on settings."""
    cfg_no_ssl = JumpServerConfig(
        base_url="https://192.168.1.50:443",
        key_id="test-key",
        secret_value="test-secret",
        verify_ssl=False,
    )
    client_no_ssl = JumpServerClient(settings=cfg_no_ssl)
    assert client_no_ssl._verify is False

    cfg_ssl = JumpServerConfig(
        base_url="https://192.168.1.50:443",
        key_id="test-key",
        secret_value="test-secret",
        verify_ssl=True,
    )
    client_ssl = JumpServerClient(settings=cfg_ssl)
    assert client_ssl._verify is True


def test_client_ca_bundle_precedence(tmp_path):
    """Test that ca_bundle takes precedence over verify_ssl boolean."""
    fake_ca = tmp_path / "custom_ca.crt"
    fake_ca.write_text("CERT")

    cfg = JumpServerConfig(
        base_url="https://192.168.1.50:443",
        key_id="test-key",
        secret_value="test-secret",
        verify_ssl=True,
        ca_bundle=fake_ca,
    )
    client = JumpServerClient(settings=cfg)
    assert client._verify == str(fake_ca)
