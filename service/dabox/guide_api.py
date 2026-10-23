"""TV guide and channel routes: read-only for the box UI, editable in the admin app."""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dabox.channels import (
    Channel,
    ChannelInput,
    ChannelKind,
    GuideError,
    PoolKind,
    Slot,
    programmes_for,
    slot_at,
    week_start_for,
)
from dabox.channels import next_slot as find_next_slot
from dabox.models import MediaSource, Weekday
from dabox.services import Services, get_services, require_admin, require_box_client

box_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

WEEKDAYS = list(Weekday)


class SlotView(BaseModel):
    id: str
    channel_id: str
    start: datetime
    end: datetime
    title: str | None
    subtitle: str | None
    art_url: str | None
    ref: str | None
    edited: bool


class ChannelDayView(BaseModel):
    id: str
    number: int
    name: str
    kind: ChannelKind
    slots: list[SlotView]


class TimeWindow(BaseModel):
    start: datetime
    end: datetime


class GuideDayView(BaseModel):
    day: date
    now: datetime
    channels: list[ChannelDayView]
    game_windows: list[TimeWindow]
    bedtime: datetime | None


class GuideWeekView(BaseModel):
    week_start: date
    today: date
    channel: Channel
    days: list[date]
    slots: list[SlotView]


class ShuffleRequest(BaseModel):
    channel_id: str
    day: date
    whole_week: bool


class NowPlayingView(BaseModel):
    channel_id: str
    channel_name: str
    kind: ChannelKind
    now: datetime
    slot: SlotView | None
    path: str | None
    offset_seconds: float | None
    next: SlotView | None


class SlotPlacement(BaseModel):
    channel_id: str
    start: datetime
    ref: str
    replace_slot_id: str | None = None


class SlotTarget(BaseModel):
    start: datetime


class PoolItemView(BaseModel):
    kind: PoolKind
    id: str
    title: str
    detail: str


class ProgrammeChoice(BaseModel):
    ref: str
    title: str
    subtitle: str | None
    minutes: int


def slot_view(slot: Slot, art_prefix: str) -> SlotView:
    programme = slot.programme
    return SlotView(
        id=slot.id,
        channel_id=slot.channel_id,
        start=slot.start,
        end=slot.end,
        title=programme.title if programme else None,
        subtitle=programme.subtitle if programme else None,
        art_url=f"{art_prefix}/{programme.art_item_id}" if programme and programme.art_item_id else None,
        ref=programme.ref if programme else None,
        edited=slot.edited,
    )


def _day_bounds(services: Services, day: date) -> tuple[datetime, datetime]:
    zone = services.guide.zone()
    start = datetime.combine(day, time(0), tzinfo=zone)
    return start, start + timedelta(days=1)


def _guide_day(services: Services, day: date | None, art_prefix: str, include_gaps: bool, kid_view: bool) -> GuideDayView:
    guide = services.guide
    now = guide.now().replace(microsecond=0)
    day = day or now.date()
    day_start, day_end = _day_bounds(services, day)
    guide.ensure_week(day_start)
    slots = guide.slots_between(day_start, day_end)
    hidden_ids = services.store.hidden_item_ids() if kid_view and not services.box_state.parent_mode else set()

    channels: list[ChannelDayView] = []
    for channel in guide.channels():
        views = [
            slot_view(slot, art_prefix)
            for slot in slots
            if slot.channel_id == channel.id
            and (slot.programme is not None or include_gaps)
            and not (slot.programme and slot.programme.hide_id in hidden_ids)
        ]
        channels.append(ChannelDayView(id=channel.id, number=channel.number, name=channel.name, kind=channel.kind, slots=views))

    game_windows: list[TimeWindow] = []
    bedtime: datetime | None = None
    limits = services.box_state.limits()
    if limits is not None:
        weekday = WEEKDAYS[day.weekday()]
        window = limits.game_windows.get(weekday)
        if window is not None:
            game_windows.append(TimeWindow(start=datetime.combine(day, window.start, tzinfo=day_start.tzinfo),
                                           end=datetime.combine(day, window.end, tzinfo=day_start.tzinfo)))
        bedtime = datetime.combine(day, limits.bedtimes[weekday], tzinfo=day_start.tzinfo)
    return GuideDayView(day=day, now=now, channels=channels, game_windows=game_windows, bedtime=bedtime)


def _guide_error(error: GuideError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


# ---- Box ----

@box_router.get("/guide")
def box_guide(day: date | None = None, services: Services = Depends(get_services)) -> GuideDayView:
    return _guide_day(services, day, "/box/art", include_gaps=False, kid_view=True)


@box_router.get("/channels/{channel_id}/now")
def channel_now(channel_id: str, services: Services = Depends(get_services)) -> NowPlayingView:
    guide = services.guide
    try:
        channel = guide.channel(channel_id)
    except GuideError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    now = guide.now().replace(microsecond=0)
    guide.ensure_week(now)
    slots = guide.slots_between(now - timedelta(hours=6), now + timedelta(days=2))
    hidden_ids = set() if services.box_state.parent_mode else services.store.hidden_item_ids()
    current = slot_at(slots, channel_id, now)
    if current and (current.programme is None or current.programme.hide_id in hidden_ids):
        current = None
    upcoming = find_next_slot(slots, channel_id, now)
    return NowPlayingView(
        channel_id=channel.id,
        channel_name=channel.name,
        kind=channel.kind,
        now=now,
        slot=slot_view(current, "/box/art") if current else None,
        path=current.programme.path if current and current.programme else None,
        offset_seconds=(now - current.start).total_seconds() if current else None,
        next=slot_view(upcoming, "/box/art") if upcoming else None,
    )


# ---- Admin ----

def _regenerate_current_weeks(services: Services) -> None:
    now = services.guide.now()
    services.guide.generate(now)
    next_week = now + timedelta(days=7)
    if services.guide.week(next_week) is not None:
        services.guide.generate(next_week)


@admin_router.get("/channels")
def list_channels(services: Services = Depends(get_services)) -> list[Channel]:
    return services.guide.channels()


@admin_router.post("/channels")
def create_channel(data: ChannelInput, services: Services = Depends(get_services)) -> Channel:
    channel = services.guide.create_channel(data)
    _regenerate_current_weeks(services)
    return channel


@admin_router.put("/channels/{channel_id}")
def update_channel(channel_id: str, data: ChannelInput, services: Services = Depends(get_services)) -> Channel:
    try:
        channel = services.guide.update_channel(channel_id, data)
    except GuideError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    _regenerate_current_weeks(services)
    return channel


@admin_router.delete("/channels/{channel_id}")
def delete_channel(channel_id: str, services: Services = Depends(get_services)) -> None:
    services.guide.delete_channel(channel_id)
    _regenerate_current_weeks(services)


@admin_router.get("/pool")
def pool_items(services: Services = Depends(get_services)) -> list[PoolItemView]:
    """What can go in a channel: box films, shows and albums (USB items cannot)."""
    library = services.library.library
    items: list[PoolItemView] = []
    for film in library.films:
        if film.source is MediaSource.BOX:
            items.append(PoolItemView(kind=PoolKind.FILM, id=film.id, title=film.title, detail=str(film.year or "")))
    for show in library.shows:
        items.append(PoolItemView(kind=PoolKind.SHOW, id=show.id, title=show.title, detail=f"{len(show.episodes)} episodes"))
    for album in library.albums:
        if album.source is MediaSource.BOX:
            items.append(PoolItemView(kind=PoolKind.ALBUM, id=album.id, title=album.title, detail=album.artist))
    return items


@admin_router.get("/programmes")
def programme_choices(kind: ChannelKind, services: Services = Depends(get_services)) -> list[ProgrammeChoice]:
    """Single films, episodes or tracks the parent can put in a slot by hand."""
    library = services.library.library
    pool = (
        [{"kind": "album", "id": album.id} for album in library.albums]
        if kind is ChannelKind.MUSIC
        else [{"kind": "film", "id": film.id} for film in library.films] + [{"kind": "show", "id": show.id} for show in library.shows]
    )
    probe = Channel(
        id="probe", number=0, name="probe", kind=kind, order="in_order", pool=pool, hours={day: None for day in Weekday},
    )
    choices: list[ProgrammeChoice] = []
    for programme in programmes_for(probe, library, services.durations.all(), set()):
        choices.append(ProgrammeChoice(
            ref=programme.ref, title=programme.title, subtitle=programme.subtitle, minutes=max(1, round(programme.seconds / 60)),
        ))
    return choices


@admin_router.get("/guide")
def admin_guide(day: date | None = None, services: Services = Depends(get_services)) -> GuideDayView:
    return _guide_day(services, day, "/api/admin/art", include_gaps=True, kid_view=False)


@admin_router.post("/guide/generate")
def generate_guide(day: date | None = None, services: Services = Depends(get_services)) -> GuideDayView:
    start, _ = _day_bounds(services, day or services.guide.now().date())
    services.guide.generate(start)
    return admin_guide(day, services)


@admin_router.get("/guide/week")
def admin_guide_week(channel_id: str, day: date | None = None, services: Services = Depends(get_services)) -> GuideWeekView:
    """One channel's week (the week that contains `day`), for the admin app's table."""
    guide = services.guide
    try:
        channel = guide.channel(channel_id)
    except GuideError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    today = guide.now().date()
    week_start = week_start_for(datetime.combine(day or today, time(0), tzinfo=guide.zone()))
    guide.ensure_week(week_start)
    slots = guide.slots_between(week_start, week_start + timedelta(days=7))
    views = [slot_view(slot, "/api/admin/art") for slot in slots if slot.channel_id == channel.id]
    days = [week_start.date() + timedelta(days=offset) for offset in range(7)]
    return GuideWeekView(week_start=week_start.date(), today=today, channel=channel, days=days, slots=views)


@admin_router.post("/guide/shuffle")
def shuffle_guide(body: ShuffleRequest, services: Services = Depends(get_services)) -> None:
    try:
        services.guide.shuffle(body.channel_id, body.day, body.whole_week)
    except GuideError as error:
        raise _guide_error(error) from error


@admin_router.post("/guide/slots")
def place_slot(body: SlotPlacement, services: Services = Depends(get_services)) -> None:
    # The admin app sends a clicked time without a zone: it is the box's local time.
    start = body.start if body.start.tzinfo else body.start.replace(tzinfo=services.guide.zone())
    try:
        services.guide.place(body.channel_id, start, body.ref, body.replace_slot_id)
    except GuideError as error:
        raise _guide_error(error) from error


@admin_router.post("/guide/slots/{slot_id}/clear")
def clear_slot(slot_id: str, body: SlotTarget, services: Services = Depends(get_services)) -> None:
    try:
        services.guide.clear_slot(slot_id, body.start)
    except GuideError as error:
        raise _guide_error(error) from error


@admin_router.post("/guide/slots/{slot_id}/restore")
def restore_slot(slot_id: str, body: SlotTarget, services: Services = Depends(get_services)) -> None:
    try:
        services.guide.restore_slot(slot_id, body.start)
    except GuideError as error:
        raise _guide_error(error) from error
