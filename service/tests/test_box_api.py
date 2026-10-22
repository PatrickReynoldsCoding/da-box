from fastapi.testclient import TestClient

from dabox.services import Services
from dabox.system import FakeTimezone
from tests.conftest import TEST_PIN, limits_payload, setup_payload


def test_box_api_rejects_the_network(phone_client: TestClient) -> None:
    for path in ("/box/state", "/box/films", "/box/setup/timezones"):
        assert phone_client.get(path).status_code == 403


def test_state_before_setup(box_client: TestClient) -> None:
    state = box_client.get("/box/state").json()
    assert state["setup_required"] is True
    assert state["parent_mode"] is False
    assert state["admin_urls"][0].startswith("http://") and state["admin_urls"][0].endswith(".local")


def test_complete_setup(box_client: TestClient, services: Services, timezone_backend: FakeTimezone) -> None:
    response = box_client.post("/box/setup/complete", json=setup_payload())

    assert response.status_code == 200
    assert response.json()["setup_required"] is False
    assert timezone_backend.timezone == "Europe/London"
    assert services.auth.check_pin(TEST_PIN)
    assert services.box_state.limits().daily_quota_minutes == 120


def test_setup_cannot_run_twice(box_client: TestClient, completed_setup: None) -> None:
    assert box_client.post("/box/setup/complete", json=setup_payload()).status_code == 409
    assert box_client.get("/box/setup/network").status_code == 409


def test_setup_rejects_bad_input(box_client: TestClient) -> None:
    missing_day = setup_payload()
    del missing_day["limits"]["bedtimes"]["sun"]
    backwards_window = setup_payload()
    backwards_window["limits"]["game_windows"]["mon"] = {"start": "18:00", "end": "16:00"}
    bad_pin = setup_payload() | {"pin": "12a4"}
    bad_zone = setup_payload() | {"timezone": "Mars/Base"}

    for payload in (missing_day, backwards_window, bad_pin, bad_zone):
        assert box_client.post("/box/setup/complete", json=payload).status_code == 422


def test_setup_wifi_flow(box_client: TestClient) -> None:
    assert box_client.get("/box/setup/network").json()["wifi_available"] is True
    assert box_client.get("/box/setup/wifi").json()[0]["ssid"] == "Home Wi-Fi"
    assert box_client.post("/box/setup/wifi", json={"ssid": "Home Wi-Fi", "password": "short"}).json()["connected"] is False
    assert box_client.post("/box/setup/wifi", json={"ssid": "Home Wi-Fi", "password": "long enough"}).json()["connected"]


def test_films_and_albums(box_client: TestClient) -> None:
    films = box_client.get("/box/films").json()
    assert [film["title"] for film in films] == ["Frozen", "Home Movie"]
    assert films[0]["art_url"] == f"/box/art/{films[0]['id']}"
    assert box_client.get(films[0]["art_url"]).status_code == 200

    albums = box_client.get("/box/music/albums").json()
    assert albums[0]["track_count"] == 2
    detail = box_client.get(f"/box/music/albums/{albums[0]['id']}").json()
    assert [track["title"] for track in detail["tracks"]] == ["Opening", "Second Song"]


def test_hidden_items_show_only_in_parent_mode(box_client: TestClient, services: Services) -> None:
    frozen_id = box_client.get("/box/films").json()[0]["id"]
    services.store.set_hidden(frozen_id, True)

    assert [film["title"] for film in box_client.get("/box/films").json()] == ["Home Movie"]

    services.box_state.set_parent_mode(True)
    films = box_client.get("/box/films").json()
    assert [(film["title"], film["hidden"]) for film in films] == [("Frozen", True), ("Home Movie", False)]

    box_client.post("/box/parent-mode/leave")
    assert services.box_state.parent_mode is False


def test_admin_qr_is_png(box_client: TestClient) -> None:
    response = box_client.get("/box/admin-qr.png")
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_parent_mode_turns_off_at_start_up(services: Services) -> None:
    from dabox.app import create_app
    from tests.conftest import BOX_ADDRESS

    services.box_state.set_parent_mode(True)
    with TestClient(create_app(services, run_workers=False), client=BOX_ADDRESS) as client:
        assert client.get("/box/state").json()["parent_mode"] is False


def test_limits_payload_is_complete() -> None:
    assert set(limits_payload()["bedtimes"]) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
