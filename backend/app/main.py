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


async def auto_reconcile_loop():
    """Periodic background task that purges orphan JumpServer assets."""
    from .api.routes import provisioner
    import asyncio
    interval_hours = float(os.getenv("JMS_RECONCILE_INTERVAL_HOURS", "12"))
    if interval_hours <= 0:
        logger.info("Auto-reconciliation background task is disabled (interval <= 0)")
        return
    interval_seconds = interval_hours * 3600
    logger.info("Starting auto-reconciliation background task (interval: %.1fh)", interval_hours)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            logger.info("Executing scheduled JumpServer assets reconciliation...")
            res = provisioner.reconcile_with_jumpserver()
            logger.info("Auto-reconciliation complete: %s orphans purged", res.get("purged_count", 0))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Error in auto-reconciliation background task: %s", e)


@app.on_event("startup")
async def startup_event():
    import asyncio
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
        max_concurrent_sessions=settings.max_concurrent_sessions,
    )

    with db_factory() as session:
        kiosks = session.query(KioskModel).all()
        for k in kiosks:
            if k.rdp_port:
                await dispatcher.start_listening_for_kiosk(k.id, host_ip, k.rdp_port)

    # Launch periodic orphan garbage collection
    asyncio.create_task(auto_reconcile_loop())


@app.get("/health")
def health():
    return {"status": "ok", "service": "jumpserver-kiosk-manager"}
