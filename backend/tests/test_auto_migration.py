from __future__ import annotations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base, KioskModel, CategoryModel, SystemSettingModel, run_auto_migrations


def create_legacy_database():
    """Create an in-memory SQLite database simulating an older production schema without node/category columns."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE kiosks (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(64) UNIQUE NOT NULL,
                device_type VARCHAR(32) NOT NULL,
                target_url VARCHAR(255) NOT NULL,
                target_ip VARCHAR(64) NOT NULL,
                target_protocol VARCHAR(10) DEFAULT 'http',
                target_port INTEGER DEFAULT 80,
                rdp_port INTEGER UNIQUE NOT NULL,
                rdp_username VARCHAR(64) NOT NULL,
                container_name VARCHAR(128) UNIQUE NOT NULL,
                volume_name VARCHAR(128) UNIQUE NOT NULL,
                jms_asset_id VARCHAR(64),
                jms_account_id VARCHAR(64),
                jms_permission_id VARCHAR(64),
                status VARCHAR(32) DEFAULT 'IDLE' NOT NULL,
                last_error TEXT,
                created_at DATETIME,
                updated_at DATETIME
            );
        """))

        # Insert a simulated historical record that must be preserved
        conn.execute(text("""
            INSERT INTO kiosks (
                id, name, device_type, target_url, target_ip, target_protocol, target_port,
                rdp_port, rdp_username, container_name, volume_name, status
            ) VALUES (
                'hist-kiosk-uuid-1', 'SWITCH-ROS-PROD', 'cisco_ios', 'http://10.20.30.40', '10.20.30.40',
                'http', 80, 33892, 'kiosk_switch_ros', 'kiosk-switch-ros', 'rdp_switch_ros', 'IDLE'
            );
        """))
    return engine


def test_auto_migration_adds_missing_columns():
    engine = create_legacy_database()

    # Pre-check: Verify new columns do NOT exist initially
    inspector = inspect(engine)
    pre_cols = {col["name"] for col in inspector.get_columns("kiosks")}
    assert "jms_node_id" not in pre_cols
    assert "jms_node_name" not in pre_cols
    assert "category_id" not in pre_cols
    assert "category_name" not in pre_cols

    # Querying KioskModel before migration would fail with OperationalError
    Session = sessionmaker(bind=engine)
    session = Session()
    with pytest.raises(Exception) as exc_info:
        session.query(KioskModel).all()
    assert "no such column: kiosks." in str(exc_info.value)
    session.close()

    # Execute safe auto-migration
    run_auto_migrations(engine)

    # Post-check: Verify all 4 columns were added
    inspector = inspect(engine)
    post_cols = {col["name"] for col in inspector.get_columns("kiosks")}
    assert "jms_node_id" in post_cols
    assert "jms_node_name" in post_cols
    assert "category_id" in post_cols
    assert "category_name" in post_cols

    # Verify categories and system_settings tables were created
    table_names = inspector.get_table_names()
    assert "categories" in table_names
    assert "system_settings" in table_names

    # Verify historical data is intact
    session = Session()
    kiosks = session.query(KioskModel).all()
    assert len(kiosks) == 1
    k = kiosks[0]
    assert k.id == "hist-kiosk-uuid-1"
    assert k.name == "SWITCH-ROS-PROD"
    assert k.rdp_port == 33892
    assert k.jms_node_id is None
    assert k.jms_node_name is None
    assert k.category_id is None
    assert k.category_name is None
    session.close()


def test_auto_migration_is_idempotent():
    engine = create_legacy_database()

    # First migration run
    run_auto_migrations(engine)

    # Second migration run should be completely safe and idempotent
    run_auto_migrations(engine)

    # Third run directly
    run_auto_migrations(engine)

    # Query should continue working normally
    Session = sessionmaker(bind=engine)
    session = Session()
    k = session.query(KioskModel).filter_by(name="SWITCH-ROS-PROD").first()
    assert k is not None
    assert k.id == "hist-kiosk-uuid-1"
    session.close()
