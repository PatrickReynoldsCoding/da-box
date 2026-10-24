"""Updating da-box itself: from the admin app (PIN) and from the TV (parent mode only)."""

import subprocess

from fastapi import APIRouter, Depends, HTTPException

from dabox.services import Services, get_services, require_admin, require_box_client, require_parent_mode
from dabox.software_update import SoftwareStatus

admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
parent_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client), Depends(require_parent_mode)])


@admin_router.get("/software")
@parent_router.get("/software")
def software_status(services: Services = Depends(get_services)) -> SoftwareStatus:
    return services.software.status()


@admin_router.post("/software/check")
@parent_router.post("/software/check")
def check_software(services: Services = Depends(get_services)) -> SoftwareStatus:
    return services.software.status(check=True)


@admin_router.post("/software/update")
@parent_router.post("/software/update")
def start_software_update(services: Services = Depends(get_services)) -> SoftwareStatus:
    status = services.software.status()
    if status.running:
        raise HTTPException(status_code=409, detail="An update is running. Wait until it ends.")
    if not status.available:
        raise HTTPException(status_code=409, detail="da-box is up to date.")
    try:
        return services.software.start()
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=500, detail=f"The update could not start: {error}") from error
