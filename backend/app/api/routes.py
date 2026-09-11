from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from ..auth.basic_auth import verify_credentials
from ..provisioning.provisioner import KioskProvisioner, KioskCreateRequest

router = APIRouter(dependencies=[Depends(verify_credentials)])
provisioner = KioskProvisioner()


@router.get("/kiosks", response_model=List[Dict[str, Any]])
def list_kiosks():
    return provisioner.list_all()


@router.post("/kiosks", status_code=status.HTTP_201_CREATED)
def create_kiosk(req: KioskCreateRequest):
    try:
        res = provisioner.provision(req)
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


@router.delete("/kiosks/{kiosk_id}")
def delete_kiosk(kiosk_id: str):
    success = provisioner.deprovision(kiosk_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kiosk not found")
    return {"status": "deleted", "kiosk_id": kiosk_id}
