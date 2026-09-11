import pytest
from unittest.mock import Mock
from app.jumpserver.operations import JumpServerOperations
from app.jumpserver.client import JumpServerClient


def test_create_rdp_asset():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "asset-uuid-1", "name": "TEST-SW"}

    ops = JumpServerOperations(mock_client)
    res = ops.create_rdp_asset(
        name="TEST-SW",
        ip="192.168.1.100",
        port=33891,
        node_id="node-1",
        platform="Windows",
    )

    assert res["id"] == "asset-uuid-1"
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "/api/v1/assets/assets/"
    assert args[1]["protocols"] == [{"name": "rdp", "port": 33891}]


def test_create_account():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "acc-uuid-1", "username": "kiosk_user"}

    ops = JumpServerOperations(mock_client)
    res = ops.create_account(
        asset_id="asset-uuid-1",
        username="kiosk_user",
        secret="super_secret_32_chars",
    )

    assert res["id"] == "acc-uuid-1"
    mock_client.post.assert_called_once()
