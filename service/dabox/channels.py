"""Channels and the weekly TV guide (design doc section 7.1).

A channel has a pool (films, shows or albums), an order, and opening hours for
each day. The generator fills one week with programmes. Slots the parent edited
stay; the generator fills around them. Channels play "live": a programme starts
at the point the schedule is at now.
"""

import hashlib
import random
import secrets
import threading
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dabox.durations import Durations
from dabox.library import LibraryIndex
from dabox.models import Library, Weekday
from dabox.store import Store

_CHANNELS_KEY = "channels"
_WEEK_KEY_PREFIX = "guide_week:"
WEEKDAYS = list(Weekday)


class ChannelKind(StrEnum):
    VIDEO = "video"
    MUSIC = "music"


class PlayOrder(StrEnum):
    IN_ORDER = "in_order"
    SHUFFLE = "shuffle"


class PoolKind(StrEnum):
    FILM = "film"
    SHOW = "show"
    ALBUM = "album"


_POOL_KINDS_FOR_CHANNEL = {
    ChannelKind.VIDEO: {PoolKind.FILM, PoolKind.SHOW},
    ChannelKind.MUSIC: {PoolKind.ALBUM},
}


class PoolEntry(BaseModel):
    kind: PoolKind
    id: str


class OpenHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: time
    end: time

    @model_validator(mode="after")
    def _end_after_start(self) -> "OpenHours":
        if self.end <= self.start:
            raise ValueError("a channel must close after it opens")
        return self


class ChannelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    kind: ChannelKind
    order: PlayOrder
    pool: list[PoolEntry]
    # None means "closed on this day".
    hours: dict[Weekday, OpenHours | None]

    @model_validator(mode="after")
    def _check(self) -> "ChannelInput":
        if set(self.hours) != set(Weekday):
            raise ValueError("hours must have an entry for every day")
        allowed = _POOL_KINDS_FOR_CHANNEL[self.kind]
        if any(entry.kind not in allowed for entry in self.pool):
            raise ValueError(f"a {self.kind} channel can only use {', '.join(sorted(allowed))}")
        return self


class Channel(ChannelInput):
    id: str
    number: int


class Programme(BaseModel):
    """Something that can go in a slot: a film, an episode or a track."""

    ref: str
    title: str
    subtitle: str | None
    path: str
    seconds: float
    # The library item whose art to show (film, show or album id).
    art_item_id: str | None
    hide_id: str


class Slot(BaseModel):
    id: str
    channel_id: str
    start: datetime
    end: datetime
    # None is a gap the parent made on purpose.
    programme: Programme | None
    edited: bool


class ChannelShuffle(BaseModel):
    """The parent's "Shuffle week" and "Shuffle day" presses, saved so that filling the week
    again (after an edit or a channel change) gives the same order."""

    week: str = ""
    days: dict[date, str] = Field(default_factory=dict)


class WeekSchedule(BaseModel):
    week_start: datetime
    slots: list[Slot]
    # Where each in-order channel's list started and ended this week.
    cursors: dict[str, dict[str, int]]
    shuffles: dict[str, ChannelShuffle] = Field(default_factory=dict)


class GuideError(Exception):
    pass


# ---- Pure helpers ----

def slot_id(channel_id: str, start: datetime) -> str:
    return hashlib.sha1(f"{channel_id}:{start.isoformat()}".encode()).hexdigest()[:16]


def week_start_for(moment: datetime) -> datetime:
    """Monday 00:00 of the week that contains `moment`, in `moment`'s time zone."""
    monday = moment.date() - timedelta(days=moment.weekday())
    return datetime.combine(monday, time(0), tzinfo=moment.tzinfo)


def week_key(week_start: datetime) -> str:
    return week_start.date().isoformat()


def programmes_for(channel: Channel, library: Library, durations: dict[str, float], hidden_ids: set[str]) -> list[Programme]:
    """The channel's pool as a list of programmes, in pool order. Skips hidden items,
    USB items and files with no known length."""
    films = {film.id: film for film in library.films if film.source == "box"}
    shows = {show.id: show for show in library.shows if show.source == "box"}
    albums = {album.id: album for album in library.albums if album.source == "box"}
    programmes: list[Programme] = []

    def add(ref: str, title: str, subtitle: str | None, path: Any, fingerprint: str, art_item_id: str | None, hide_id: str) -> None:
        seconds = durations.get(fingerprint) or 0.0
        if seconds > 0 and hide_id not in hidden_ids:
            programmes.append(Programme(
                ref=ref, title=title, subtitle=subtitle, path=str(path), seconds=seconds,
                art_item_id=art_item_id, hide_id=hide_id,
            ))

    for entry in channel.pool:
        if entry.kind is PoolKind.FILM and entry.id in films:
            film = films[entry.id]
            add(f"film:{film.id}", film.title, str(film.year) if film.year else None, film.path, film.fingerprint, film.id, film.id)
        elif entry.kind is PoolKind.SHOW and entry.id in shows:
            show = shows[entry.id]
            for episode in show.episodes:
                # Videos in a group without S01E02 markers (season 0) show only their title.
                subtitle = f"S{episode.season} E{episode.number} · {episode.title}" if episode.season else episode.title
                add(f"episode:{episode.id}", show.title, subtitle, episode.path, episode.fingerprint, show.id, show.id)
        elif entry.kind is PoolKind.ALBUM and entry.id in albums:
            album = albums[entry.id]
            for track in album.tracks:
                add(f"track:{track.id}", track.title, track.artist, track.path, track.fingerprint, album.id, album.id)
    return programmes


def free_intervals(window_start: datetime, window_end: datetime, taken: list[Slot]) -> list[tuple[datetime, datetime]]:
    """The parts of the window that edited slots do not cover."""
    intervals: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for slot in sorted(taken, key=lambda slot: slot.start):
        if slot.end <= cursor or slot.start >= window_end:
            continue
        if slot.start > cursor:
            intervals.append((cursor, slot.start))
        cursor = max(cursor, slot.end)
    if cursor < window_end:
        intervals.append((cursor, window_end))
    return intervals


class _ShuffleDeck:
    """Deals programmes in a shuffled order, then shuffles again. Seeded, so a
    generation can be repeated."""

    def __init__(self, programmes: list[Programme], seed: str) -> None:
        self._programmes = programmes
        self._random = random.Random(seed)
        self._deck: list[Programme] = []

    def take_fitting(self, seconds_left: float) -> Programme | None:
        if not self._deck:
            self._deck = list(self._programmes)
            self._random.shuffle(self._deck)
        for index, programme in enumerate(self._deck):
            if programme.seconds <= seconds_left:
                return self._deck.pop(index)
        return None


def generate_channel_week(
    channel: Channel,
    programmes: list[Programme],
    week_start: datetime,
    zone: tzinfo,
    start_cursor: int,
    edited: list[Slot],
    shuffle: ChannelShuffle | None = None,
) -> tuple[list[Slot], int]:
    """Fills the channel's open hours for one week. Returns the new slots and the end cursor.
    A day with its own shuffle gets its own deck; the other days share the week's deck."""
    slots: list[Slot] = []
    cursor = start_cursor
    shuffle = shuffle or ChannelShuffle()
    week_seed = f"{channel.id}:{week_key(week_start)}" + (f":{shuffle.week}" if shuffle.week else "")
    week_deck = _ShuffleDeck(programmes, week_seed)
    if not programmes:
        return slots, cursor

    for day_index in range(7):
        day: date = week_start.date() + timedelta(days=day_index)
        hours = channel.hours.get(WEEKDAYS[day.weekday()])
        if hours is None:
            continue
        window_start = datetime.combine(day, hours.start, tzinfo=zone)
        window_end = datetime.combine(day, hours.end, tzinfo=zone)
        intervals = free_intervals(window_start, window_end, edited)
        day_start_cursor = cursor
        day_slots, cursor = _fill_day(channel, programmes, intervals, week_deck, day_start_cursor)
        day_seed = shuffle.days.get(day)
        if day_seed:
            # The week's deck still dealt this day above, so the days after it keep their order.
            day_deck = _ShuffleDeck(programmes, f"{channel.id}:{day.isoformat()}:{day_seed}")
            day_slots, _ = _fill_day(channel, programmes, intervals, day_deck, day_start_cursor)
        slots += day_slots
    return slots, cursor


def _fill_day(
    channel: Channel,
    programmes: list[Programme],
    intervals: list[tuple[datetime, datetime]],
    deck: _ShuffleDeck,
    cursor: int,
) -> tuple[list[Slot], int]:
    slots: list[Slot] = []
    for interval_start, interval_end in intervals:
        moment = interval_start
        while True:
            seconds_left = (interval_end - moment).total_seconds()
            if channel.order is PlayOrder.IN_ORDER:
                programme = programmes[cursor % len(programmes)]
                if programme.seconds > seconds_left:
                    break
                cursor += 1
            else:
                found = deck.take_fitting(seconds_left)
                if found is None:
                    break
                programme = found
            end = moment + timedelta(seconds=programme.seconds)
            slots.append(Slot(
                id=slot_id(channel.id, moment), channel_id=channel.id, start=moment, end=end,
                programme=programme, edited=False,
            ))
            moment = end
    return slots, cursor


def slot_at(slots: list[Slot], channel_id: str, moment: datetime) -> Slot | None:
    for slot in slots:
        if slot.channel_id == channel_id and slot.start <= moment < slot.end:
            return slot
    return None


def next_slot(slots: list[Slot], channel_id: str, moment: datetime) -> Slot | None:
    upcoming = [slot for slot in slots if slot.channel_id == channel_id and slot.start > moment and slot.programme]
    return min(upcoming, key=lambda slot: slot.start) if upcoming else None


# ---- Guide service ----

class Guide:
    """Stores channels and weekly schedules, and answers "what is on now"."""

    def __init__(self, store: Store, library: LibraryIndex, durations: Durations, timezone_name: Any) -> None:
        self._store = store
        self._library = library
        self._durations = durations
        # A function, so a time zone changed in setup takes effect at once.
        self._timezone_name = timezone_name
        self._lock = threading.Lock()
        # Replaceable in tests.
        self.clock: Callable[[tzinfo], datetime] = lambda zone: datetime.now(zone)

    def zone(self) -> tzinfo:
        name = self._timezone_name()
        if name:
            return ZoneInfo(name)
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")

    def now(self) -> datetime:
        return self.clock(self.zone())

    # Channels

    def channels(self) -> list[Channel]:
        raw = self._store.get(_CHANNELS_KEY) or []
        return sorted((Channel.model_validate(item) for item in raw), key=lambda channel: channel.number)

    def _save_channels(self, channels: list[Channel]) -> None:
        self._store.put(_CHANNELS_KEY, [channel.model_dump(mode="json") for channel in channels])

    def channel(self, channel_id: str) -> Channel:
        for channel in self.channels():
            if channel.id == channel_id:
                return channel
        raise GuideError("No such channel")

    def create_channel(self, data: ChannelInput) -> Channel:
        channels = self.channels()
        number = max((channel.number for channel in channels), default=0) + 1
        channel = Channel(**data.model_dump(), id=secrets.token_hex(6), number=number)
        self._save_channels([*channels, channel])
        return channel

    def update_channel(self, channel_id: str, data: ChannelInput) -> Channel:
        existing = self.channel(channel_id)
        updated = Channel(**data.model_dump(), id=existing.id, number=existing.number)
        self._save_channels([updated if channel.id == channel_id else channel for channel in self.channels()])
        return updated

    def delete_channel(self, channel_id: str) -> None:
        self._save_channels([channel for channel in self.channels() if channel.id != channel_id])

    # Weeks

    def week(self, week_start: datetime) -> WeekSchedule | None:
        raw = self._store.get(_WEEK_KEY_PREFIX + week_key(week_start))
        return WeekSchedule.model_validate(raw) if raw is not None else None

    def _save_week(self, schedule: WeekSchedule) -> None:
        self._store.put(_WEEK_KEY_PREFIX + week_key(schedule.week_start), schedule.model_dump(mode="json"))

    def ensure_week(self, week_start: datetime) -> WeekSchedule:
        existing = self.week(week_start)
        return existing if existing is not None else self.generate(week_start)

    def generate(self, week_start: datetime) -> WeekSchedule:
        """(Re)fills the week. Edited slots stay. In-order channels start where they
        started last time for this week, or where last week ended."""
        with self._lock:
            zone = self.zone()
            week_start = week_start_for(week_start.astimezone(zone))
            existing = self.week(week_start)
            previous = self.week(week_start - timedelta(days=7))
            library = self._library.library
            hidden_ids = self._store.hidden_item_ids()
            durations = self._durations.all()

            old_shuffles = existing.shuffles if existing else {}
            slots: list[Slot] = []
            cursors: dict[str, dict[str, int]] = {}
            shuffles: dict[str, ChannelShuffle] = {}
            for channel in self.channels():
                edited = [slot for slot in (existing.slots if existing else []) if slot.channel_id == channel.id and slot.edited]
                start_cursor = self._start_cursor(channel.id, existing, previous)
                shuffle = old_shuffles.get(channel.id)
                generated, end_cursor = generate_channel_week(
                    channel, programmes_for(channel, library, durations, hidden_ids), week_start, zone, start_cursor, edited, shuffle,
                )
                slots += edited + generated
                cursors[channel.id] = {"start": start_cursor, "end": end_cursor}
                if shuffle is not None:
                    shuffles[channel.id] = shuffle
            schedule = WeekSchedule(
                week_start=week_start, slots=sorted(slots, key=lambda slot: slot.start), cursors=cursors, shuffles=shuffles,
            )
            self._save_week(schedule)
            return schedule

    def shuffle(self, channel_id: str, day: date, whole_week: bool) -> WeekSchedule:
        """Gives the channel a new random order for the week of `day`, or for `day` only.
        Edited slots stay."""
        if self.channel(channel_id).order is not PlayOrder.SHUFFLE:
            raise GuideError("This channel plays in order, so it cannot be shuffled")
        week_start = week_start_for(datetime.combine(day, time(0), tzinfo=self.zone()))
        self.ensure_week(week_start)
        with self._lock:
            schedule = self.week(week_start)
            if schedule is None:
                raise GuideError("That week has no guide yet")
            seed = secrets.token_hex(4)
            current = schedule.shuffles.get(channel_id, ChannelShuffle())
            updated = ChannelShuffle(week=seed) if whole_week else ChannelShuffle(week=current.week, days={**current.days, day: seed})
            schedule.shuffles = {**schedule.shuffles, channel_id: updated}
            self._save_week(schedule)
        return self.generate(week_start)

    @staticmethod
    def _start_cursor(channel_id: str, existing: WeekSchedule | None, previous: WeekSchedule | None) -> int:
        if existing and channel_id in existing.cursors:
            return existing.cursors[channel_id]["start"]
        if previous and channel_id in previous.cursors:
            return previous.cursors[channel_id]["end"]
        return 0

    def slots_between(self, start: datetime, end: datetime) -> list[Slot]:
        slots: list[Slot] = []
        week = week_start_for(start.astimezone(self.zone()))
        while week < end:
            schedule = self.week(week)
            if schedule:
                slots += [slot for slot in schedule.slots if slot.end > start and slot.start < end]
            week += timedelta(days=7)
        return slots

    # Edits by the parent

    def _edit_week(self, slot_start: datetime, change) -> WeekSchedule:
        with self._lock:
            week_start = week_start_for(slot_start.astimezone(self.zone()))
            schedule = self.week(week_start)
            if schedule is None:
                raise GuideError("That week has no guide yet")
            schedule.slots = sorted(change(schedule.slots), key=lambda slot: slot.start)
            self._save_week(schedule)
            return schedule

    def programme_for_ref(self, ref: str) -> Programme:
        kind, _, item_id = ref.partition(":")
        pool_kind = {"film": PoolKind.FILM, "episode": PoolKind.SHOW, "track": PoolKind.ALBUM}.get(kind)
        if pool_kind is None:
            raise GuideError("Unknown programme")
        library = self._library.library
        owners = {
            PoolKind.FILM: [film.id for film in library.films],
            PoolKind.SHOW: [show.id for show in library.shows if any(episode.id == item_id for episode in show.episodes)],
            PoolKind.ALBUM: [album.id for album in library.albums if any(track.id == item_id for track in album.tracks)],
        }[pool_kind]
        probe = Channel(
            id="probe", number=0, name="probe", order=PlayOrder.IN_ORDER,
            kind=ChannelKind.MUSIC if pool_kind is PoolKind.ALBUM else ChannelKind.VIDEO,
            pool=[PoolEntry(kind=pool_kind, id=owner) for owner in owners],
            hours={day: None for day in Weekday},
        )
        for programme in programmes_for(probe, library, self._durations.all(), set()):
            if programme.ref == ref:
                return programme
        raise GuideError("That programme is not on the box, or its length is not known yet")

    def place(self, channel_id: str, start: datetime, ref: str, replace_slot_id: str | None) -> WeekSchedule:
        """Puts a programme at `start`. Fails if it would overlap another slot."""
        programme = self.programme_for_ref(ref)
        end = start + timedelta(seconds=programme.seconds)

        def overlaps(slot: Slot) -> bool:
            return slot.channel_id == channel_id and slot.start < end and slot.end > start

        def change(slots: list[Slot]) -> list[Slot]:
            kept = [slot for slot in slots if slot.id != replace_slot_id]
            for slot in kept:
                # Other edits (and gaps the parent made) are never moved or removed.
                if overlaps(slot) and slot.edited:
                    what = slot.programme.title if slot.programme else "an empty gap"
                    raise GuideError(f"It would overlap {what} at {slot.start:%H:%M}")
            # Generated slots under the new one make way.
            kept = [slot for slot in kept if not overlaps(slot)]
            new_slot = Slot(id=slot_id(channel_id, start), channel_id=channel_id, start=start, end=end, programme=programme, edited=True)
            return [*kept, new_slot]

        return self._edit_week(start, change)

    def clear_slot(self, slot_id_to_clear: str, slot_start: datetime) -> WeekSchedule:
        """Makes the slot an empty gap that stays when the week is generated again."""

        def change(slots: list[Slot]) -> list[Slot]:
            changed: list[Slot] = []
            for slot in slots:
                if slot.id == slot_id_to_clear:
                    slot = slot.model_copy(update={"programme": None, "edited": True})
                changed.append(slot)
            return changed

        return self._edit_week(slot_start, change)

    def restore_slot(self, slot_id_to_restore: str, slot_start: datetime) -> WeekSchedule:
        """Removes an edit. The generator fills the time again."""
        self._edit_week(slot_start, lambda slots: [slot for slot in slots if slot.id != slot_id_to_restore])
        return self.generate(slot_start)
