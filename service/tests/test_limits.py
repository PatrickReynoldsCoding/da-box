from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from dabox.limits import (
    PlayerSnapshot,
    ScheduleShutdown,
    StopPlayback,
    Notify,
    TodayUsage,
    compute_status,
    decide,
    may_start_game,
    may_start_video,
)
from dabox.limits_service import FakePower
from dabox.models import LimitSettings
from dabox.services import Services
from tests.conftest import FakeAgent, limits_payload, write_file

UTC = timezone.utc
# Wednesday. Game window 16:00-18:00, bedtime 19:30, quota 120 min, overrun 20 min, shared.
WEDNESDAY = datetime(2026, 10, 21, tzinfo=UTC)


def limits(**changes) -> LimitSettings:
    return LimitSettings.model_validate(limits_payload() | changes)


def at(hour: int, minute: int = 0) -> datetime:
    return WEDNESDAY.replace(hour=hour, minute=minute)


def used(video_minutes: float = 0, game_minutes: float = 0, **extra) -> TodayUsage:
    return TodayUsage(video_seconds=video_minutes * 60, game_seconds=game_minutes * 60, **extra)


# ---- compute_status ----

def test_parent_mode_and_no_setup_are_unlimited() -> None:
    assert compute_status(limits(), used(500), at(23), parent_mode=True).unlimited
    assert compute_status(None, used(), at(12), parent_mode=False).unlimited


def test_time_left_and_deadline() -> None:
    status = compute_status(limits(), used(video_minutes=90), at(12), False)
    assert status.video_seconds_left == 30 * 60
    # 30 minutes left + 20 minutes overrun.
    assert status.video_deadline == at(12, 50)
    assert not status.video_locked


def test_bedtime_caps_the_deadline() -> None:
    status = compute_status(limits(), used(), at(19), False)
    assert status.video_deadline == at(19, 30)
    with_overrun = compute_status(limits(bedtime_overrun=True), used(), at(19), False)
    assert with_overrun.video_deadline == at(19, 50)


def test_shared_quota_counts_games() -> None:
    assert compute_status(limits(), used(60, 60), at(12), False).video_locked
    assert not compute_status(limits(shared_quota=False), used(60, 60), at(12), False).video_locked


def test_extra_time_adds_to_quota() -> None:
    status = compute_status(limits(), used(120, extra_quota_minutes=15), at(12), False)
    assert status.video_seconds_left == 15 * 60


@pytest.mark.parametrize(
    ("moment", "is_night"),
    [(at(5, 59), True), (at(6), False), (at(19, 29), False), (at(19, 30), True), (at(23), True)],
)
def test_night(moment: datetime, is_night: bool) -> None:
    status = compute_status(limits(), used(), moment, False)
    assert status.night is is_night
    assert status.video_locked is is_night


@pytest.mark.parametrize(
    ("moment", "usage", "open_", "message"),
    [
        (at(15), used(), False, "Games open at 16:00"),
        (at(16, 30), used(), True, "Open until 18:00"),
        (at(17), used(100), True, "Open until 17:20"),
        (at(16, 30), used(120), False, "No time left today"),
        (at(18, 5), used(), False, "Games are over for today"),
    ],
)
def test_games(moment: datetime, usage: TodayUsage, open_: bool, message: str) -> None:
    status = compute_status(limits(), usage, moment, False)
    assert (status.games_open, status.games_message) == (open_, message)


def test_no_games_today_and_extra_game_time() -> None:
    sunday = WEDNESDAY + timedelta(days=4)
    assert compute_status(limits(), used(), sunday.replace(hour=12), False).games_message == "No games today"
    status = compute_status(limits(), used(extra_game_minutes=30), at(18, 10), False)
    assert status.games_message == "Open until 18:30"


def test_warnings() -> None:
    assert compute_status(limits(), used(), at(17, 56), False).warning == "Game time ends in 4 minutes"
    assert compute_status(limits(), used(), at(19, 26), False).warning == "Bedtime in 4 minutes"
    assert compute_status(limits(), used(), at(12), False).warning is None


# ---- rule (c) ----

def test_video_may_start_only_if_it_ends_before_the_deadline() -> None:
    status = compute_status(limits(), used(video_minutes=90), at(12), False)
    assert may_start_video(status, 50 * 60).allowed
    denied = may_start_video(status, 51 * 60)
    assert not denied.allowed and "not enough" in denied.reason


def test_locked_video_says_why() -> None:
    assert may_start_video(compute_status(limits(), used(120), at(12), False), 60).reason == "That's all the TV for today!"
    assert "bedtime" in may_start_video(compute_status(limits(), used(), at(21), False), 60).reason


def test_game_decision() -> None:
    assert may_start_game(compute_status(limits(), used(), at(16, 30), False)).allowed
    assert may_start_game(compute_status(limits(), used(), at(15), False)).reason == "Games open at 16:00"


# ---- enforcer decisions ----

PLAYING_VIDEO = PlayerSnapshot(state="playing", kind="video")
PLAYING_GAME = PlayerSnapshot(state="playing", kind="game")
IDLE = PlayerSnapshot(state="idle", kind=None)


def test_approved_video_plays_to_its_end_after_quota() -> None:
    usage = used(125)
    status = compute_status(limits(), usage, at(12), False)
    assert decide(status, usage, PLAYING_VIDEO, approved_video_until=at(12, 10), shutdown_scheduled=False) == []
    late = compute_status(limits(), usage, at(12, 12), False)
    assert decide(late, usage, PLAYING_VIDEO, at(12, 10), False) == [StopPlayback("That's all the TV for today!")]


def test_unapproved_video_stops_when_locked() -> None:
    usage = used(120)
    actions = decide(compute_status(limits(), usage, at(12), False), usage, PLAYING_VIDEO, None, False)
    assert isinstance(actions[0], StopPlayback)


def test_game_warnings_then_stop() -> None:
    usage = used()
    warning = decide(compute_status(limits(), usage, at(17, 56), False), usage, PLAYING_GAME, None, False)
    assert warning == [Notify("game-5", "Game time ends in 4 minutes")]
    last = decide(compute_status(limits(), usage, at(17, 59, ), False), usage, PLAYING_GAME, None, False)
    assert last == [Notify("game-1", "Game time ends in 1 minute")]
    over = decide(compute_status(limits(), usage, at(18, 1), False), usage, PLAYING_GAME, None, False)
    assert over == [StopPlayback("Game time is over. Your game is saved!")]


def test_shutdown_after_quota_once_and_at_bedtime() -> None:
    usage = used(120)
    assert decide(compute_status(limits(), usage, at(12), False), usage, IDLE, None, False) == [
        ScheduleShutdown("That's all the TV for today!", quota=True)
    ]
    done = used(120, quota_shutdown_done=True)
    assert decide(compute_status(limits(), done, at(12), False), done, IDLE, None, False) == []
    music = PlayerSnapshot(state="playing", kind="audio")
    assert decide(compute_status(limits(), done, at(20), False), done, music, None, False) == [
        ScheduleShutdown("It's bedtime. Good night!", quota=False)
    ]


# ---- LimitsService and API ----

@pytest.fixture
def limited(services: Services, completed_setup: None):
    clock = {"now": datetime(2026, 10, 21, 16, 30)}
    services.guide.clock = lambda zone: clock["now"].replace(tzinfo=zone)
    return services, clock


def test_api_status_and_approvals(limited, box_client: TestClient) -> None:
    services, clock = limited
    status = box_client.get("/box/limits").json()
    assert (status["games_open"], status["video_seconds_left"]) == (True, 7200)

    assert box_client.post("/box/limits/video", json={"seconds": 3600}).json() == {"allowed": True, "reason": None}
    denied = box_client.post("/box/limits/video", json={"seconds": 3 * 3600}).json()
    assert denied["allowed"] is False
    assert box_client.post("/box/limits/game").json()["allowed"] is True


def test_tick_counts_usage_and_stops_games(limited, fake_agent: FakeAgent, box_client: TestClient) -> None:
    services, clock = limited
    fake_ticks = iter([1000.0, 1002.0, 1004.0, 1006.0])
    services.limits.monotonic = lambda: next(fake_ticks)
    fake_agent.play("game")
    services.limits.tick()
    services.limits.tick()
    services.limits.tick()
    assert box_client.get("/box/limits").json()["used_minutes"] == 0
    assert services.limits._usage.get(clock["now"].date()).game_seconds == 4.0

    clock["now"] = datetime(2026, 10, 21, 18, 1)
    services.limits.tick()
    assert fake_agent.stopped == 1
    assert fake_agent.messages == ["Game time is over. Your game is saved!"]


def test_shutdown_then_power_off(limited, fake_agent: FakeAgent, fake_power: FakePower, box_client: TestClient) -> None:
    services, clock = limited
    clock["now"] = datetime(2026, 10, 21, 20, 0)
    services.limits.tick()
    status = box_client.get("/box/limits").json()
    assert status["shutdown_at"] is not None
    assert not fake_power.powered_off

    clock["now"] = datetime(2026, 10, 21, 20, 1, 1)
    services.limits.tick()
    assert fake_power.powered_off


def test_extra_time_cancels_quota_shutdown(limited, fake_agent: FakeAgent, admin_client: TestClient) -> None:
    services, clock = limited
    usage = services.limits._usage.get(clock["now"].date())
    usage.video_seconds = 7200
    services.limits._usage.put(clock["now"].date(), usage)
    services.limits.tick()
    assert admin_client.get("/api/admin/today").json()["shutdown_at"] is not None

    after = admin_client.post("/api/admin/extra-time", json={"quota_minutes": 15}).json()
    assert (after["shutdown_at"], after["video_locked"], after["video_seconds_left"]) == (None, False, 900)
    assert admin_client.post("/api/admin/extra-time", json={}).status_code == 422


def test_parent_mode_has_no_limits(limited, fake_agent: FakeAgent, box_client: TestClient) -> None:
    services, clock = limited
    services.box_state.set_parent_mode(True)
    clock["now"] = datetime(2026, 10, 21, 23, 0)
    fake_agent.play("game")
    services.limits.tick()
    assert fake_agent.stopped == 0
    assert box_client.get("/box/limits").json()["unlimited"] is True


def test_games_list_needs_a_core(limited, box_client: TestClient, media_dir) -> None:
    services, _ = limited
    write_file(media_dir / "Games" / "nes" / "Space Game (USA).nes", b"nes rom")
    write_file(media_dir / "Games" / "snes" / "No Core Game.sfc", b"snes rom")
    services.rescan_library()
    games = box_client.get("/box/games").json()
    assert [(game["title"], game["system_name"]) for game in games] == [("Space Game", "NES")]
    assert games[0]["core"].endswith("nestopia_libretro.so")


def test_game_box_art_from_libretro_thumbnails(limited, box_client: TestClient, media_dir, fake_http) -> None:
    services, _ = limited
    write_file(media_dir / "Games" / "nes" / "Space Game (USA).nes", b"nes rom")
    services.rescan_library()
    fake_http.responses["https://thumbnails.libretro.com/Nintendo%20-%20Nintendo%20Entertainment%20System/Named_Boxarts/Space%20Game%20%28USA%29.png"] = b"\x89PNG art"
    game = services.library.library.games[0]
    services.metadata.auto_fetch(game)
    art_url = box_client.get("/box/games").json()[0]["art_url"]
    assert box_client.get(art_url).content == b"\x89PNG art"
