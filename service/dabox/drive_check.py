"""The USB drive check: for each drive, whether it is mounted (or why not), what the box found
on it, and what it skipped (DESIGN_CORRECTIONS_2.md, part 5). On the TV and in the admin app."""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dabox.models import Library, ScanReport
from dabox.services import Services, get_services, require_admin, require_box_client
from dabox.systems import SYSTEMS, find_core
from dabox.usb import UsbDrive

box_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class DriveCheckView(BaseModel):
    drive: UsbDrive
    # None until the drive is mounted and read.
    report: ScanReport | None
    # Games found for systems that have no emulator (core) on the box.
    games_without_core: int
    # Items on this drive the parent hid.
    hidden: int


def _on_stick(path: Path, stick_path: Path) -> bool:
    return path == stick_path or stick_path in path.parents


def drive_checks(services: Services) -> list[DriveCheckView]:
    library: Library = services.library.library
    hidden_ids = services.store.hidden_item_ids()
    core_dirs = list(services.core_dirs)
    checks: list[DriveCheckView] = []
    for drive in services.usb.drives():
        stick = next((stick for stick in library.sticks if stick.id == drive.id), None)
        if stick is None:
            checks.append(DriveCheckView(drive=drive, report=None, games_without_core=0, hidden=0))
            continue
        games = [game for game in library.games if _on_stick(game.path, stick.path)]
        items = [
            *(film.id for film in library.films if _on_stick(film.path, stick.path)),
            *(show.id for show in library.shows if _on_stick(show.folder, stick.path)),
            *(album.id for album in library.albums if _on_stick(album.folder, stick.path)),
            *(game.id for game in games),
        ]
        checks.append(DriveCheckView(
            drive=drive,
            report=library.reports.get(stick.id),
            games_without_core=sum(1 for game in games if find_core(SYSTEMS[game.system], core_dirs) is None),
            hidden=sum(1 for item_id in items if item_id in hidden_ids),
        ))
    return checks


@box_router.get("/usb/drives")
def box_drive_checks(services: Services = Depends(get_services)) -> list[DriveCheckView]:
    return drive_checks(services)


@admin_router.get("/usb/drives")
def admin_drive_checks(services: Services = Depends(get_services)) -> list[DriveCheckView]:
    return drive_checks(services)
