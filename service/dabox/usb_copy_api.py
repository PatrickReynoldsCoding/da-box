"""Copy from USB on the box (TV UI). Starting a copy needs parent mode; the progress is for everyone."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dabox.models import Album, MediaSource, Show
from dabox.services import Services, get_services, require_box_client, require_parent_mode
from dabox.usb import UsbStick
from dabox.usb_copy import CopyProgress, SpaceCheck, StickItem, UsbStickTree, check_space, stick_item_for, stick_items, stick_tree

box_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])
parent_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client), Depends(require_parent_mode)])


class CopyRequest(BaseModel):
    stick_id: str
    item_ids: list[str]


def _stick_or_404(services: Services, stick_id: str) -> UsbStick:
    for stick in services.library.library.sticks:
        if stick.id == stick_id:
            return stick
    raise HTTPException(status_code=404, detail="That USB drive is not plugged in")


def _ticked(services: Services, request: CopyRequest) -> tuple[UsbStick, list[StickItem]]:
    stick = _stick_or_404(services, request.stick_id)
    by_id = {item.id: item for item in stick_items(stick, services.library.library, services.library.media_dir)}
    missing = [item_id for item_id in request.item_ids if item_id not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail=f"Not on the USB drive: {', '.join(missing)}")
    if not request.item_ids:
        raise HTTPException(status_code=422, detail="Tick something to copy")
    return stick, [by_id[item_id] for item_id in dict.fromkeys(request.item_ids)]


def _start(services: Services, stick: UsbStick, items: list[StickItem]) -> CopyProgress:
    if services.usb_copier.running():
        raise HTTPException(status_code=409, detail="A copy is running. Wait until it ends.")
    space = check_space(items, services.library.media_dir)
    if space.items == 0:
        raise HTTPException(status_code=409, detail="Everything you ticked is on the box already")
    if not space.fits:
        raise HTTPException(status_code=409, detail="There is not enough space on the box")
    return services.usb_copier.start(stick, items, services.rescan_library)


@parent_router.get("/usb/tree")
def usb_tree(services: Services = Depends(get_services)) -> list[UsbStickTree]:
    library = services.library.library
    return [stick_tree(stick, stick_items(stick, library, services.library.media_dir)) for stick in library.sticks]


@parent_router.post("/usb/check")
def usb_check(request: CopyRequest, services: Services = Depends(get_services)) -> SpaceCheck:
    _, items = _ticked(services, request)
    return check_space(items, services.library.media_dir)


@parent_router.post("/usb/copy")
def usb_copy(request: CopyRequest, services: Services = Depends(get_services)) -> CopyProgress:
    stick, items = _ticked(services, request)
    return _start(services, stick, items)


@box_router.get("/usb/copy")
def usb_copy_progress(services: Services = Depends(get_services)) -> CopyProgress:
    return services.usb_copier.progress()


@parent_router.post("/usb/copy/stop")
def usb_copy_stop(services: Services = Depends(get_services)) -> CopyProgress:
    services.usb_copier.stop()
    return services.usb_copier.progress()


@parent_router.post("/content/{item_id}/copy-to-box")
def copy_item_to_box(item_id: str, services: Services = Depends(get_services)) -> CopyProgress:
    """"Copy to the box" on one video, group, album or game. Runs as a copy job, so a big video does not block the TV."""
    item = services.library.find_show(item_id) or services.item_or_404(item_id)
    if item.source is not MediaSource.USB:
        raise HTTPException(status_code=409, detail="This item is already on the box")
    path = item.folder if isinstance(item, (Album, Show)) else item.path
    stick = next((stick for stick in services.library.library.sticks if path.is_relative_to(stick.path)), None)
    if stick is None:
        raise HTTPException(status_code=404, detail="That USB drive is not plugged in")
    return _start(services, stick, [stick_item_for(item, stick, services.library.library, services.library.media_dir)])
