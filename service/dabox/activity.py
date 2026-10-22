"""What was watched, played and listened to, and for how long (admin app, Activity tab)."""

from datetime import date, datetime, timedelta

from pydantic import BaseModel

from dabox.store import Store

# Shorter sessions (zapping through channels, a mis-press) are not worth showing.
MIN_SECONDS = 10.0
KEEP_DAYS = 60


class ActivityEntry(BaseModel):
    kind: str
    title: str
    started: datetime
    ended: datetime
    seconds: float


class DayTotals(BaseModel):
    day: date
    video_minutes: int
    game_minutes: int
    music_minutes: int


class _Session(BaseModel):
    kind: str
    title: str
    started: datetime
    last_seen: datetime


_KIND_TO_TOTAL = {"video": "video_minutes", "game": "game_minutes", "audio": "music_minutes"}


def day_totals(entries: list[ActivityEntry]) -> list[DayTotals]:
    """Minutes per kind, per day, newest day first."""
    minutes: dict[date, dict[str, float]] = {}
    for entry in entries:
        field = _KIND_TO_TOTAL.get(entry.kind)
        if field is None:
            continue
        day_minutes = minutes.setdefault(entry.started.date(), {})
        day_minutes[field] = day_minutes.get(field, 0.0) + entry.seconds / 60
    totals: list[DayTotals] = []
    for day in sorted(minutes, reverse=True):
        values = minutes[day]
        totals.append(DayTotals(
            day=day,
            video_minutes=round(values.get("video_minutes", 0)),
            game_minutes=round(values.get("game_minutes", 0)),
            music_minutes=round(values.get("music_minutes", 0)),
        ))
    return totals


class ActivityLog:
    """Turns the player snapshots of each enforcer tick into sessions."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._session: _Session | None = None

    def observe(self, kind: str | None, title: str | None, playing: bool, now: datetime) -> None:
        current = (kind, title) if playing and kind and title else None
        if self._session is not None and current == (self._session.kind, self._session.title):
            self._session.last_seen = now
            return
        self._close(now)
        if current is not None:
            self._session = _Session(kind=current[0], title=current[1], started=now, last_seen=now)

    def _close(self, now: datetime) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        # The session ended somewhere between the last tick that saw it and now.
        ended = min(now, session.last_seen + timedelta(seconds=5))
        seconds = (ended - session.started).total_seconds()
        if seconds >= MIN_SECONDS:
            self._store.add_activity(ActivityEntry(
                kind=session.kind, title=session.title, started=session.started, ended=ended, seconds=seconds,
            ).model_dump(mode="json"))

    def recent(self, now: datetime, days: int = 7) -> list[ActivityEntry]:
        since = now - timedelta(days=days)
        self._store.delete_activity_before((now - timedelta(days=KEEP_DAYS)).isoformat())
        return [ActivityEntry.model_validate(row) for row in self._store.activity_since(since.isoformat())]
