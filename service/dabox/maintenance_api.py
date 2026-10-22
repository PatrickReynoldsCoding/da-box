"""Admin routes for appearance, backup and restore, and system updates."""

import subprocess
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

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
