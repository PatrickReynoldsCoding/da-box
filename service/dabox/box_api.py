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


@router.get("/films")
def films(services: Services = Depends(get_services)) -> list[FilmView]:
    hidden_ids = services.store.hidden_item_ids()
    show_hidden = services.box_state.parent_mode
    return [film_view(film, hidden_ids, ART_PREFIX) for film in visible_films(services.library.library, hidden_ids, show_hidden)]


@router.get("/music/albums")
def albums(services: Services = Depends(get_services)) -> list[AlbumView]:
    hidden_ids = services.store.hidden_item_ids()
    show_hidden = services.box_state.parent_mode
    return [album_view(album, hidden_ids, ART_PREFIX) for album in visible_albums(services.library.library, hidden_ids, show_hidden)]


@router.get("/music/albums/{album_id}")
def album(album_id: str, services: Services = Depends(get_services)) -> AlbumDetailView:
    hidden_ids = services.store.hidden_item_ids()
    show_hidden = services.box_state.parent_mode
    for candidate in visible_albums(services.library.library, hidden_ids, show_hidden):
        if candidate.id == album_id:
            return album_detail_view(candidate, hidden_ids, ART_PREFIX)
    raise HTTPException(status_code=404, detail="No such album")


@router.get("/art/{item_id}")
def art(item_id: str, services: Services = Depends(get_services)) -> FileResponse:
    return art_response(services, item_id)


def art_response(services: Services, item_id: str) -> FileResponse:
    library = services.library.library
    for item in [*library.films, *library.albums]:
        if item.id == item_id and item.art_path is not None:
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
