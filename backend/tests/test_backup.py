import pytest
from unittest.mock import Mock, AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.models.database import Base, KioskModel, CategoryModel, SystemSettingModel
from app.services.backup_service import BackupService, BackupPayload
from app.provisioning.provisioner import KioskProvisioner


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


@pytest.fixture
def mock_provisioner(test_db):
    prov = Mock(spec=KioskProvisioner)
    prov.db_factory = test_db
    prov.jms = Mock()
    prov.jms.client = Mock()
    prov.jms.client.ensure_node.return_value = "node-uuid-1"
    prov._allocate_port.return_value = 33895
    return prov


def test_backup_export_structure(test_db, mock_provisioner):
    with test_db() as session:
        cat = CategoryModel(id="cat-1", name="SWITCHES ROSARIO", description="Switches", icon="🔌")
        kiosk = KioskModel(
            id="k-1",
            name="SWSRCORE01",
            device_type="network",
            target_url="http://192.168.1.1",
            target_ip="192.168.1.1",
            target_protocol="http",
            target_port=80,
            rdp_port=33891,
            rdp_username="kiosk_swsrcore01",
            container_name="kiosk-swsrcore01",
            volume_name="rdp_swsrcore01",
            category_name="SWITCHES ROSARIO",
            status="RUNNING",
        )
        setting = SystemSettingModel(key="disconnect_grace_seconds", value="45")
        session.add_all([cat, kiosk, setting])
        session.commit()

    service = BackupService(mock_provisioner)
    data = service.export_backup()

    assert data["version"] == "1.0"
    assert "exported_at" in data
    assert data["system"]["total_kiosks"] == 1
    assert data["system"]["total_categories"] == 1
    assert data["categories"][0]["name"] == "SWITCHES ROSARIO"
    assert data["kiosks"][0]["name"] == "SWSRCORE01"
    assert data["kiosks"][0]["jms_asset_name"] == "SWSRCORE01-WEB"
    assert data["settings"]["disconnect_grace_seconds"] == 45


@pytest.mark.asyncio
async def test_backup_import_clean_db_offline(test_db, mock_provisioner):
    service = BackupService(mock_provisioner)

    payload = {
        "version": "1.0",
        "categories": [
            {"name": "SERVERS INFRA", "description": "Infra servers", "icon": "🖥️"}
        ],
        "kiosks": [
            {
                "name": "ZABBIX",
                "device_type": "web",
                "target_url": "http://10.0.0.5:8080",
                "target_ip": "10.0.0.5",
                "target_protocol": "http",
                "target_port": 8080,
                "category_name": "SERVERS INFRA",
            }
        ],
        "settings": {
            "disconnect_grace_seconds": 60,
        },
    }

    res = await service.import_backup(
        payload_data=payload,
        conflict_strategy="skip",
        auto_provision_jms=False,
    )

    assert res["success"] is True
    assert res["categories_created"] == 1
    assert res["imported_kiosks"] == 1
    assert res["skipped_kiosks"] == 0

    with test_db() as session:
        cat = session.query(CategoryModel).filter(CategoryModel.name == "SERVERS INFRA").first()
        assert cat is not None
        assert cat.icon == "🖥️"

        k = session.query(KioskModel).filter(KioskModel.name == "ZABBIX").first()
        assert k is not None
        assert k.target_port == 8080
        assert k.rdp_port == 33895


@pytest.mark.asyncio
async def test_backup_import_conflict_skip(test_db, mock_provisioner):
    with test_db() as session:
        existing = KioskModel(
            id="k-1",
            name="CAMARA01",
            device_type="cctv",
            target_url="http://192.168.1.10",
            target_ip="192.168.1.10",
            rdp_port=33891,
            rdp_username="kiosk_camara01",
            container_name="kiosk-camara01",
            volume_name="rdp_camara01",
            status="RUNNING",
        )
        session.add(existing)
        session.commit()

    service = BackupService(mock_provisioner)

    payload = {
        "version": "1.0",
        "kiosks": [
            {
                "name": "CAMARA01",
                "device_type": "cctv",
                "target_url": "http://192.168.1.99",
            }
        ],
    }

    res = await service.import_backup(
        payload_data=payload,
        conflict_strategy="skip",
        auto_provision_jms=False,
    )

    assert res["imported_kiosks"] == 0
    assert res["skipped_kiosks"] == 1

    with test_db() as session:
        k = session.query(KioskModel).filter(KioskModel.name == "CAMARA01").first()
        assert k.target_url == "http://192.168.1.10"  # Not overwritten


@pytest.mark.asyncio
async def test_backup_import_conflict_update(test_db, mock_provisioner):
    with test_db() as session:
        existing = KioskModel(
            id="k-1",
            name="CAMARA01",
            device_type="cctv",
            target_url="http://192.168.1.10",
            target_ip="192.168.1.10",
            rdp_port=33891,
            rdp_username="kiosk_camara01",
            container_name="kiosk-camara01",
            volume_name="rdp_camara01",
            status="RUNNING",
        )
        session.add(existing)
        session.commit()

    service = BackupService(mock_provisioner)

    payload = {
        "version": "1.0",
        "kiosks": [
            {
                "name": "CAMARA01",
                "device_type": "cctv",
                "target_url": "http://192.168.1.99",
            }
        ],
    }

    res = await service.import_backup(
        payload_data=payload,
        conflict_strategy="update",
        auto_provision_jms=False,
    )

    assert res["updated_kiosks"] == 1
    mock_provisioner.update.assert_called_once()


@pytest.mark.asyncio
async def test_backup_import_with_auto_provision(test_db, mock_provisioner):
    mock_provisioner.provision.return_value = {
        "id": "k-new-1",
        "name": "CAMARA02",
        "rdp_port": 33896,
        "jms_asset_id": "jms-asset-2",
    }

    service = BackupService(mock_provisioner)

    payload = {
        "version": "1.0",
        "kiosks": [
            {
                "name": "CAMARA02",
                "device_type": "cctv",
                "target_url": "http://192.168.1.20",
            }
        ],
    }

    res = await service.import_backup(
        payload_data=payload,
        conflict_strategy="skip",
        auto_provision_jms=True,
    )

    assert res["imported_kiosks"] == 1
    assert res["success"] is True
    mock_provisioner.provision.assert_called_once()


def test_backup_api_endpoints():
    from app.main import app
    from app.auth.jms_auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin", "is_authenticated": True}
    client = TestClient(app)

    # 1. Test Export endpoint
    resp = client.get("/api/backup/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    data = resp.json()
    assert data["version"] == "1.0"
    assert "kiosks" in data
    assert "categories" in data

    # 2. Test Import endpoint
    import_payload = {
        "version": "1.0",
        "categories": [{"name": "TEST-CAT"}],
        "kiosks": [],
    }
    resp_import = client.post("/api/backup/import?auto_provision_jms=false", json=import_payload)
    assert resp_import.status_code == 200
    res_data = resp_import.json()
    assert "categories_created" in res_data

    app.dependency_overrides.clear()
