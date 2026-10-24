"""API for the box UI. Only callers on the box itself (loopback) can use it."""

import io

import segno
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from dabox.maintenance import Appearance, load_appearance
from dabox.models import SetupRequest
from dabox.services import Services, get_services, require_box_client
from dabox.system import NetworkStatus, WifiConnectResult, WifiNetwork, available_timezones
from dabox.views import (
    AlbumDetailView,
    AlbumView,
    FilmView,
    GroupDetailView,
    VideoTileView,
    admin_urls,
    album_detail_view,
    album_view,
    film_view,
    group_detail_view,
    group_tile,
    video_tile,
    visible_albums,
    visible_films,
    visible_shows,
)
from dabox.names import natural_key

ART_PREFIX = "/box/art"
# Where Play starts in each group: {group id: index of the next video}.
_GROUP_RESUME_KEY = "group_resume"

router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])


class BoxStateView(BaseModel):
    setup_required: bool
    parent_mode: bool
    admin_urls: list[str]
    appearance: Appearance


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
        appearance=load_appearance(services.store),
    )


class Listing:
    """What the kid-side lists need: hidden items, metadata, parent mode and the USB setting."""

    def __init__(self, services: Services) -> None:
        self.hidden_ids = services.store.hidden_item_ids()
        self.metadata = services.metadata.store.all()
        self.show_hidden = services.box_state.parent_mode
        limits = services.box_state.limits()
        self.usb_allowed = limits.usb_playback if limits is not None else False


@router.get("/films")
def films(services: Services = Depends(get_services)) -> list[FilmView]:
    listing = Listing(services)
    visible = visible_films(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    return [
        film_view(film, listing.hidden_ids, listing.metadata.get(film.id), ART_PREFIX, services.durations.get(film.fingerprint))
        for film in visible
    ]


@router.get("/videos")
def videos(services: Services = Depends(get_services)) -> list[VideoTileView]:
    """Single videos and groups together, by name (DESIGN_CORRECTIONS_2.md, 2.3)."""
    listing = Listing(services)
    library = services.library.library
    tiles = [
        video_tile(film, listing.hidden_ids, listing.metadata.get(film.id), ART_PREFIX, services.durations.get(film.fingerprint))
        for film in visible_films(library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    ] + [
        group_tile(show, listing.hidden_ids, listing.metadata.get(show.id), ART_PREFIX)
        for show in visible_shows(library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    ]
    return sorted(tiles, key=lambda tile: natural_key(tile.title))


class ResumeRequest(BaseModel):
    # The video to start from next time.
    index: int


@router.get("/groups/{group_id}")
def group(group_id: str, services: Services = Depends(get_services)) -> GroupDetailView:
    listing = Listing(services)
    for show in visible_shows(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed):
        if show.id == group_id:
            resume = (services.store.get(_GROUP_RESUME_KEY) or {}).get(group_id, 0)
            return group_detail_view(show, listing.hidden_ids, listing.metadata.get(show.id), ART_PREFIX, services.durations.all(), resume)
    raise HTTPException(status_code=404, detail="No such group")


@router.post("/groups/{group_id}/resume")
def set_group_resume(group_id: str, body: ResumeRequest, services: Services = Depends(get_services)) -> None:
    """The UI says which video Play should start from: the one after a video that ended."""
    show = services.library.find_show(group_id)
    if show is None:
        raise HTTPException(status_code=404, detail="No such group")
    resume = services.store.get(_GROUP_RESUME_KEY) or {}
    resume[group_id] = body.index if 0 <= body.index < len(show.episodes) else 0
    services.store.put(_GROUP_RESUME_KEY, resume)


@router.get("/music/albums")
def albums(artist: str | None = None, services: Services = Depends(get_services)) -> list[AlbumView]:
    """All albums, or the albums of one artist."""
    listing = Listing(services)
    visible = visible_albums(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    views = [album_view(album, listing.hidden_ids, listing.metadata.get(album.id), ART_PREFIX) for album in visible]
    if artist is not None:
        views = [view for view in views if view.artist.casefold() == artist.casefold()]
    return views


@router.get("/music/albums/{album_id}")
def album(album_id: str, services: Services = Depends(get_services)) -> AlbumDetailView:
    listing = Listing(services)
    for candidate in visible_albums(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed):
        if candidate.id == album_id:
            return album_detail_view(candidate, listing.hidden_ids, listing.metadata.get(candidate.id), ART_PREFIX)
    raise HTTPException(status_code=404, detail="No such album")


@router.get("/art/{item_id}")
def art(item_id: str, services: Services = Depends(get_services)) -> FileResponse:
    return art_response(services, item_id)


def art_response(services: Services, item_id: str) -> FileResponse:
    """Art the parent picked or the box fetched comes first, then art next to the media."""
    item = services.library.find_show(item_id) or services.item_or_404(item_id)
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
def admin_qr(target: str | None = None, services: Services = Depends(get_services)) -> Response:
    """The admin app's address. `target=accounts` opens its key form (Settings on the TV)."""
    url = admin_urls(services.admin_port, services.network.status().ip_address)[0]
    if target == "accounts":
        url += "/#accounts"
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
