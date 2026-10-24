from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox.channels import (
    Channel,
    ChannelKind,
    ChannelShuffle,
    OpenHours,
    PlayOrder,
    Programme,
    Slot,
    free_intervals,
    generate_channel_week,
    week_start_for,
)
from dabox.library import episode_title, parse_episode
from dabox.models import Weekday
from dabox.services import Services

UTC = timezone.utc
MONDAY = datetime(2026, 10, 19, tzinfo=UTC)


def programme(name: str, minutes: float) -> Programme:
    return Programme(ref=f"film:{name}", title=name, subtitle=None, path=f"/m/{name}.mp4", seconds=minutes * 60,
                     art_item_id=None, hide_id=name)


def channel(order: PlayOrder, hours: dict | None = None) -> Channel:
    every_day = {day: OpenHours(start="18:00", end="19:00") for day in Weekday}
    return Channel(id="c1", number=1, name="Test", kind=ChannelKind.VIDEO, order=order,
                   pool=[], hours=hours if hours is not None else every_day)


# ---- Pure generator ----

@pytest.mark.parametrize(
    ("name", "expected"),
    [("Bluey S01E05 - Pool", (1, 5)), ("show.s2e10.mkv", (2, 10)), ("Season 3/04 Bike", (3, 4)), ("Extras/Trailer", None)],
)
def test_parse_episode(name: str, expected: tuple[int, int] | None) -> None:
    assert parse_episode(Path(f"/tv/Show/{name}.mp4")) == expected


def test_episode_title() -> None:
    assert episode_title(Path("Bluey S01E05 - The Pool.mp4"), "Bluey") == "The Pool"
    assert episode_title(Path("Bluey S01E05.mp4"), "Bluey") == "Bluey S01E05"


def test_week_start_is_monday_midnight() -> None:
    assert week_start_for(datetime(2026, 10, 22, 15, 30, tzinfo=UTC)) == MONDAY


def test_in_order_fills_window_leaves_gap_and_continues_next_day() -> None:
    programmes = [programme("a", 25), programme("b", 25), programme("c", 25)]
    hours = {day: None for day in Weekday} | {Weekday.MON: OpenHours(start="18:00", end="19:00"),
                                              Weekday.TUE: OpenHours(start="18:00", end="19:00")}

    slots, cursor = generate_channel_week(channel(PlayOrder.IN_ORDER, hours), programmes, MONDAY, UTC, 0, [])

    assert [(slot.start.strftime("%a %H:%M"), slot.programme.title) for slot in slots] == [
        ("Mon 18:00", "a"), ("Mon 18:25", "b"),  # c does not fit before 19:00: gap
        ("Tue 18:00", "c"), ("Tue 18:25", "a"),
    ]
    assert cursor == 4


def test_in_order_starts_at_cursor() -> None:
    programmes = [programme("a", 30), programme("b", 30)]
    slots, _ = generate_channel_week(channel(PlayOrder.IN_ORDER), programmes, MONDAY, UTC, 1, [])
    assert slots[0].programme.title == "b"


def test_shuffle_only_picks_programmes_that_fit() -> None:
    programmes = [programme("long", 50), programme("short", 10)]
    slots, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [])
    for slot in slots:
        assert slot.end <= slot.start.replace(hour=19, minute=0)
    assert len(slots) >= 7 * 2


def test_shuffle_is_repeatable() -> None:
    programmes = [programme(name, 10) for name in "abcdef"]
    first, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [])
    second, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [])
    assert [slot.programme.title for slot in first] == [slot.programme.title for slot in second]


def titles_by_day(slots: list[Slot]) -> dict[str, list[str]]:
    days: dict[str, list[str]] = {}
    for slot in slots:
        days.setdefault(slot.start.strftime("%a"), []).append(slot.programme.title)
    return days


def test_week_shuffle_gives_a_new_order() -> None:
    programmes = [programme(name, 6) for name in "abcdefghij"]
    plain, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [])
    shuffled, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [], ChannelShuffle(week="x1"))
    assert titles_by_day(plain) != titles_by_day(shuffled)


def test_day_shuffle_changes_only_that_day() -> None:
    programmes = [programme(name, 6) for name in "abcdefghij"]
    week = ChannelShuffle(week="x1")
    plain, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [], week)
    one_day = ChannelShuffle(week="x1", days={MONDAY.date().replace(day=21): "y1"})
    shuffled, _ = generate_channel_week(channel(PlayOrder.SHUFFLE), programmes, MONDAY, UTC, 0, [], one_day)
    before, after = titles_by_day(plain), titles_by_day(shuffled)
    assert before["Wed"] != after["Wed"]
    assert {day: titles for day, titles in before.items() if day != "Wed"} == {day: titles for day, titles in after.items() if day != "Wed"}


def test_generator_fills_around_edited_slots() -> None:
    edited = Slot(id="e", channel_id="c1", start=MONDAY.replace(hour=18, minute=20), end=MONDAY.replace(hour=18, minute=40),
                  programme=None, edited=True)
    hours = {day: None for day in Weekday} | {Weekday.MON: OpenHours(start="18:00", end="19:00")}
    slots, _ = generate_channel_week(channel(PlayOrder.IN_ORDER, hours), [programme("a", 20)], MONDAY, UTC, 0, [edited])
    assert [slot.start.strftime("%H:%M") for slot in slots] == ["18:00", "18:40"]


def test_free_intervals() -> None:
    taken = [Slot(id="x", channel_id="c", start=MONDAY.replace(hour=1), end=MONDAY.replace(hour=2), programme=None, edited=True)]
    assert free_intervals(MONDAY, MONDAY.replace(hour=3), taken) == [
        (MONDAY, MONDAY.replace(hour=1)), (MONDAY.replace(hour=2), MONDAY.replace(hour=3)),
    ]


def test_empty_pool_gives_no_slots() -> None:
    assert generate_channel_week(channel(PlayOrder.IN_ORDER), [], MONDAY, UTC, 0, []) == ([], 0)


# ---- Service and API ----

WEDNESDAY_1830 = datetime(2026, 10, 21, 18, 30)


@pytest.fixture
def guide_services(services: Services, admin_client: TestClient) -> Services:
    """Setup done (time zone Europe/London), clock on Wednesday 18:30, all box files 20 minutes long."""
    library = services.library.library
    files = [film.fingerprint for film in library.films]
    files += [episode.fingerprint for show in library.shows for episode in show.episodes]
    files += [track.fingerprint for album in library.albums for track in album.tracks]
    for fingerprint in files:
        services.durations.record(fingerprint, 20 * 60)
    services.guide.clock = lambda zone: WEDNESDAY_1830.replace(tzinfo=zone)
    return services


def channel_body(name: str, kind: str, pool: list[dict], order: str = "in_order", start: str = "18:00", end: str = "20:00") -> dict:
    return {"name": name, "kind": kind, "order": order, "pool": pool,
            "hours": {day: {"start": start, "end": end} for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}}


def show_id(services: Services) -> str:
    return services.library.library.shows[0].id


def test_shows_are_scanned(guide_services: Services) -> None:
    show = guide_services.library.library.shows[0]
    assert show.title == "Bluey"
    assert [(episode.season, episode.number, episode.title) for episode in show.episodes] == [
        (1, 1, "The Pool"), (1, 2, "Hospital"), (2, 3, "Bike"),
    ]


def test_create_channel_fills_the_guide(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    response = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}]))
    assert response.status_code == 200, response.text

    guide = box_client.get("/box/guide").json()
    assert guide["day"] == "2026-10-21"
    cartoons = guide["channels"][0]
    assert cartoons["name"] == "Cartoons"
    assert [slot["start"][11:16] for slot in cartoons["slots"]] == ["18:00", "18:20", "18:40", "19:00", "19:20", "19:40"]
    assert cartoons["slots"][0]["subtitle"].startswith("S")
    assert guide["game_windows"][0]["start"][11:16] == "16:00"
    assert guide["bedtime"][11:16] == "19:30"


def test_episodes_continue_through_the_week(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}]))
    monday = box_client.get("/box/guide", params={"day": "2026-10-19"}).json()["channels"][0]["slots"]
    tuesday = box_client.get("/box/guide", params={"day": "2026-10-20"}).json()["channels"][0]["slots"]
    # 6 slots a day, 3 episodes: Monday ends on episode 3, so Tuesday starts with episode 1 again.
    assert monday[0]["subtitle"] == "S1 E1 · The Pool"
    assert tuesday[0]["subtitle"] == "S1 E1 · The Pool"
    assert monday[2]["subtitle"] == "S2 E3 · Bike"


def test_now_playing_gives_offset(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    channel = admin_client.post("/api/admin/channels", json=channel_body("Films", "video", [{"kind": "film", "id": guide_services.library.library.films[0].id}])).json()
    now = box_client.get(f"/box/channels/{channel['id']}/now").json()
    assert now["slot"]["start"][11:16] == "18:20"
    assert now["offset_seconds"] == 600
    assert now["path"].endswith("Frozen (2013).mkv")
    assert now["next"]["start"][11:16] == "18:40"


def test_closed_channel_has_no_programme_now(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    body = channel_body("Morning", "video", [{"kind": "show", "id": show_id(guide_services)}], start="07:00", end="08:00")
    channel = admin_client.post("/api/admin/channels", json=body).json()
    now = box_client.get(f"/box/channels/{channel['id']}/now").json()
    assert (now["slot"], now["path"]) == (None, None)
    assert now["next"]["start"].startswith("2026-10-22T07:00")


def test_hidden_programmes_do_not_air(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    show = show_id(guide_services)
    channel = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show}])).json()
    guide_services.store.set_hidden(show, True)
    assert box_client.get(f"/box/channels/{channel['id']}/now").json()["slot"] is None
    assert box_client.get("/box/guide").json()["channels"][0]["slots"] == []


def test_music_channel_only_takes_albums(guide_services: Services, admin_client: TestClient) -> None:
    film = guide_services.library.library.films[0].id
    assert admin_client.post("/api/admin/channels", json=channel_body("Songs", "music", [{"kind": "film", "id": film}])).status_code == 422
    album = guide_services.library.library.albums[0].id
    assert admin_client.post("/api/admin/channels", json=channel_body("Songs", "music", [{"kind": "album", "id": album}])).status_code == 200


def todays_slots(client: TestClient, channel_id: str) -> list[dict]:
    """Today's column of the admin app's week table."""
    week = client.get("/api/admin/guide/week", params={"channel_id": channel_id}).json()
    return [slot for slot in week["slots"] if slot["start"].startswith(week["today"])]


def test_edit_slots_survive_regeneration(guide_services: Services, admin_client: TestClient) -> None:
    channel = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}])).json()
    slots = todays_slots(admin_client, channel["id"])
    first, second = slots[0], slots[1]

    admin_client.post(f"/api/admin/guide/slots/{second['id']}/clear", json={"start": second["start"]})
    film_ref = f"film:{guide_services.library.library.films[0].id}"
    placed = admin_client.post("/api/admin/guide/slots", json={
        "channel_id": channel["id"], "start": first["start"], "ref": film_ref, "replace_slot_id": first["id"],
    })
    assert placed.status_code == 200, placed.text
    admin_client.post("/api/admin/guide/generate")

    slots = todays_slots(admin_client, channel["id"])
    assert (slots[0]["ref"], slots[0]["edited"]) == (film_ref, True)
    assert (slots[1]["title"], slots[1]["edited"]) == (None, True)

    overlap = admin_client.post("/api/admin/guide/slots", json={
        "channel_id": channel["id"], "start": slots[0]["start"][:11] + "18:10:00+01:00", "ref": film_ref,
    })
    assert overlap.status_code == 422

    admin_client.post(f"/api/admin/guide/slots/{slots[1]['id']}/restore", json={"start": slots[1]["start"]})
    slots = todays_slots(admin_client, channel["id"])
    assert slots[1]["title"] == "Bluey" and slots[1]["edited"] is False


def test_pool_and_programme_choices(guide_services: Services, admin_client: TestClient) -> None:
    pool = admin_client.get("/api/admin/pool").json()
    assert {item["kind"] for item in pool} == {"film", "show", "album"}
    choices = admin_client.get("/api/admin/programmes", params={"kind": "music"}).json()
    assert [choice["title"] for choice in choices] == ["Opening", "Second Song"]
    assert choices[0]["minutes"] == 20


def test_delete_channel(guide_services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    channel = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}])).json()
    admin_client.delete(f"/api/admin/channels/{channel['id']}")
    assert box_client.get("/box/guide").json()["channels"] == []


def test_guide_without_setup_has_no_limits(services: Services, box_client: TestClient) -> None:
    services.guide.clock = lambda zone: WEDNESDAY_1830.replace(tzinfo=zone)
    guide = box_client.get("/box/guide").json()
    assert (guide["game_windows"], guide["bedtime"]) == ([], None)


def test_week_view_has_one_channel(guide_services: Services, admin_client: TestClient) -> None:
    cartoons = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}])).json()
    admin_client.post("/api/admin/channels", json=channel_body("Films", "video", [{"kind": "film", "id": guide_services.library.library.films[0].id}]))

    week = admin_client.get("/api/admin/guide/week", params={"channel_id": cartoons["id"], "day": "2026-10-24"}).json()

    assert (week["week_start"], week["today"], week["channel"]["name"]) == ("2026-10-19", "2026-10-21", "Cartoons")
    assert week["days"][0] == "2026-10-19" and week["days"][6] == "2026-10-25"
    assert {slot["channel_id"] for slot in week["slots"]} == {cartoons["id"]}
    assert len(week["slots"]) == 7 * 6
    assert admin_client.get("/api/admin/guide/week", params={"channel_id": "nope"}).status_code == 404


def shuffle_channel(services: Services, admin_client: TestClient) -> dict:
    body = channel_body("Mixed", "video", [{"kind": "show", "id": show_id(services)}], order="shuffle")
    return admin_client.post("/api/admin/channels", json=body).json()


def week_slots(admin_client: TestClient, channel_id: str) -> list[dict]:
    return admin_client.get("/api/admin/guide/week", params={"channel_id": channel_id, "day": "2026-10-21"}).json()["slots"]


def test_day_shuffle_keeps_other_days_and_edits(guide_services: Services, admin_client: TestClient) -> None:
    channel = shuffle_channel(guide_services, admin_client)
    wednesday_first = next(slot for slot in week_slots(admin_client, channel["id"]) if slot["start"].startswith("2026-10-21"))
    admin_client.post(f"/api/admin/guide/slots/{wednesday_first['id']}/clear", json={"start": wednesday_first["start"]})
    # Emptying a slot does not fill the week again, so fill it here for a fair "before".
    admin_client.post("/api/admin/guide/generate")
    before = week_slots(admin_client, channel["id"])

    response = admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-21", "whole_week": False})
    assert response.status_code == 200, response.text

    after = week_slots(admin_client, channel["id"])
    not_wednesday = lambda slots: [(slot["start"], slot["subtitle"]) for slot in slots if not slot["start"].startswith("2026-10-21")]
    assert not_wednesday(after) == not_wednesday(before)
    emptied = next(slot for slot in after if slot["id"] == wednesday_first["id"])
    assert (emptied["title"], emptied["edited"]) == (None, True)
    schedule = guide_services.guide.week(week_start_for(guide_services.guide.now()))
    assert set(schedule.shuffles[channel["id"]].days) == {WEDNESDAY_1830.date()}


def test_shuffles_survive_filling_the_week_again(guide_services: Services, admin_client: TestClient) -> None:
    channel = shuffle_channel(guide_services, admin_client)
    admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-21", "whole_week": True})
    admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-22", "whole_week": False})
    shuffled = week_slots(admin_client, channel["id"])

    admin_client.post("/api/admin/guide/generate")

    assert week_slots(admin_client, channel["id"]) == shuffled


def test_week_shuffle_clears_day_shuffles(guide_services: Services, admin_client: TestClient) -> None:
    channel = shuffle_channel(guide_services, admin_client)
    admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-22", "whole_week": False})
    admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-22", "whole_week": True})
    shuffle = guide_services.guide.week(week_start_for(guide_services.guide.now())).shuffles[channel["id"]]
    assert shuffle.week and shuffle.days == {}


def test_in_order_channel_cannot_be_shuffled(guide_services: Services, admin_client: TestClient) -> None:
    channel = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}])).json()
    response = admin_client.post("/api/admin/guide/shuffle", json={"channel_id": channel["id"], "day": "2026-10-21", "whole_week": True})
    assert response.status_code == 422


def test_place_at_a_clicked_time_uses_the_box_time_zone(guide_services: Services, admin_client: TestClient) -> None:
    channel = admin_client.post("/api/admin/channels", json=channel_body("Cartoons", "video", [{"kind": "show", "id": show_id(guide_services)}])).json()
    film_ref = f"film:{guide_services.library.library.films[0].id}"

    placed = admin_client.post("/api/admin/guide/slots", json={"channel_id": channel["id"], "start": "2026-10-21T19:05:00", "ref": film_ref})

    assert placed.status_code == 200, placed.text
    slot = next(slot for slot in week_slots(admin_client, channel["id"]) if slot["ref"] == film_ref)
    assert (slot["start"], slot["edited"]) == ("2026-10-21T19:05:00+01:00", True)
