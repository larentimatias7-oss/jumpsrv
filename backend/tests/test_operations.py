import pytest
from unittest.mock import Mock
from app.jumpserver.operations import JumpServerOperations, is_valid_uuid
from app.jumpserver.client import JumpServerClient


def test_is_valid_uuid():
    assert is_valid_uuid("8efe99ea-dee5-4ba0-9ad2-1978d91e8f65") is True
    assert is_valid_uuid("") is False
    assert is_valid_uuid("/DEFAULT") is False
    assert is_valid_uuid("node-1") is False
    assert is_valid_uuid(None) is False


def test_create_rdp_asset_with_explicit_uuid():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "asset-uuid-1", "name": "TEST-SW"}

    ops = JumpServerOperations(mock_client)
    res = ops.create_rdp_asset(
        name="TEST-SW",
        ip="192.168.1.100",
        port=33891,
        node_id="8efe99ea-dee5-4ba0-9ad2-1978d91e8f65",
        platform="Windows",
    )

    assert res["id"] == "asset-uuid-1"
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "/api/v1/assets/hosts/"
    assert args[1]["name"] == "TEST-SW"
    assert args[1]["address"] == "192.168.1.100"
    assert args[1]["platform"] == 5
    assert args[1]["protocols"] == [{"name": "rdp", "port": 33891}]
    assert args[1]["nodes"] == ["8efe99ea-dee5-4ba0-9ad2-1978d91e8f65"]
    assert args[1]["is_active"] is True


def test_create_rdp_asset_resolves_default_node_and_caches():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "asset-uuid-2", "name": "TEST-DEFAULT"}
    mock_client.get.return_value = [
        {"id": "8efe99ea-dee5-4ba0-9ad2-1978d91e8f65", "name": "Default", "value": "DEFAULT"}
    ]

    ops = JumpServerOperations(mock_client)
    # 1. First call with empty string node_id
    res1 = ops.create_rdp_asset(
        name="TEST-DEFAULT-1",
        ip="192.168.1.101",
        port=33892,
        node_id="",
        platform=5,
    )
    assert res1["id"] == "asset-uuid-2"
    args1, _ = mock_client.post.call_args
    assert args1[1]["nodes"] == ["8efe99ea-dee5-4ba0-9ad2-1978d91e8f65"]
    assert mock_client.get.call_count == 1

    # 2. Second call with /DEFAULT - should use cache and not call get again
    res2 = ops.create_rdp_asset(
        name="TEST-DEFAULT-2",
        ip="192.168.1.102",
        port=33893,
        node_id="/DEFAULT",
        platform=5,
    )
    assert res2["id"] == "asset-uuid-2"
    args2, _ = mock_client.post.call_args
    assert args2[1]["nodes"] == ["8efe99ea-dee5-4ba0-9ad2-1978d91e8f65"]
    assert mock_client.get.call_count == 1


def test_create_rdp_asset_without_nodes_when_resolution_fails():
    mock_client = Mock(spec=JumpServerClient)
    mock_client.post.return_value = {"id": "asset-uuid-3", "name": "TEST-NO-NODE"}
    mock_client.get.return_value = []

    ops = JumpServerOperations(mock_client)
    res = ops.create_rdp_asset(
        name="TEST-NO-NODE",
        ip="192.168.1.103",
        port=33894,
        node_id=None,
        platform=5,
    )
    assert res["id"] == "asset-uuid-3"
    args, _ = mock_client.post.call_args
    # When no node resolved, 'nodes' key should NOT be included
    assert "nodes" not in args[1]
    assert args[1]["platform"] == 5


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
