"""API for the PIN-locked admin web app."""

import secrets
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from dabox.auth import LockedOut, LoginSucceeded, NoPinSet, WrongPin
from dabox.box_api import art_response
from dabox.library import read_album_tags
from dabox.models import LimitSettings
from dabox.services import SESSION_COOKIE, Services, get_services, require_admin
from dabox.uploads import (
    UploadRejected,
    film_destination,
    film_poster_destination,
    music_destination,
    save_stream,
)
from dabox.views import AlbumView, FilmView, album_view, film_view

ART_PREFIX = "/api/admin/art"

public_router = APIRouter(prefix="/api/admin")
router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class LoginRequest(BaseModel):
    pin: str


class SessionView(BaseModel):
    logged_in: bool
    setup_required: bool


class StatusView(BaseModel):
    parent_mode: bool
    setup_required: bool
    timezone: str | None
    film_count: int
    album_count: int


class ParentModeRequest(BaseModel):
    enabled: bool


class HiddenRequest(BaseModel):
    hidden: bool


class ContentView(BaseModel):
    films: list[FilmView]
    albums: list[AlbumView]


class ChangePinRequest(BaseModel):
    current_pin: str
    new_pin: str = Field(pattern=r"^\d{4,8}$")


class UploadResult(BaseModel):
    saved: list[str]


@public_router.get("/session")
def session(request: Request, services: Services = Depends(get_services)) -> SessionView:
    logged_in = services.auth.is_session_valid(request.cookies.get(SESSION_COOKIE), datetime.now())
    return SessionView(logged_in=logged_in, setup_required=services.box_state.setup_required())


@public_router.post("/login")
def login(body: LoginRequest, response: Response, services: Services = Depends(get_services)) -> SessionView:
    result = services.auth.login(body.pin, datetime.now())
    match result:
        case LoginSucceeded(token=token):
            response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict")
            return SessionView(logged_in=True, setup_required=services.box_state.setup_required())
        case WrongPin(attempts_before_lockout=attempts):
            raise HTTPException(status_code=401, detail={"reason": "wrong_pin", "attempts_before_lockout": attempts})
        case LockedOut(until=until):
            raise HTTPException(status_code=423, detail={"reason": "locked_out", "until": until.isoformat()})
        case NoPinSet():
            raise HTTPException(status_code=409, detail={"reason": "setup_required"})


@public_router.post("/logout")
def logout(request: Request, response: Response, services: Services = Depends(get_services)) -> None:
    services.auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)


@router.get("/status")
def status(services: Services = Depends(get_services)) -> StatusView:
    library = services.library.library
    return StatusView(
        parent_mode=services.box_state.parent_mode,
        setup_required=services.box_state.setup_required(),
        timezone=services.box_state.timezone,
        film_count=len(library.films),
        album_count=len(library.albums),
    )


@router.post("/parent-mode")
def set_parent_mode(body: ParentModeRequest, services: Services = Depends(get_services)) -> StatusView:
    services.box_state.set_parent_mode(body.enabled)
    return status(services)


@router.get("/content")
def content(services: Services = Depends(get_services)) -> ContentView:
    hidden_ids = services.store.hidden_item_ids()
    library = services.library.library
    return ContentView(
        films=[film_view(film, hidden_ids, ART_PREFIX) for film in library.films],
        albums=[album_view(album, hidden_ids, ART_PREFIX) for album in library.albums],
    )


@router.get("/art/{item_id}")
def art(item_id: str, services: Services = Depends(get_services)) -> FileResponse:
    return art_response(services, item_id)


@router.post("/content/{item_id}/hidden")
def set_hidden(item_id: str, body: HiddenRequest, services: Services = Depends(get_services)) -> None:
    library = services.library.library
    known_ids = {item.id for item in [*library.films, *library.albums]}
    if item_id not in known_ids:
        raise HTTPException(status_code=404, detail="No such item")
    services.store.set_hidden(item_id, body.hidden)


@router.post("/rescan")
def rescan(services: Services = Depends(get_services)) -> ContentView:
    services.library.rescan()
    return content(services)


def _reject_existing(destination: Path) -> None:
    if destination.exists():
        raise HTTPException(status_code=409, detail=f"'{destination.name}' is already on the box")


@router.post("/upload/film")
def upload_film(
    title: str = Form(...),
    year: int | None = Form(None),
    video: UploadFile = File(...),
    poster: UploadFile | None = File(None),
    services: Services = Depends(get_services),
) -> UploadResult:
    media_dir = services.library.media_dir
    try:
        video_destination = film_destination(media_dir, title, year, video.filename or "")
        poster_destination = (
            film_poster_destination(media_dir, title, year, poster.filename or "") if poster and poster.filename else None
        )
    except UploadRejected as rejection:
        raise HTTPException(status_code=422, detail=str(rejection)) from rejection

    _reject_existing(video_destination)
    save_stream(video.file, video_destination)
    saved = [video_destination.name]
    if poster_destination is not None and poster is not None:
        save_stream(poster.file, poster_destination)
        saved.append(poster_destination.name)

    services.library.rescan()
    return UploadResult(saved=saved)


@router.post("/upload/music")
def upload_music(
    files: list[UploadFile] = File(...),
    artist: str = Form(""),
    album: str = Form(""),
    services: Services = Depends(get_services),
) -> UploadResult:
    media_dir = services.library.media_dir
    services.incoming_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for upload in files:
        file_name = upload.filename or ""
        # Save first, so the file's own tags can decide the artist and album folders.
        incoming_path = services.incoming_dir / f"{secrets.token_hex(8)}{Path(file_name).suffix.lower()}"
        save_stream(upload.file, incoming_path)
        try:
            tag_artist, tag_album = read_album_tags(incoming_path)
            destination = music_destination(media_dir, artist or tag_artist or "", album or tag_album or "", file_name)
            _reject_existing(destination)
        except UploadRejected as rejection:
            incoming_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(rejection)) from rejection
        except HTTPException:
            incoming_path.unlink(missing_ok=True)
            raise
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(incoming_path, destination)
        saved.append(str(destination.relative_to(media_dir)))

    services.library.rescan()
    return UploadResult(saved=saved)


@router.get("/settings")
def get_settings(services: Services = Depends(get_services)) -> LimitSettings:
    limits = services.box_state.limits()
    if limits is None:
        raise HTTPException(status_code=409, detail="Setup is not complete")
    return limits


@router.put("/settings")
def put_settings(limits: LimitSettings, services: Services = Depends(get_services)) -> LimitSettings:
    services.box_state.save_limits(limits)
    return limits


@router.post("/pin")
def change_pin(body: ChangePinRequest, services: Services = Depends(get_services)) -> JSONResponse:
    if not services.auth.check_pin(body.current_pin):
        raise HTTPException(status_code=403, detail="The current PIN is wrong")
    services.auth.set_pin(body.new_pin)
    return JSONResponse({"changed": True})


@router.post("/setup/rerun")
def rerun_setup(services: Services = Depends(get_services)) -> StatusView:
    services.box_state.request_setup_again()
    return status(services)
