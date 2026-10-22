"""Daily quota, game window, overrun allowance and bedtime (design doc sections 7.2 to 7.6).

Everything here is pure: callers pass the settings, today's usage and the time.
The enforcer (background.py) does the I/O.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel

from dabox.models import LimitSettings, Weekday
from dabox.store import Store

# The night runs from bedtime until this time the next morning.
NIGHT_ENDS = time(6, 0)
WARNING_MINUTES = (5, 1)
# An approved video may run this much past its expected end (start-up, buffering).
APPROVAL_GRACE = timedelta(seconds=60)
SHUTDOWN_DELAY = timedelta(seconds=60)

_USAGE_KEY_PREFIX = "usage:"
WEEKDAYS = list(Weekday)


class TodayUsage(BaseModel):
    video_seconds: float = 0.0
    game_seconds: float = 0.0
    extra_quota_minutes: int = 0
    extra_game_minutes: int = 0
    # The box shuts down once when the quota is used up. After a restart it stays on, with video locked.
    quota_shutdown_done: bool = False


class LimitsStatus(BaseModel):
    unlimited: bool
    now: datetime
    quota_minutes: int | None
    used_minutes: int
    video_seconds_left: float | None
    # A video that starts now must end by this time (quota + overrun, and bedtime).
    video_deadline: datetime | None
    video_locked: bool
    video_locked_reason: str | None
    games_open: bool
    games_message: str
    games_until: datetime | None
    bedtime: datetime | None
    night: bool
    warning: str | None
    shutdown_at: datetime | None = None


class UsageStore:
    def __init__(self, store: Store) -> None:
        self._store = store

    def get(self, day: date) -> TodayUsage:
        raw = self._store.get(_USAGE_KEY_PREFIX + day.isoformat())
        return TodayUsage.model_validate(raw) if raw is not None else TodayUsage()

    def put(self, day: date, usage: TodayUsage) -> None:
        self._store.put(_USAGE_KEY_PREFIX + day.isoformat(), usage.model_dump())


def usage_day(now: datetime) -> date:
    """Usage resets at midnight."""
    return now.date()


def _minutes_text(delta: timedelta) -> str:
    minutes = max(1, math.ceil(delta.total_seconds() / 60))
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def is_night(limits: LimitSettings, now: datetime) -> bool:
    if now.time() < NIGHT_ENDS:
        return True
    bedtime = datetime.combine(now.date(), limits.bedtimes[WEEKDAYS[now.weekday()]], tzinfo=now.tzinfo)
    return now >= bedtime


def unlimited_status(now: datetime) -> LimitsStatus:
    return LimitsStatus(
        unlimited=True, now=now, quota_minutes=None, used_minutes=0, video_seconds_left=None, video_deadline=None,
        video_locked=False, video_locked_reason=None, games_open=True, games_message="Open", games_until=None,
        bedtime=None, night=False, warning=None,
    )


def compute_status(limits: LimitSettings | None, usage: TodayUsage, now: datetime, parent_mode: bool) -> LimitsStatus:
    if parent_mode or limits is None:
        return unlimited_status(now)

    weekday = WEEKDAYS[now.weekday()]
    quota_seconds = (limits.daily_quota_minutes + usage.extra_quota_minutes) * 60
    used_seconds = usage.video_seconds + (usage.game_seconds if limits.shared_quota else 0.0)
    left = max(0.0, quota_seconds - used_seconds)
    overrun = timedelta(minutes=limits.overrun_minutes)

    bedtime = datetime.combine(now.date(), limits.bedtimes[weekday], tzinfo=now.tzinfo)
    night = is_night(limits, now)
    bedtime_deadline = bedtime + overrun if limits.bedtime_overrun else bedtime
    video_deadline = min(now + timedelta(seconds=left) + overrun, bedtime_deadline) if left > 0 else None

    locked_reason = None
    if night:
        locked_reason = "It's bedtime. The TV is sleeping."
    elif left <= 0:
        locked_reason = "That's all the TV for today!"

    games_open, games_message, games_until = _games(limits, usage, now, night, left, bedtime)

    warning = None
    if games_open and games_until is not None and games_until - now <= timedelta(minutes=WARNING_MINUTES[0]):
        warning = f"Game time ends in {_minutes_text(games_until - now)}"
    if not night and timedelta(0) < bedtime - now <= timedelta(minutes=WARNING_MINUTES[0]):
        warning = f"Bedtime in {_minutes_text(bedtime - now)}"

    return LimitsStatus(
        unlimited=False,
        now=now,
        quota_minutes=limits.daily_quota_minutes + usage.extra_quota_minutes,
        used_minutes=int(used_seconds // 60),
        video_seconds_left=left,
        video_deadline=video_deadline,
        video_locked=locked_reason is not None,
        video_locked_reason=locked_reason,
        games_open=games_open,
        games_message=games_message,
        games_until=games_until,
        bedtime=bedtime,
        night=night,
        warning=warning,
    )


def _games(
    limits: LimitSettings, usage: TodayUsage, now: datetime, night: bool, quota_left: float, bedtime: datetime
) -> tuple[bool, str, datetime | None]:
    window = limits.game_windows[WEEKDAYS[now.weekday()]]
    if window is None:
        return False, "No games today", None
    start = datetime.combine(now.date(), window.start, tzinfo=now.tzinfo)
    end = datetime.combine(now.date(), window.end, tzinfo=now.tzinfo) + timedelta(minutes=usage.extra_game_minutes)
    until = min(end, bedtime)
    if limits.shared_quota:
        until = min(until, now + timedelta(seconds=quota_left))
    if night:
        return False, "Games are asleep", None
    if limits.shared_quota and quota_left <= 0:
        return False, "No time left today", None
    if now < start:
        return False, f"Games open at {start:%H:%M}", None
    if now >= until:
        return False, "Games are over for today", None
    return True, f"Open until {until:%H:%M}", until


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None


def may_start_video(status: LimitsStatus, seconds: float) -> Decision:
    """Rule (c): a video can start only if it ends before the deadline."""
    if status.unlimited:
        return Decision(True)
    if status.video_locked:
        return Decision(False, status.video_locked_reason)
    if status.video_deadline is None or status.now + timedelta(seconds=seconds) > status.video_deadline:
        return Decision(False, "There is not enough TV time left today for this one.")
    return Decision(True)


def may_start_game(status: LimitsStatus) -> Decision:
    if status.games_open:
        return Decision(True)
    return Decision(False, status.games_message)


# ---- Enforcer decisions ----

class PlayerSnapshot(BaseModel):
    """What the player agent is doing. kind: "video", "audio", "game" or None."""

    state: str
    kind: str | None

    @property
    def active(self) -> bool:
        return self.state in ("playing", "paused")


@dataclass(frozen=True)
class StopPlayback:
    message: str


@dataclass(frozen=True)
class Notify:
    key: str
    message: str


@dataclass(frozen=True)
class ScheduleShutdown:
    reason: str
    quota: bool


EnforcerAction = StopPlayback | Notify | ScheduleShutdown


def decide(
    status: LimitsStatus,
    usage: TodayUsage,
    player: PlayerSnapshot,
    approved_video_until: datetime | None,
    shutdown_scheduled: bool,
) -> list[EnforcerAction]:
    if status.unlimited:
        return []
    now = status.now
    actions: list[EnforcerAction] = []

    if player.active and player.kind == "video":
        approved = approved_video_until is not None and now <= approved_video_until + APPROVAL_GRACE
        past_deadline = status.video_deadline is None or now > status.video_deadline
        if not approved and (status.video_locked or past_deadline):
            actions.append(StopPlayback(status.video_locked_reason or "TV time is over for today"))

    if player.active and player.kind == "game":
        if not status.games_open:
            actions.append(StopPlayback("Game time is over. Your game is saved!"))
        elif status.games_until is not None:
            # Smallest first, so the last minute gets its own warning.
            for minutes in sorted(WARNING_MINUTES):
                if status.games_until - now <= timedelta(minutes=minutes):
                    actions.append(Notify(f"game-{minutes}", f"Game time ends in {_minutes_text(status.games_until - now)}"))
                    break

    if not shutdown_scheduled:
        if status.night:
            # Bedtime: everything stops, music too.
            if not player.active or player.kind == "audio":
                actions.append(ScheduleShutdown("It's bedtime. Good night!", quota=False))
        elif status.video_locked and not usage.quota_shutdown_done and not player.active:
            actions.append(ScheduleShutdown("That's all the TV for today!", quota=True))
    return actions
