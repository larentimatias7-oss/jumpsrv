from __future__ import annotations
import pytest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.jumpserver.client import JumpServerClient
from app.jumpserver.config import JumpServerSettings
from app.jumpserver.operations import JumpServerOperations
from app.models.database import Base, KioskModel, CategoryModel
from app.services.category import CategoryService
from app.provisioning.provisioner import KioskProvisioner, KioskCreateRequest


@pytest.fixture
def mock_jms_settings():
    return JumpServerSettings(
        base_url="http://mock-jumpserver:80",
        key_id="test-key-id",
        secret_value="test-secret-value",
        org_id="00000000-0000-0000-0000-000000000002",
        verify_ssl=False,
        default_node_name="SWITCHES ROSARIO",
    )


from sqlalchemy.pool import StaticPool


@pytest.fixture
def in_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_factory


# ==============================================================================
# 1. Tests for JumpServerClient Node Methods
# ==============================================================================

def test_list_nodes_handles_list_and_dict_responses(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)

    # 1. Direct list response
    with patch.object(client, "get", return_value=[{"id": "node-1", "value": "ROOT"}]) as mock_get:
        nodes = client.list_nodes()
        assert len(nodes) == 1
        assert nodes[0]["id"] == "node-1"
        mock_get.assert_called_with("/api/v1/assets/nodes/")

    # 2. Paginated results dict response
    with patch.object(client, "get", return_value={"results": [{"id": "node-2", "value": "DEFAULT"}]}):
        nodes = client.list_nodes()
        assert len(nodes) == 1
        assert nodes[0]["id"] == "node-2"


def test_get_node_by_name_case_insensitive(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)
    mock_nodes = [
        {"id": "uuid-default", "value": "DEFAULT", "name": "DEFAULT"},
        {"id": "uuid-switches", "value": "SWITCHES ROSARIO", "name": "Switches Rosario"},
        {"id": "uuid-servers", "value": "SERVERS INFRA", "name": "Servers Infra"},
    ]

    with patch.object(client, "list_nodes", return_value=mock_nodes):
        # Match by value
        node1 = client.get_node_by_name("switches rosario")
        assert node1 is not None
        assert node1["id"] == "uuid-switches"

        # Match by name
        node2 = client.get_node_by_name("SERVERS INFRA")
        assert node2 is not None
        assert node2["id"] == "uuid-servers"

        # Non-existent
        node3 = client.get_node_by_name("NON_EXISTENT")
        assert node3 is None


def test_ensure_node_resolves_existing_uuid(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)
    mock_nodes = [
        {"id": "8efe99ea-dee5-4ba0-9ad2-1978d91e8f65", "value": "SWITCHES ROSARIO"},
    ]

    with patch.object(client, "list_nodes", return_value=mock_nodes):
        with patch.object(client, "create_node") as mock_create:
            node_id = client.ensure_node("SWITCHES ROSARIO")
            assert node_id == "8efe99ea-dee5-4ba0-9ad2-1978d91e8f65"
            mock_create.assert_not_called()


def test_ensure_node_creates_dynamically_when_not_exists(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)
    mock_nodes = [
        {"id": "root-uuid", "value": "DEFAULT", "parent": None},
    ]

    new_node_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    with patch.object(client, "list_nodes", return_value=mock_nodes):
        with patch.object(
            client,
            "post",
            return_value={"id": new_node_uuid, "value": "SERVERS BACKUP", "parent": "root-uuid"},
        ) as mock_post:
            node_id = client.ensure_node("SERVERS BACKUP")
            assert node_id == new_node_uuid
            mock_post.assert_called_once()
            args, _ = mock_post.call_args
            assert args[0] == "/api/v1/assets/nodes/"
            assert args[1]["value"] == "SERVERS BACKUP"
            assert args[1]["parent"] == "root-uuid"


def test_delete_node_safe(mock_jms_settings):
    client = JumpServerClient(mock_jms_settings)
    with patch.object(client, "delete", return_value={}) as mock_del:
        assert client.delete_node("node-to-delete") is True
        mock_del.assert_called_with("/api/v1/assets/nodes/node-to-delete/")

    with patch.object(client, "delete", side_effect=Exception("Node has active assets")):
        # Should not raise exception, but return False with a warning
        assert client.delete_node("node-with-assets") is False


# ==============================================================================
# 2. Tests for Device Provisioning Payload containing `nodes: [target_uuid]`
# ==============================================================================

def test_provision_asset_injects_category_node_uuid(mock_jms_settings, in_memory_db, monkeypatch):
    monkeypatch.setenv("KIOSK_HOST_IP", "192.168.1.50")
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    target_node_uuid = "99999999-aaaa-bbbb-cccc-dddddddddddd"

    # ensure_node returns target node uuid
    mock_client.ensure_node.return_value = target_node_uuid
    mock_client.post.return_value = {"id": "asset-uuid-101", "name": "CORE-SW-01"}

    mock_docker = Mock()
    mock_docker.create_volume.return_value = "rdp_core_sw_01"
    mock_docker.get_container_status.return_value = {"status": "stopped", "health": "unknown"}

    jms_ops = JumpServerOperations(mock_client)
    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=mock_docker,
        jms_ops=jms_ops,
        host_ip="192.168.1.50",
    )

    req = KioskCreateRequest(
        name="CORE-SW-01",
        device_type="switch",
        target_ip="10.0.0.1",
        target_port=443,
        target_protocol="https",
        category_name="SWITCHES ROSARIO",
    )

    result = provisioner.provision(req)
    assert result["status"] == "RUNNING"
    assert result["name"] == "CORE-SW-01"

    # Verify that JumpServer API was called with nodes: [target_node_uuid]
    post_calls = mock_client.post.call_args_list
    asset_call = None
    for call in post_calls:
        if "/api/v1/assets/" in call[0][0]:
            asset_call = call
            break

    assert asset_call is not None
    endpoint, payload = asset_call[0][0], asset_call[0][1]
    assert "nodes" in payload
    assert payload["nodes"] == [target_node_uuid]
    assert payload["name"] == "CORE-SW-01-WEB"
    assert payload["address"] == "192.168.1.50"
    assert payload["protocols"] == [{"name": "rdp", "port": result["rdp_port"]}]

    # Check database persistence
    with in_memory_db() as session:
        k = session.query(KioskModel).filter(KioskModel.name == "CORE-SW-01").first()
        assert k is not None
        assert k.category_name == "SWITCHES ROSARIO"
        assert k.jms_node_name == "SWITCHES ROSARIO"
        assert k.jms_node_id == target_node_uuid


# ==============================================================================
# 3. Tests for CategoryService: Lifecycle, Reassignment, and JMS Node Sync
# ==============================================================================

def test_category_service_create_ensures_node(mock_jms_settings, in_memory_db):
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    mock_client.ensure_node.return_value = "node-uuid-infra"

    service = CategoryService(mock_client)
    with in_memory_db() as session:
        created = service.create_category(
            session=session,
            name="SERVERS INFRA",
            description="Infraestructura central",
            icon="🖥️",
        )
        assert created["name"] == "SERVERS INFRA"
        assert created["jms_node_id"] == "node-uuid-infra"
        mock_client.ensure_node.assert_called_with("SERVERS INFRA")

        # Verify in DB
        cat = session.query(CategoryModel).filter(CategoryModel.name == "SERVERS INFRA").first()
        assert cat is not None
        assert cat.jms_node_id == "node-uuid-infra"


def test_category_service_delete_reassigns_orphans_to_default_node(mock_jms_settings, in_memory_db):
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    mock_client.ensure_node.return_value = "default-node-uuid"
    mock_client.delete_node.return_value = True

    service = CategoryService(mock_client)
    with in_memory_db() as session:
        # Create category
        cat = CategoryModel(
            name="TEMPORARY CATEGORY",
            jms_node_id="temp-node-uuid",
        )
        session.add(cat)
        session.commit()
        session.refresh(cat)
        cat_id = cat.id

        # Create two associated kiosks
        k1 = KioskModel(
            name="KIOSK-1",
            device_type="switch",
            target_url="http://10.0.0.1",
            target_ip="10.0.0.1",
            rdp_port=33891,
            rdp_username="kiosk_1",
            container_name="kiosk-1",
            volume_name="vol-1",
            category_id=cat_id,
            category_name="TEMPORARY CATEGORY",
            jms_node_name="TEMPORARY CATEGORY",
            jms_node_id="temp-node-uuid",
        )
        k2 = KioskModel(
            name="KIOSK-2",
            device_type="switch",
            target_url="http://10.0.0.2",
            target_ip="10.0.0.2",
            rdp_port=33892,
            rdp_username="kiosk_2",
            container_name="kiosk-2",
            volume_name="vol-2",
            category_id=cat_id,
            category_name="TEMPORARY CATEGORY",
            jms_node_name="TEMPORARY CATEGORY",
            jms_node_id="temp-node-uuid",
        )
        session.add_all([k1, k2])
        session.commit()

        # Delete category with reassign_to_default=True
        res = service.delete_category(session, cat_id, reassign_to_default=True)
        assert res["status"] == "deleted"
        assert res["reassigned_kiosks"] == 2
        assert res["default_node"] == "SWITCHES ROSARIO"

        # Verify orphans reassigned to default
        updated_k1 = session.query(KioskModel).filter(KioskModel.name == "KIOSK-1").first()
        assert updated_k1.category_id is None
        assert updated_k1.category_name == "SWITCHES ROSARIO"
        assert updated_k1.jms_node_name == "SWITCHES ROSARIO"
        assert updated_k1.jms_node_id == "default-node-uuid"


def test_category_service_sync_jms_nodes(mock_jms_settings, in_memory_db):
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings

    # Remote nodes in JumpServer
    mock_client.list_nodes.return_value = [
        {"id": "root-id", "value": "DEFAULT"},
        {"id": "node-101", "value": "SWITCHES ROSARIO"},
        {"id": "node-102", "value": "SERVERS BACKUP"},
    ]
    mock_client.ensure_node.side_effect = lambda name: f"uuid-{name.lower()}"

    service = CategoryService(mock_client)
    with in_memory_db() as session:
        # Pre-populate one local category
        local_cat = CategoryModel(name="SECURITY CAMERAS", jms_node_id=None)
        session.add(local_cat)
        session.commit()

        sync_result = service.sync_jms_nodes(session)
        assert sync_result["status"] == "synchronized"
        assert sync_result["imported_from_jms"] == 2  # SWITCHES ROSARIO and SERVERS BACKUP imported

        # Verify imported categories exist locally
        sw = session.query(CategoryModel).filter(CategoryModel.name == "SWITCHES ROSARIO").first()
        assert sw is not None
        assert sw.jms_node_id == "node-101"

        sb = session.query(CategoryModel).filter(CategoryModel.name == "SERVERS BACKUP").first()
        assert sb is not None
        assert sb.jms_node_id == "node-102"

        # Verify local category was pushed/ensured in JumpServer
        sc = session.query(CategoryModel).filter(CategoryModel.name == "SECURITY CAMERAS").first()
        assert sc is not None
        assert sc.jms_node_id == "uuid-security cameras"


def test_category_api_routes(mock_jms_settings, in_memory_db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import routes

    routes.provisioner.db_factory = in_memory_db
    mock_client = Mock(spec=JumpServerClient)
    mock_client.config = mock_jms_settings
    mock_client.ensure_node.return_value = "api-node-uuid"
    mock_client.list_nodes.return_value = [{"id": "api-node-uuid", "value": "API TEST CATEGORY"}]
    mock_client.delete_node.return_value = True
    routes.category_service.jms_client = mock_client

    client = TestClient(app)
    auth = ("admin", "admin")

    # 1. Create Category
    resp = client.post("/api/categories", json={"name": "API TEST CATEGORY", "description": "Test Desc"}, auth=auth)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "API TEST CATEGORY"
    assert data["jms_node_id"] == "api-node-uuid"
    cat_id = data["id"]

    # 2. List Categories
    resp_list = client.get("/api/categories", auth=auth)
    assert resp_list.status_code == 200
    assert any(c["id"] == cat_id for c in resp_list.json())

    # 3. Get Category by ID
    resp_get = client.get(f"/api/categories/{cat_id}", auth=auth)
    assert resp_get.status_code == 200
    assert resp_get.json()["name"] == "API TEST CATEGORY"

    # 4. Sync JMS Nodes
    resp_sync = client.post("/api/categories/sync-jms-nodes", auth=auth)
    assert resp_sync.status_code == 200
    assert resp_sync.json()["status"] == "synchronized"

    # 5. Delete Category
    resp_del = client.delete(f"/api/categories/{cat_id}", auth=auth)
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"


def test_format_jms_asset_name_suffix():
    from app.provisioning.provisioner import format_jms_asset_name
    assert format_jms_asset_name("ZABBIX") == "ZABBIX-WEB"
    assert format_jms_asset_name("SWSRCORE01") == "SWSRCORE01-WEB"
    assert format_jms_asset_name("ZABBIX-WEB") == "ZABBIX-WEB"
    assert format_jms_asset_name("zabbix") == "ZABBIX-WEB"
    assert format_jms_asset_name("  core-switch-01  ") == "CORE-SWITCH-01-WEB"
    assert format_jms_asset_name("") == "GENERIC-WEB"


def test_reconcile_auto_aligns_web_suffix_without_purging(in_memory_db):
    from app.provisioning.provisioner import KioskProvisioner
    from app.models.database import KioskModel

    # Mock JumpServer Client
    mock_client = Mock(spec=JumpServerClient)
    # Existing assets in JumpServer without -WEB suffix
    mock_client.get.return_value = {
        "results": [
            {
                "id": "jms-zabbix-1",
                "name": "ZABBIX",
                "comment": "Managed by Kiosk-Manager | Device: ZABBIX",
                "tags": ["kiosk-manager", "ephemeral"],
            }
        ]
    }
    mock_client.patch.return_value = {"id": "jms-zabbix-1", "name": "ZABBIX-WEB"}

    mock_docker = Mock()
    ops = JumpServerOperations(mock_client)
    provisioner = KioskProvisioner(
        db_session_factory=in_memory_db,
        docker_runtime=mock_docker,
        jms_ops=ops,
    )

    # Insert active local kiosk named ZABBIX
    with in_memory_db() as session:
        k = KioskModel(
            id="local-kiosk-1",
            name="ZABBIX",
            device_type="web",
            target_url="http://10.0.0.5",
            target_ip="10.0.0.5",
            rdp_port=33892,
            rdp_username="kiosk_zabbix",
            container_name="kiosk-zabbix",
            volume_name="rdp_zabbix",
            jms_asset_id="jms-zabbix-1",
            status="RUNNING",
        )
        session.add(k)
        session.commit()

    reconcile_res = provisioner.reconcile_with_jumpserver()

    # Verify asset was auto-aligned with patch to ZABBIX-WEB
    mock_client.patch.assert_called_once_with(
        "/api/v1/assets/assets/jms-zabbix-1/",
        {"name": "ZABBIX-WEB"},
    )
    # Verify it was NOT purged
    assert reconcile_res["purged_count"] == 0
    mock_client.delete.assert_not_called()

