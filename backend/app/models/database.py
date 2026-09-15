import os
import datetime
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class KioskModel(Base):
    __tablename__ = "kiosks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(64), unique=True, nullable=False, index=True)
    device_type = Column(String(32), nullable=False)
    target_url = Column(String(255), nullable=False)
    target_ip = Column(String(64), nullable=False)
    target_protocol = Column(String(10), default="http")
    target_port = Column(Integer, default=80)
    
    # RDP allocation
    rdp_port = Column(Integer, unique=True, nullable=False)
    rdp_username = Column(String(64), nullable=False)
    
    # Container & volume identifiers
    container_name = Column(String(128), unique=True, nullable=False)
    volume_name = Column(String(128), unique=True, nullable=False)
    
    # JumpServer linkage
    jms_asset_id = Column(String(64), nullable=True)
    jms_account_id = Column(String(64), nullable=True)
    jms_permission_id = Column(String(64), nullable=True)
    jms_node_name = Column(String(128), nullable=True)
    jms_node_id = Column(String(64), nullable=True)
    category_id = Column(String(36), nullable=True)
    category_name = Column(String(64), nullable=True)
    
    # Status: PENDING, RUNNING, STOPPED, FAILED, DEGRADED
    status = Column(String(32), default="PENDING", nullable=False)
    last_error = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class CategoryModel(Base):
    __tablename__ = "categories"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    jms_node_id = Column(String(64), nullable=True)
    icon = Column(String(32), default="📁")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class SystemSettingModel(Base):
    __tablename__ = "system_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


import logging
from sqlalchemy import inspect, text

logger = logging.getLogger("kiosk.database.migration")


def run_auto_migrations(engine) -> None:
    """
    Safely and idempotently migrates SQLite database schema.
    Ensures that any new tables exist and that existing tables have
    all required columns added without modifying or deleting pre-existing data.
    """
    # 1. Create any missing tables (e.g. categories, system_settings)
    Base.metadata.create_all(bind=engine)

    # 2. Inspect kiosks table and append missing columns
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "kiosks" in table_names:
        existing_cols = {col["name"] for col in inspector.get_columns("kiosks")}

        # Required columns for JumpServer node and category integration
        required_cols = [
            ("jms_node_id", "VARCHAR(64)"),
            ("jms_node_name", "VARCHAR(128)"),
            ("category_id", "VARCHAR(36)"),
            ("category_name", "VARCHAR(64)"),
        ]

        with engine.begin() as conn:
            for col_name, col_type in required_cols:
                if col_name not in existing_cols:
                    logger.info("Auto-migrating kiosks table: adding column %s (%s)", col_name, col_type)
                    conn.execute(text(f"ALTER TABLE kiosks ADD COLUMN {col_name} {col_type};"))


def init_db(db_url: str = None):
    if not db_url:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            if os.path.exists("/app/data"):
                db_url = "sqlite:////app/data/kiosk.db"
            else:
                db_url = "sqlite:///./kiosk.db"

    if "sqlite:///" in db_url and not db_url.startswith("sqlite:///:memory:"):
        path_part = db_url.replace("sqlite:///", "")
        parent = os.path.dirname(path_part)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception:
                pass
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )
    # Enable WAL mode for SQLite
    if "sqlite" in db_url:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")

    # Run safe and idempotent schema auto-migrations
    run_auto_migrations(engine)

    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
