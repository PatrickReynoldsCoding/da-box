"""Limits and games routes: the box UI asks before it plays; the parent sees today and gives extra time."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dabox.activity import ActivityEntry, DayTotals, day_totals
from dabox.limits import LimitsStatus
from dabox.models import Game, MediaSource
from dabox.services import Services, get_services, require_admin, require_box_client
from dabox.systems import SYSTEMS, find_core

box_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class VideoRequest(BaseModel):
    # How long the video (or what is left of the programme) will play.
    seconds: float = Field(gt=0)


class DecisionView(BaseModel):
    allowed: bool
    reason: str | None


class GameView(BaseModel):
    id: str
    title: str
    system: str
    system_name: str
    art_url: str | None
    path: str
    core: str
    # Saves are kept by the game file's fingerprint.
    save_key: str
    hidden: bool
    source: MediaSource
    stick_label: str | None


class ActivityView(BaseModel):
    totals: list[DayTotals]
    entries: list[ActivityEntry]


class ExtraTimeRequest(BaseModel):
    quota_minutes: int = Field(default=0, ge=0, le=240)
    game_minutes: int = Field(default=0, ge=0, le=240)


def game_view(game: Game, services: Services, hidden_ids: set[str], art_prefix: str, has_metadata_art: bool) -> GameView | None:
    system = SYSTEMS[game.system]
    core = find_core(system, list(services.core_dirs))
    if core is None:
        return None
    return GameView(
        id=game.id,
        title=game.title,
        system=system.key,
        system_name=system.name,
        art_url=f"{art_prefix}/{game.id}" if game.art_path or has_metadata_art else None,
        path=str(game.path),
        core=str(core),
        save_key=game.fingerprint,
        hidden=game.id in hidden_ids,
        source=game.source,
        stick_label=game.stick_label,
    )


def game_views(services: Services, art_prefix: str, kid_view: bool) -> list[GameView]:
    hidden_ids = services.store.hidden_item_ids()
    metadata = services.metadata.store.all()
    limits = services.box_state.limits()
    show_all = not kid_view or services.box_state.parent_mode
    usb_allowed = limits.usb_games if limits is not None else False
    views: list[GameView] = []
    for game in services.library.library.games:
        if not show_all and (game.id in hidden_ids or (game.source is MediaSource.USB and not usb_allowed)):
            continue
        record = metadata.get(game.id)
        view = game_view(game, services, hidden_ids, art_prefix, record is not None and record.art_file is not None)
        if view is not None:
            views.append(view)
    return views


@box_router.get("/limits")
def box_limits(services: Services = Depends(get_services)) -> LimitsStatus:
    return services.limits.status()


@box_router.post("/limits/video")
def approve_video(body: VideoRequest, services: Services = Depends(get_services)) -> DecisionView:
    decision = services.limits.approve_video(body.seconds)
    return DecisionView(allowed=decision.allowed, reason=decision.reason)


@box_router.post("/limits/game")
def approve_game(services: Services = Depends(get_services)) -> DecisionView:
    decision = services.limits.approve_game()
    return DecisionView(allowed=decision.allowed, reason=decision.reason)


@box_router.get("/games")
def box_games(services: Services = Depends(get_services)) -> list[GameView]:
    return game_views(services, "/box/art", kid_view=True)


@admin_router.get("/today")
def today(services: Services = Depends(get_services)) -> LimitsStatus:
    return services.limits.status()


@admin_router.post("/extra-time")
def extra_time(body: ExtraTimeRequest, services: Services = Depends(get_services)) -> LimitsStatus:
    if body.quota_minutes == 0 and body.game_minutes == 0:
        raise HTTPException(status_code=422, detail="Give some minutes")
    return services.limits.add_extra_time(body.quota_minutes, body.game_minutes)


@admin_router.get("/games")
def admin_games(services: Services = Depends(get_services)) -> list[GameView]:
    return game_views(services, "/api/admin/art", kid_view=False)


@admin_router.get("/activity")
def activity(services: Services = Depends(get_services)) -> ActivityView:
    entries = services.limits.activity.recent(services.guide.now())
    return ActivityView(totals=day_totals(entries), entries=entries)
