from fastapi.testclient import TestClient

from dabox.background import BackgroundWorkers
from dabox.metadata import MetadataStatus, is_allowed_art_url
from dabox.services import Services
from tests.conftest import JPEG_BYTES, FakeHttp

TMDB_SEARCH = {
    "results": [
        {"id": 1, "title": "Home Movie: The Return", "release_date": "2001-05-01", "overview": "A film.", "poster_path": "/p1.jpg"},
        {"id": 2, "title": "Other", "release_date": "", "overview": "", "poster_path": None},
    ]
}
TMDB_DETAILS = {"title": "Home Movie: The Return", "release_date": "2001-05-01", "overview": "A film."}
TMDB_IMAGES = {"posters": [{"file_path": "/p1.jpg"}, {"file_path": "/p2.jpg"}]}
MUSICBRAINZ_SEARCH = {
    "release-groups": [
        {"id": "rg-1", "title": "First Album", "first-release-date": "1999", "primary-type": "Album",
         "artist-credit": [{"name": "The Band"}]},
    ]
}
COVER_ART = {"images": [{"image": "http://coverartarchive.org/release/x/1.jpg",
                         "thumbnails": {"250": "http://coverartarchive.org/release/x/1-250.jpg",
                                        "1200": "http://coverartarchive.org/release/x/1-1200.jpg"}}]}


def add_tmdb_responses(fake_http: FakeHttp) -> None:
    fake_http.responses.update({
        "https://api.themoviedb.org/3/search/movie": TMDB_SEARCH,
        "https://api.themoviedb.org/3/movie/1?": TMDB_DETAILS,
        "https://api.themoviedb.org/3/movie/1/images": TMDB_IMAGES,
        "https://image.tmdb.org/t/p/": JPEG_BYTES,
    })


def add_musicbrainz_responses(fake_http: FakeHttp) -> None:
    fake_http.responses.update({
        "https://musicbrainz.org/ws/2/release-group/": MUSICBRAINZ_SEARCH,
        "https://coverartarchive.org/release-group/rg-1": COVER_ART,
        "https://coverartarchive.org/release/": JPEG_BYTES,
    })


def film_id(client: TestClient, title: str) -> str:
    return next(film["id"] for film in client.get("/api/admin/content").json()["films"] if film["title"].startswith(title))


def test_allowed_art_urls() -> None:
    assert is_allowed_art_url("https://image.tmdb.org/t/p/w780/x.jpg")
    assert is_allowed_art_url("https://ia800.us.archive.org/x.jpg")
    assert not is_allowed_art_url("http://image.tmdb.org/x.jpg")
    assert not is_allowed_art_url("https://evil.example/archive.org.jpg")


def test_auto_fetch_only_items_without_own_art(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    to_fetch = services.metadata.items_to_fetch([*services.library.library.films, *services.library.library.albums])
    # Frozen and the album have their own art. Only "Home Movie" needs fetching.
    assert [item.title for item in to_fetch] == ["Home Movie"]


def test_films_wait_for_a_tmdb_key_then_fetch(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    workers = BackgroundWorkers(services)
    workers.fetch_metadata_once()
    home_id = film_id(admin_client, "Home Movie")
    assert services.metadata.store.get(home_id).status is MetadataStatus.NO_ACCOUNT
    assert fake_http.requested == []

    add_tmdb_responses(fake_http)
    assert admin_client.put("/api/admin/accounts", json={"tmdb_api_key": "k" * 32}).json() == {"tmdb_api_key_set": True}
    workers.fetch_metadata_once()

    film = next(film for film in admin_client.get("/api/admin/content").json()["films"] if film["id"] == home_id)
    assert (film["title"], film["year"], film["plot"], film["metadata_status"]) == ("Home Movie: The Return", 2001, "A film.", "matched")
    assert admin_client.get(film["art_url"]).content == JPEG_BYTES
    assert "api_key=" + "k" * 32 in fake_http.requested[0]


def test_v4_token_uses_bearer_header(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    add_tmdb_responses(fake_http)
    admin_client.put("/api/admin/accounts", json={"tmdb_api_key": "t" * 200})
    response = admin_client.post(f"/api/admin/content/{film_id(admin_client, 'Home')}/metadata/search", json={"title": "Home"})
    assert response.status_code == 200
    assert "api_key" not in fake_http.requested[0]


def test_search_pick_and_choose_art(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    add_tmdb_responses(fake_http)
    admin_client.put("/api/admin/accounts", json={"tmdb_api_key": "k" * 32})
    item_id = film_id(admin_client, "Frozen")

    candidates = admin_client.post(f"/api/admin/content/{item_id}/metadata/search", json={"title": "Home", "year": 2001}).json()
    assert [candidate["title"] for candidate in candidates] == ["Home Movie: The Return", "Other"]
    assert candidates[0]["preview_url"] == "https://image.tmdb.org/t/p/w185/p1.jpg"

    applied = admin_client.post(f"/api/admin/content/{item_id}/metadata/apply", json=candidates[0]).json()
    assert applied["provider_id"] == "1"

    options = admin_client.get(f"/api/admin/content/{item_id}/metadata/art-options").json()
    assert [option["full_url"] for option in options] == [
        "https://image.tmdb.org/t/p/w780/p1.jpg", "https://image.tmdb.org/t/p/w780/p2.jpg"
    ]
    assert admin_client.post(f"/api/admin/content/{item_id}/metadata/art", json={"url": options[1]["full_url"]}).status_code == 200
    assert admin_client.post(f"/api/admin/content/{item_id}/metadata/art", json={"url": "https://evil.example/x.jpg"}).status_code == 422


def test_search_films_without_key_explains(admin_client: TestClient) -> None:
    response = admin_client.post(f"/api/admin/content/{film_id(admin_client, 'Frozen')}/metadata/search", json={})
    assert response.status_code == 422
    assert "TMDB" in response.json()["detail"]


def test_album_search_and_apply(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    add_musicbrainz_responses(fake_http)
    album_id = admin_client.get("/api/admin/content").json()["albums"][0]["id"]

    candidates = admin_client.post(f"/api/admin/content/{album_id}/metadata/search", json={"title": "First Album"}).json()
    assert candidates[0]["artist"] == "The Band"
    applied = admin_client.post(f"/api/admin/content/{album_id}/metadata/apply", json=candidates[0]).json()

    assert (applied["year"], applied["art_file"]) == (1999, f"{album_id}.jpg")
    assert any(url.startswith("https://coverartarchive.org/release/x/1-1200.jpg") for url in fake_http.requested)


def test_edit_upload_and_reset(services: Services, admin_client: TestClient, box_client: TestClient) -> None:
    item_id = film_id(admin_client, "Frozen")
    admin_client.put(f"/api/admin/content/{item_id}/metadata", json={"title": "Frozen (sing-along)", "year": 2013, "plot": "Snow."})
    upload = admin_client.post(
        f"/api/admin/content/{item_id}/metadata/art-upload", files={"image": ("a.png", b"\x89PNG rest", "image/png")}
    )
    assert upload.json()["art_file"] == f"{item_id}.png"
    bad = admin_client.post(f"/api/admin/content/{item_id}/metadata/art-upload", files={"image": ("a.txt", b"hello", "text/plain")})
    assert bad.status_code == 422

    film = next(film for film in box_client.get("/box/films").json() if film["id"] == item_id)
    assert (film["title"], film["plot"]) == ("Frozen (sing-along)", "Snow.")
    assert box_client.get(film["art_url"]).content == b"\x89PNG rest"

    admin_client.delete(f"/api/admin/content/{item_id}/metadata")
    film = next(film for film in box_client.get("/box/films").json() if film["id"] == item_id)
    assert film["title"] == "Frozen"
    assert box_client.get(film["art_url"]).content.startswith(b"\xff\xd8\xff")


def test_failed_fetch_is_recorded(services: Services, admin_client: TestClient, fake_http: FakeHttp) -> None:
    admin_client.put("/api/admin/accounts", json={"tmdb_api_key": "k" * 32})
    BackgroundWorkers(services).fetch_metadata_once()
    record = services.metadata.store.get(film_id(admin_client, "Home"))
    assert record.status is MetadataStatus.FAILED
