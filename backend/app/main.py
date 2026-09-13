import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import router as api_router
from .dispatcher.service import KioskDispatcher
from .models.database import init_db, KioskModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("kiosk.main")

dispatcher = KioskDispatcher()

app = FastAPI(
    title="JumpServer Kiosk Manager API",
    version="1.0.0",
    description="Automated RDP kiosk provisioning for JumpServer CE",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    from .provisioning.provisioner import detect_host_ip
    from .config import get_lifecycle_settings
    db_factory = init_db()
    host_ip = detect_host_ip()

    # Apply persisted session lifecycle & RAM conservation settings
    settings = get_lifecycle_settings(db_factory)
    dispatcher.update_lifecycle_settings(
        disconnect_grace_seconds=settings.disconnect_grace_seconds,
        idle_timeout_seconds=settings.idle_timeout_seconds,
        max_session_lifetime_seconds=settings.max_session_lifetime_seconds,
    )

    with db_factory() as session:
        kiosks = session.query(KioskModel).all()
        for k in kiosks:
            if k.rdp_port:
                await dispatcher.start_listening_for_kiosk(k.id, host_ip, k.rdp_port)


@app.get("/health")
def health():
    return {"status": "ok", "service": "jumpserver-kiosk-manager"}
