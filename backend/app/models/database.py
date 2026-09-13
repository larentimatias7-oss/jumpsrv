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
    
    # Status: PENDING, RUNNING, STOPPED, FAILED, DEGRADED
    status = Column(String(32), default="PENDING", nullable=False)
    last_error = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class SystemSettingModel(Base):
    __tablename__ = "system_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


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
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
