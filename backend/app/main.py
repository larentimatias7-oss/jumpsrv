from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import router as api_router
from .models.database import init_db

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
def startup_event():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "jumpserver-kiosk-manager"}
