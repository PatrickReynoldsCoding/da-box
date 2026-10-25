"""Posters and info (DESIGN_CORRECTIONS_2.md, part 4): groups found as TV series, keys set and
checked from the TV, the status, Look up now, ScreenScraper, fixing a match, and the proxy."""

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from dabox.background import BackgroundWorkers
from dabox.library import item_id
from dabox.metadata import SOURCE_URLS, HttpError, MetadataStatus, search_terms
from dabox.services import Services
from tests.conftest import JPEG_BYTES, FakeHttp, write_file

KEY = "k" * 32
TMDB = "https://api.themoviedb.org/3"
PROXY_FILTER = Path(__file__).parents[2] / "install" / "files" / "dabox-filter"


def tmdb(fake_http: FakeHttp, movies: list[dict], series: list[dict]) -> None:
    fake_http.responses.update({
        f"{TMDB}/configuration": {"images": {}},
        f"{TMDB}/search/movie": {"results": movies},
        f"{TMDB}/search/tv": {"results": series},
        "https://image.tmdb.org/t/p/": JPEG_BYTES,
    })


def series(number: int, name: str, year: str = "2018") -> dict:
    return {"id": number, "name": name, "first_air_date": f"{year}-10-01", "overview": f"About {name}", "poster_path": f"/s{number}.jpg"}


def movie(number: int, title: str, year: str = "2001") -> dict:
    return {"id": number, "title": title, "release_date": f"{year}-01-01", "overview": f"About {title}", "poster_path": f"/m{number}.jpg"}


@pytest.mark.parametrize(("title", "terms"), [
    ("Fargo (2014) Season 5", ("Fargo", 2014)),
    ("Bluey", ("Bluey", None)),
    ("Bluey S02", ("Bluey", None)),
    ("Frozen (2013)", ("Frozen", 2013)),
    ("Guitar Heroes at the BBC, 2010", ("Guitar Heroes at the BBC, 2010", None)),
    ("Season 1", ("Season 1", None)),
])
def test_search_terms(title: str, terms: tuple[str, int | None]) -> None:
    assert search_terms(title) == terms


def test_a_group_is_looked_up_as_a_tv_series(services: Services, box_client: TestClient, completed_setup: None, fake_http: FakeHttp) -> None:
    tmdb(fake_http, movies=[movie(1, "Bluey: The Movie")], series=[series(7, "Bluey")])
    fake_http.responses[f"{TMDB}/tv/7?"] = series(7, "Bluey")
    fake_http.responses[f"{TMDB}/tv/7/images"] = {"posters": [{"file_path": "/s7.jpg"}]}
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": KEY})

    BackgroundWorkers(services).fetch_metadata_once()

    group_id = item_id("show", "TV/Bluey")
    record = services.metadata.store.get(group_id)
    # Bluey has its own poster.jpg, so it is not fetched; Home Movie and others are.
    assert record is None
    services.metadata.store.delete(group_id)
    services.metadata.auto_fetch(services.library.find_show(group_id))
    record = services.metadata.store.get(group_id)
    assert (record.status, record.provider_id, record.title, record.year) == (MetadataStatus.MATCHED, "tv:7", "Bluey", 2018)
    tile = next(tile for tile in box_client.get("/box/videos").json() if tile["id"] == group_id)
    assert (tile["title"], tile["year"]) == ("Bluey", 2018)
    assert any("/search/tv?query=Bluey" in url for url in fake_http.requested)


def test_an_exact_title_wins_over_the_preferred_kind(services: Services, fake_http: FakeHttp, admin_client: TestClient) -> None:
    tmdb(fake_http, movies=[movie(2, "Fargo 2")], series=[series(9, "Fargo", "2014")])
    admin_client.put("/api/admin/accounts", json={"tmdb_api_key": KEY})
    film = next(film for film in services.library.library.films if film.title == "Home Movie")
    titles = [candidate.title for candidate in services.metadata.search(film, "Fargo", None, None)]
    assert titles == ["Fargo", "Fargo 2"]


def accounts_by_key(client: TestClient) -> dict[str, dict]:
    return {account["key"]: account for account in client.get("/box/posters").json()["accounts"]}


def test_account_states(box_client: TestClient, completed_setup: None, fake_http: FakeHttp) -> None:
    accounts = accounts_by_key(box_client)
    assert [accounts[key]["state"] for key in ("tmdb", "musicbrainz", "libretro", "screenscraper")] == [
        "not_set", "not_needed", "not_needed", "not_set",
    ]
    # A wrong key: TMDB answers 401.
    fake_http.responses[f"{TMDB}/configuration"] = HttpError(401, "x")
    status = box_client.put("/box/posters/accounts", json={"tmdb_api_key": "wrong"}).json()
    tmdb_view = next(account for account in status["accounts"] if account["key"] == "tmdb")
    assert (tmdb_view["state"], tmdb_view["reason"]) == ("not_working", "The key or password is wrong.")
    # The right key.
    fake_http.responses[f"{TMDB}/configuration"] = {"images": {}}
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": KEY})
    assert accounts_by_key(box_client)["tmdb"]["state"] == "working"
    # An empty key removes it.
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": ""})
    assert accounts_by_key(box_client)["tmdb"]["state"] == "not_set"


def test_keys_are_never_sent_back(box_client: TestClient, admin_client: TestClient, fake_http: FakeHttp) -> None:
    tmdb(fake_http, [], [])
    secret = "s3cr3t-key-" + "x" * 21
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": secret, "screenscraper_password": "hunter2"})
    for response in (box_client.get("/box/posters"), admin_client.get("/api/admin/posters"), admin_client.get("/api/admin/accounts")):
        assert secret not in response.text and "hunter2" not in response.text


def test_status_counts_last_error_and_look_up_now(
    services: Services, box_client: TestClient, completed_setup: None, fake_http: FakeHttp,
) -> None:
    workers = BackgroundWorkers(services)
    workers.fetch_metadata_once()
    status = box_client.get("/box/posters").json()
    # Home Movie waits for a TMDB key; Frozen and Bluey have their own posters; the album has a cover.
    assert (status["done"], status["no_account"], status["waiting"]) == (3, 1, 0)

    # With a key, but TMDB is down: the fetch fails and says why.
    fake_http.responses[f"{TMDB}/configuration"] = {"images": {}}
    fake_http.responses[f"{TMDB}/search"] = OSError("network down")
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": KEY})
    workers.fetch_metadata_once()
    status = box_client.get("/box/posters").json()
    assert status["failed"] == 1
    assert status["last_error"] == "Home Movie: No internet, or the site cannot be reached."

    # TMDB is back: Look up now tries again.
    tmdb(fake_http, movies=[movie(1, "Home Movie")], series=[])
    fake_http.responses[f"{TMDB}/movie/1?"] = movie(1, "Home Movie")
    fake_http.responses[f"{TMDB}/movie/1/images"] = {"posters": [{"file_path": "/m1.jpg"}]}
    status = box_client.post("/box/posters/lookup").json()
    assert (status["failed"], status["waiting"], status["last_error"]) == (0, 1, None)
    workers.fetch_metadata_once()
    assert box_client.get("/box/posters").json()["done"] == 4


def test_settings_routes_need_no_parent_mode_but_stay_on_the_box(
    box_client: TestClient, phone_client: TestClient, services: Services, completed_setup: None,
) -> None:
    assert services.box_state.parent_mode is False
    assert box_client.get("/box/posters").status_code == 200
    assert box_client.post("/box/posters/lookup").status_code == 200
    assert phone_client.get("/box/posters").status_code == 403
    assert phone_client.put("/box/posters/accounts", json={"tmdb_api_key": "x"}).status_code == 403


SCREENSCRAPER_GAME = {"response": {"jeu": {
    "id": "1234",
    "noms": [{"region": "jp", "text": "Rokketto"}, {"region": "us", "text": "Rocket Rider"}],
    "dates": [{"region": "us", "text": "1990-05-01"}],
    "synopsis": [{"langue": "fr", "text": "Une fusée."}, {"langue": "en", "text": "A rocket game."}],
}}}


def test_screenscraper_adds_game_descriptions(
    services: Services, box_client: TestClient, completed_setup: None, fake_http: FakeHttp, tmp_path: Path,
) -> None:
    write_file(services.library.media_dir / "Games" / "nes" / "Rocket.nes", b"rom")
    services.rescan_library()
    game = next(game for game in services.library.library.games if game.title == "Rocket")
    fake_http.responses["https://thumbnails.libretro.com/"] = JPEG_BYTES

    # Without an account: box art only.
    services.metadata.auto_fetch(game)
    assert services.metadata.store.get(game.id).plot is None

    fake_http.responses["https://api.screenscraper.fr/api2/ssuserInfos.php"] = {"response": {"ssuser": {"id": "me"}}}
    fake_http.responses["https://api.screenscraper.fr/api2/jeuInfos.php"] = SCREENSCRAPER_GAME
    box_client.put("/box/posters/accounts", json={
        "screenscraper_user": "me", "screenscraper_password": "pw", "screenscraper_dev_id": "dev", "screenscraper_dev_password": "devpw",
    })
    assert accounts_by_key(box_client)["screenscraper"]["state"] == "working"
    services.metadata.store.delete(game.id)
    record = services.metadata.auto_fetch(game)
    assert (record.title, record.year, record.plot, record.provider) == ("Rocket Rider", 1990, "A rocket game.", "screenscraper")
    assert record.art_file is not None
    lookup = next(url for url in fake_http.requested if "jeuInfos.php" in url)
    assert "systemeid=3" in lookup and "romnom=Rocket.nes" in lookup and "devid=dev" in lookup


def test_screenscraper_without_the_game_keeps_the_box_art(services: Services, fake_http: FakeHttp) -> None:
    write_file(services.library.media_dir / "Games" / "nes" / "Rocket.nes", b"rom")
    services.rescan_library()
    game = next(game for game in services.library.library.games if game.title == "Rocket")
    fake_http.responses["https://thumbnails.libretro.com/"] = JPEG_BYTES
    services.metadata.save_accounts(services.metadata.store.accounts().model_copy(update={
        "screenscraper_user": "me", "screenscraper_password": "pw", "screenscraper_dev_id": "dev", "screenscraper_dev_password": "devpw",
    }))
    record = services.metadata.auto_fetch(game)
    assert (record.provider, record.plot) == ("libretro-thumbnails", None)


def test_fix_a_match_on_the_tv_needs_parent_mode(
    services: Services, box_client: TestClient, completed_setup: None, fake_http: FakeHttp,
) -> None:
    tmdb(fake_http, movies=[], series=[series(7, "Bluey")])
    fake_http.responses[f"{TMDB}/tv/7?"] = series(7, "Bluey")
    fake_http.responses[f"{TMDB}/tv/7/images"] = {"posters": []}
    box_client.put("/box/posters/accounts", json={"tmdb_api_key": KEY})
    group_id = item_id("show", "TV/Bluey")

    assert box_client.post(f"/box/content/{group_id}/metadata/search", json={"title": "Bluey"}).status_code == 403
    services.box_state.set_parent_mode(True)
    candidates = box_client.post(f"/box/content/{group_id}/metadata/search", json={"title": "Bluey"}).json()
    assert [(candidate["title"], candidate["provider_id"]) for candidate in candidates] == [("Bluey", "tv:7")]
    applied = box_client.post(f"/box/content/{group_id}/metadata/apply", json=candidates[0]).json()
    assert (applied["status"], applied["title"]) == ("matched", "Bluey")


def test_the_admin_app_edits_a_group(admin_client: TestClient) -> None:
    group_id = item_id("show", "TV/Bluey")
    edited = admin_client.put(f"/api/admin/content/{group_id}/metadata", json={"title": "Bluey!", "year": 2018, "plot": "Dogs"})
    assert edited.status_code == 200 and edited.json()["title"] == "Bluey!"


def test_the_qr_code_can_open_the_accounts_form(box_client: TestClient) -> None:
    plain = box_client.get("/box/admin-qr.png")
    accounts = box_client.get("/box/admin-qr.png?target=accounts")
    assert accounts.headers["content-type"] == "image/png" and accounts.content != plain.content


def _allowed_hosts() -> list[re.Pattern[str]]:
    return [re.compile(line.strip()) for line in PROXY_FILTER.read_text().splitlines() if line.strip() and not line.startswith("#")]


@pytest.mark.parametrize("url", [*SOURCE_URLS, "https://api.github.com/repos/x/y/releases/latest"])
def test_the_proxy_lets_every_source_through(url: str) -> None:
    host = urlparse(url).hostname
    assert any(pattern.search(host) for pattern in _allowed_hosts()), f"{host} is not in install/files/dabox-filter"
