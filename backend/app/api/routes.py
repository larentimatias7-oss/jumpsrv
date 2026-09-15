from __future__ import annotations
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from ..auth.basic_auth import verify_credentials
from ..config import (
    SessionLifecycleSettings,
    get_lifecycle_settings,
    save_lifecycle_settings,
)
from ..provisioning.provisioner import KioskProvisioner, KioskCreateRequest, KioskUpdateRequest
from ..services.category import CategoryService

router = APIRouter(dependencies=[Depends(verify_credentials)])
provisioner = KioskProvisioner()
category_service = CategoryService(provisioner.jms.client)


class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64)
    description: Optional[str] = None
    icon: Optional[str] = "📁"


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=64)
    description: Optional[str] = None
    icon: Optional[str] = None


@router.get("/settings", response_model=SessionLifecycleSettings)
def get_settings():
    return get_lifecycle_settings()


@router.put("/settings", response_model=SessionLifecycleSettings)
@router.post("/settings", response_model=SessionLifecycleSettings)
def update_settings(req: SessionLifecycleSettings):
    saved = save_lifecycle_settings(req)
    try:
        from ..main import dispatcher
        dispatcher.update_lifecycle_settings(
            disconnect_grace_seconds=saved.disconnect_grace_seconds,
            idle_timeout_seconds=saved.idle_timeout_seconds,
            max_session_lifetime_seconds=saved.max_session_lifetime_seconds,
            max_concurrent_sessions=saved.max_concurrent_sessions,
        )
    except Exception:
        pass
    return saved


@router.get("/kiosks", response_model=List[Dict[str, Any]])
def list_kiosks():
    return provisioner.list_all()


@router.post("/kiosks", status_code=status.HTTP_201_CREATED)
async def create_kiosk(req: KioskCreateRequest):
    try:
        res = provisioner.provision(req)
        # Register new port with dispatcher
        from ..main import dispatcher
        from ..provisioning.provisioner import detect_host_ip
        host_ip = detect_host_ip()
        await dispatcher.start_listening_for_kiosk(res["id"], host_ip, res["rdp_port"])
        return res
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/kiosks/{kiosk_id}/restart")
def restart_kiosk(kiosk_id: str):
    success = provisioner.restart(kiosk_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kiosk not found or failed to restart")
    return {"status": "restarted", "kiosk_id": kiosk_id}


@router.post("/kiosks/{kiosk_id}/stop")
@router.post("/kiosks/{kiosk_id}/terminate-session")
def stop_kiosk_session(kiosk_id: str):
    """Manually stop the container and set status to IDLE to immediately reclaim host RAM."""
    success = provisioner.stop_session(kiosk_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kiosk not found")
    return {"status": "stopped", "kiosk_id": kiosk_id}


@router.put("/kiosks/{kiosk_id}")
def update_kiosk(kiosk_id: str, req: KioskUpdateRequest):
    try:
        return provisioner.update(kiosk_id, req)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/kiosks/{kiosk_id}/test-url")
def test_kiosk_url(kiosk_id: str):
    try:
        return provisioner.test_connectivity(kiosk_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/kiosks/{kiosk_id}/clear-cache")
def clear_kiosk_cache(kiosk_id: str):
    success = provisioner.clear_cache(kiosk_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kiosk not found")
    return {"status": "cache_cleared", "kiosk_id": kiosk_id}


@router.delete("/kiosks/{kiosk_id}")
async def delete_kiosk(kiosk_id: str):
    # Retrieve port before deprovisioning
    from ..models.database import KioskModel
    with provisioner.db_factory() as session:
        k = session.query(KioskModel).get(kiosk_id)
        port = k.rdp_port if k else None

    success = provisioner.deprovision(kiosk_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kiosk not found")

    if port:
        from ..main import dispatcher
        await dispatcher.stop_listening(port)

    return {"status": "deleted", "kiosk_id": kiosk_id}


@router.post("/kiosks/reconcile-jms")
@router.post("/kiosk/reconcile-jms")
def reconcile_jumpserver_assets():
    """
    Garbage collection endpoint to reconcile and purge orphan JumpServer assets
    that no longer have an active kiosk record in kiosk-manager.
    """
    try:
        return provisioner.reconcile_with_jumpserver()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Category & JumpServer Node Management ---

@router.get("/categories", response_model=List[Dict[str, Any]])
def list_categories():
    with provisioner.db_factory() as session:
        return category_service.list_categories(session)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(req: CategoryCreateRequest):
    try:
        with provisioner.db_factory() as session:
            return category_service.create_category(
                session=session,
                name=req.name,
                description=req.description,
                icon=req.icon or "📁",
            )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/categories/{category_id}")
def get_category(category_id: str):
    with provisioner.db_factory() as session:
        cat = category_service.get_category_by_id(session, category_id)
        if not cat:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        return {
            "id": cat.id,
            "name": cat.name,
            "description": cat.description or "",
            "jms_node_id": cat.jms_node_id,
            "icon": cat.icon or "📁",
            "created_at": cat.created_at.isoformat() if cat.created_at else None,
            "updated_at": cat.updated_at.isoformat() if cat.updated_at else None,
        }


@router.put("/categories/{category_id}")
@router.patch("/categories/{category_id}")
def update_category(category_id: str, req: CategoryUpdateRequest):
    try:
        with provisioner.db_factory() as session:
            return category_service.update_category(
                session=session,
                category_id=category_id,
                name=req.name,
                description=req.description,
                icon=req.icon,
            )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/categories/{category_id}")
def delete_category(category_id: str):
    try:
        with provisioner.db_factory() as session:
            return category_service.delete_category(session, category_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/categories/sync-jms-nodes")
def sync_jms_nodes():
    try:
        with provisioner.db_factory() as session:
            return category_service.sync_jms_nodes(session)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
