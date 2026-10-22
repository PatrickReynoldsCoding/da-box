from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from dabox.activity import ActivityEntry, ActivityLog, day_totals
from dabox.services import Services
from dabox.store import Store
from tests.conftest import FakeAgent

START = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc)


def test_sessions_are_recorded_when_they_change(tmp_path: Path) -> None:
    log = ActivityLog(Store(tmp_path / "db.sqlite"))
    for second in range(0, 61, 2):
        log.observe("video", "Frozen", True, START + timedelta(seconds=second))
    log.observe("game", "Mario", True, START + timedelta(seconds=62))
    log.observe("game", "Mario", True, START + timedelta(seconds=64))
    log.observe("game", "Mario", True, START + timedelta(seconds=70))
    # Paused/idle closes the game; 3 seconds of zapping are not kept.
    log.observe(None, None, False, START + timedelta(seconds=72))
    log.observe("video", "Zap", True, START + timedelta(seconds=74))
    log.observe(None, None, False, START + timedelta(seconds=76))

    entries = log.recent(START + timedelta(minutes=5))
    assert [(entry.kind, entry.title, round(entry.seconds)) for entry in entries] == [("game", "Mario", 10), ("video", "Frozen", 62)]


def test_day_totals() -> None:
    entries = [
        ActivityEntry(kind="video", title="a", started=START, ended=START, seconds=600),
        ActivityEntry(kind="video", title="b", started=START, ended=START, seconds=300),
        ActivityEntry(kind="audio", title="c", started=START - timedelta(days=1), ended=START, seconds=120),
    ]
    totals = day_totals(entries)
    assert [(total.day.isoformat(), total.video_minutes, total.music_minutes) for total in totals] == [
        ("2026-10-21", 15, 0), ("2026-10-20", 0, 2),
    ]


def test_activity_api(services: Services, admin_client: TestClient, fake_agent: FakeAgent) -> None:
    clock = {"now": datetime(2026, 10, 21, 12, 0)}
    services.guide.clock = lambda zone: clock["now"].replace(tzinfo=zone)
    fake_agent.play("audio", "Song")
    for second in range(0, 40, 2):
        clock["now"] = datetime(2026, 10, 21, 12, 0, second)
        services.limits.tick()
    fake_agent.stop()
    services.limits.tick()

    activity = admin_client.get("/api/admin/activity").json()
    assert activity["entries"][0]["title"] == "Song"
    assert activity["totals"][0]["music_minutes"] == 1
