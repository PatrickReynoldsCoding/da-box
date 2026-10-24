"""Admin routes for appearance, backup and restore, system updates, and removing da-box."""

import subprocess
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from dabox.auth import LockedOut, LoginSucceeded, WrongPin
from dabox.maintenance import (
    Appearance,
    RestoreRejected,
    UpdateStatus,
    load_appearance,
    make_backup,
    restore_backup,
    save_appearance,
)
from dabox.services import Services, get_services, require_admin

admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@admin_router.get("/appearance")
def get_appearance(services: Services = Depends(get_services)) -> Appearance:
    return load_appearance(services.store)


@admin_router.put("/appearance")
def put_appearance(appearance: Appearance, services: Services = Depends(get_services)) -> Appearance:
    save_appearance(services.store, appearance)
    return appearance


@admin_router.get("/backup")
def backup(services: Services = Depends(get_services)) -> Response:
    data = make_backup(services.store, services.metadata.store.art_dir)
    file_name = f"dabox-backup-{date.today().isoformat()}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{file_name}"'})


@admin_router.post("/restore")
def restore(backup_file: UploadFile = File(...), services: Services = Depends(get_services)) -> dict:
    try:
        restore_backup(backup_file.file.read(), services.store, services.metadata.store.art_dir)
    except RestoreRejected as rejection:
        raise HTTPException(status_code=422, detail=str(rejection)) from rejection
    services.durations.reload()
    services.rescan_library()
    return {"restored": True}


@admin_router.get("/system-update")
def update_status(services: Services = Depends(get_services)) -> UpdateStatus:
    return services.updater.status()


@admin_router.post("/system-update")
def start_update(services: Services = Depends(get_services)) -> UpdateStatus:
    try:
        services.updater.start()
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=500, detail=f"The update could not start: {error}") from error
    return services.updater.status()


# The word the parent types to confirm. The PIN is asked again as well.
REMOVE_WORD = "REMOVE"


class RemoveRequest(BaseModel):
    pin: str
    confirm: str
    # Also delete the media, settings and the kid and tvbox users.
    purge: bool = False


@admin_router.post("/remove-dabox")
def remove_dabox(body: RemoveRequest, services: Services = Depends(get_services)) -> dict:
    if body.confirm.strip() != REMOVE_WORD:
        raise HTTPException(status_code=422, detail=f"Type {REMOVE_WORD} to confirm.")
    # The same check as logging in, so wrong PINs here count towards the lockout too.
    match services.auth.login(body.pin, datetime.now()):
        case LoginSucceeded(token=token):
            services.auth.logout(token)
        case WrongPin():
            raise HTTPException(status_code=403, detail="Wrong PIN.")
        case LockedOut(until=until):
            raise HTTPException(status_code=423, detail=f"Too many wrong PINs. Try again after {until:%H:%M}.")
        case _:
            raise HTTPException(status_code=409, detail="The box has no PIN yet.")
    try:
        services.remover.start(body.purge)
    except (OSError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=500, detail=f"Could not start removing da-box: {error}") from error
    return {"removing": True, "purge": body.purge}
