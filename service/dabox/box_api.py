"""API for the box UI. Only callers on the box itself (loopback) can use it."""

import io

import segno
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from dabox.models import SetupRequest
from dabox.services import Services, get_services, require_box_client
from dabox.system import NetworkStatus, WifiConnectResult, WifiNetwork, available_timezones
from dabox.views import (
    AlbumDetailView,
    AlbumView,
    FilmView,
    admin_urls,
    album_detail_view,
    album_view,
    film_view,
    visible_albums,
    visible_films,
)

ART_PREFIX = "/box/art"

router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])


class BoxStateView(BaseModel):
    setup_required: bool
    parent_mode: bool
    admin_urls: list[str]


class WifiConnectRequest(BaseModel):
    ssid: str
    password: str


def _require_setup_open(services: Services) -> None:
    if not services.box_state.setup_required():
        raise HTTPException(status_code=409, detail="Setup is already complete")


@router.get("/state")
def box_state(services: Services = Depends(get_services)) -> BoxStateView:
    ip_address = services.network.status().ip_address
    return BoxStateView(
        setup_required=services.box_state.setup_required(),
        parent_mode=services.box_state.parent_mode,
        admin_urls=admin_urls(services.admin_port, ip_address),
    )


class _Listing:
    """What the kid-side lists need: hidden items, metadata, parent mode and the USB setting."""

    def __init__(self, services: Services) -> None:
        self.hidden_ids = services.store.hidden_item_ids()
        self.metadata = services.metadata.store.all()
        self.show_hidden = services.box_state.parent_mode
        limits = services.box_state.limits()
        self.usb_allowed = limits.usb_playback if limits is not None else False


@router.get("/films")
def films(services: Services = Depends(get_services)) -> list[FilmView]:
    listing = _Listing(services)
    visible = visible_films(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    return [film_view(film, listing.hidden_ids, listing.metadata.get(film.id), ART_PREFIX) for film in visible]


@router.get("/music/albums")
def albums(services: Services = Depends(get_services)) -> list[AlbumView]:
    listing = _Listing(services)
    visible = visible_albums(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    return [album_view(album, listing.hidden_ids, listing.metadata.get(album.id), ART_PREFIX) for album in visible]


@router.get("/music/albums/{album_id}")
def album(album_id: str, services: Services = Depends(get_services)) -> AlbumDetailView:
    listing = _Listing(services)
    for candidate in visible_albums(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed):
        if candidate.id == album_id:
            return album_detail_view(candidate, listing.hidden_ids, listing.metadata.get(candidate.id), ART_PREFIX)
    raise HTTPException(status_code=404, detail="No such album")


@router.get("/art/{item_id}")
def art(item_id: str, services: Services = Depends(get_services)) -> FileResponse:
    return art_response(services, item_id)


def art_response(services: Services, item_id: str) -> FileResponse:
    """Art the parent picked or the box fetched comes first, then art next to the media."""
    item = services.item_or_404(item_id)
    metadata = services.metadata.store.get(item_id)
    if metadata is not None and metadata.art_file is not None:
        cached = services.metadata.store.art_dir / metadata.art_file
        if cached.is_file():
            return FileResponse(cached)
    if item.art_path is not None:
        return FileResponse(item.art_path)
    raise HTTPException(status_code=404, detail="No art for this item")


@router.post("/parent-mode/leave")
def leave_parent_mode(services: Services = Depends(get_services)) -> None:
    services.box_state.set_parent_mode(False)


@router.get("/admin-qr.png")
def admin_qr(services: Services = Depends(get_services)) -> Response:
    url = admin_urls(services.admin_port, services.network.status().ip_address)[0]
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="png", scale=10, border=2)
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.get("/setup/network")
def setup_network(services: Services = Depends(get_services)) -> NetworkStatus:
    _require_setup_open(services)
    return services.network.status()


@router.get("/setup/wifi")
def setup_wifi_scan(services: Services = Depends(get_services)) -> list[WifiNetwork]:
    _require_setup_open(services)
    return services.network.scan_wifi()


@router.post("/setup/wifi")
def setup_wifi_connect(request: WifiConnectRequest, services: Services = Depends(get_services)) -> WifiConnectResult:
    _require_setup_open(services)
    return services.network.connect_wifi(request.ssid, request.password)


@router.get("/setup/timezones")
def setup_timezones() -> list[str]:
    return available_timezones()


@router.post("/setup/complete")
def setup_complete(request: SetupRequest, services: Services = Depends(get_services)) -> BoxStateView:
    _require_setup_open(services)
    if request.timezone not in available_timezones():
        raise HTTPException(status_code=422, detail="Unknown time zone")
    services.box_state.complete_setup(request)
    return box_state(services)
