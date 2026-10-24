from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox.background import BackgroundWorkers
from dabox.services import Services
from tests.conftest import write_file


@pytest.fixture
def music(services: Services, admin_client: TestClient, box_client: TestClient, media_dir: Path, usb_root: Path) -> TestClient:
    """The box's "The Band - First Album", another box album, and an album on a USB stick."""
    write_file(media_dir / "Music" / "Blue Artist" / "Blue Album" / "01 Blue Song.mp3", b"blue song")
    write_file(media_dir / "Music" / "Blue Artist" / "Blue Album" / "02 After.mp3", b"after song")
    write_file(usb_root / "STICK" / "Music" / "Stick Band" / "Stick Album" / "01 Stick Song.mp3", b"stick song")
    BackgroundWorkers(services).check_usb_once()
    return box_client


def song_ids(client: TestClient, prefix: str = "/box/music") -> dict[str, str]:
    return {song["title"]: song["id"] for song in client.get(f"{prefix}/songs").json()}


def test_artists_and_their_albums(music: TestClient) -> None:
    artists = music.get("/box/music/artists").json()

    assert [(artist["name"], artist["album_count"]) for artist in artists] == [
        ("Blue Artist", 1), ("Stick Band", 1), ("The Band", 1),
    ]
    albums = music.get("/box/music/albums", params={"artist": "the band"}).json()
    assert [album["title"] for album in albums] == ["First Album"]


def test_songs_are_a_to_z(music: TestClient) -> None:
    songs = music.get("/box/music/songs").json()

    assert [song["title"] for song in songs] == ["After", "Blue Song", "Opening", "Second Song", "Stick Song"]
    stick_song = songs[-1]
    assert (stick_song["source"], stick_song["album"], stick_song["artist"]) == ("usb", "Stick Album", "Stick Band")


def test_search_gives_one_list_of_artists_albums_and_songs(music: TestClient) -> None:
    hits = music.get("/box/music/search", params={"q": "  BLUE "}).json()

    assert [(hit["kind"], hit["title"]) for hit in hits] == [
        ("artist", "Blue Artist"), ("album", "Blue Album"), ("song", "Blue Song"),
    ]
    assert hits[0]["artist"] == "Blue Artist"
    assert hits[1]["album_id"]
    assert hits[2]["song"]["path"].endswith("01 Blue Song.mp3")
    assert music.get("/box/music/search", params={"q": " "}).json() == []


def test_shuffle_an_album_and_all_music(music: TestClient) -> None:
    album_id = next(album["id"] for album in music.get("/box/music/albums").json() if album["title"] == "Blue Album")

    album_songs = music.get("/box/music/shuffle", params={"album_id": album_id}).json()
    everything = music.get("/box/music/shuffle").json()

    assert sorted(song["title"] for song in album_songs) == ["After", "Blue Song"]
    # Shuffle all is the music on the box, not on the stick.
    assert sorted(song["title"] for song in everything) == ["After", "Blue Song", "Opening", "Second Song"]
    assert music.get("/box/music/shuffle", params={"album_id": "nope"}).status_code == 404


def test_hidden_album_leaves_the_kid_lists(services: Services, music: TestClient) -> None:
    album_id = next(album["id"] for album in music.get("/box/music/albums").json() if album["title"] == "Blue Album")
    services.store.set_hidden(album_id, True)

    assert "Blue Song" not in song_ids(music)
    assert [hit["kind"] for hit in music.get("/box/music/search", params={"q": "blue"}).json()] == []
    services.box_state.set_parent_mode(True)
    assert "Blue Song" in song_ids(music)


def test_make_a_playlist_on_the_box(music: TestClient) -> None:
    songs = song_ids(music)

    created = music.post("/box/music/playlists", json={"name": "  Car   songs "})
    assert created.status_code == 200, created.text
    playlist = created.json()
    assert (playlist["name"], playlist["made_on"], playlist["can_change"]) == ("Car songs", "box", True)
    url = f"/box/music/playlists/{playlist['id']}"

    music.post(f"{url}/songs", json={"song_id": songs["Opening"]})
    music.post(f"{url}/songs", json={"song_id": songs["Blue Song"]})
    music.post(f"{url}/songs", json={"song_id": songs["Opening"]})
    assert [song["title"] for song in music.get(url).json()["songs"]] == ["Opening", "Blue Song"]
    # Only songs on the box.
    assert music.post(f"{url}/songs", json={"song_id": songs["Stick Song"]}).status_code == 422

    music.delete(f"{url}/songs/{songs['Opening']}")
    renamed = music.put(url, json={"name": "Road trip"}).json()
    assert ([song["title"] for song in renamed["songs"]], renamed["name"], renamed["song_count"]) == (["Blue Song"], "Road trip", 1)
    assert [entry["name"] for entry in music.get("/box/music/playlists").json()] == ["Road trip"]

    assert music.delete(url).status_code == 200
    assert music.get("/box/music/playlists").json() == []


def test_playlist_names(music: TestClient) -> None:
    assert music.post("/box/music/playlists", json={"name": "   "}).status_code == 422
    assert music.post("/box/music/playlists", json={"name": "x" * 31}).status_code == 422
    assert music.post("/box/music/playlists", json={"name": "x" * 30}).status_code == 200


def test_a_kid_changes_only_playlists_made_on_the_box(services: Services, music: TestClient, admin_client: TestClient) -> None:
    songs = song_ids(music)
    parents = admin_client.post("/api/admin/music/playlists", json={"name": "Dad's"}).json()
    kids = music.post("/box/music/playlists", json={"name": "Mine"}).json()
    parents_url = f"/box/music/playlists/{parents['id']}"

    assert [(entry["name"], entry["can_change"]) for entry in music.get("/box/music/playlists").json()] == [("Dad's", False), ("Mine", True)]
    assert music.put(parents_url, json={"name": "Ha"}).status_code == 403
    assert music.post(f"{parents_url}/songs", json={"song_id": songs["Opening"]}).status_code == 403
    assert music.delete(parents_url).status_code == 403

    services.box_state.set_parent_mode(True)
    assert music.post(f"{parents_url}/songs", json={"song_id": songs["Opening"]}).status_code == 200
    # The parent can delete a kid's playlist from the admin app.
    assert admin_client.delete(f"/api/admin/music/playlists/{kids['id']}").status_code == 200
    assert [entry["name"] for entry in admin_client.get("/api/admin/music/playlists").json()] == ["Dad's"]


def test_hidden_song_stays_on_the_playlist_but_is_skipped(services: Services, music: TestClient, admin_client: TestClient) -> None:
    songs = song_ids(admin_client, "/api/admin/music")
    playlist = admin_client.post("/api/admin/music/playlists", json={"name": "Mix"}).json()
    admin_client.put(f"/api/admin/music/playlists/{playlist['id']}/songs", json={"song_ids": [songs["Blue Song"], songs["Opening"]]})
    album_id = next(album["id"] for album in music.get("/box/music/albums").json() if album["title"] == "Blue Album")
    services.store.set_hidden(album_id, True)

    kid_view = music.get(f"/box/music/playlists/{playlist['id']}").json()
    admin_view = admin_client.get(f"/api/admin/music/playlists/{playlist['id']}").json()

    assert ([song["title"] for song in kid_view["songs"]], kid_view["song_count"]) == (["Opening"], 1)
    assert [(song["title"], song["hidden"]) for song in admin_view["songs"]] == [("Blue Song", True), ("Opening", False)]
    services.store.set_hidden(album_id, False)
    assert [song["title"] for song in music.get(f"/box/music/playlists/{playlist['id']}").json()["songs"]] == ["Blue Song", "Opening"]


def test_deleted_song_leaves_the_playlist(services: Services, music: TestClient, admin_client: TestClient, media_dir: Path) -> None:
    songs = song_ids(admin_client, "/api/admin/music")
    playlist = admin_client.post("/api/admin/music/playlists", json={"name": "Mix"}).json()
    url = f"/api/admin/music/playlists/{playlist['id']}"
    admin_client.put(f"{url}/songs", json={"song_ids": [songs["After"], songs["Opening"]]})

    (media_dir / "Music" / "Blue Artist" / "Blue Album" / "02 After.mp3").unlink()
    services.rescan_library()

    assert [song["title"] for song in admin_client.get(url).json()["songs"]] == ["Opening"]
    admin_client.put(url, json={"name": "Mix 2"})
    assert services.playlists.get(playlist["id"]).song_ids == [songs["Opening"]]


def test_admin_sets_the_order(admin_client: TestClient, music: TestClient) -> None:
    songs = song_ids(admin_client, "/api/admin/music")
    playlist = admin_client.post("/api/admin/music/playlists", json={"name": "Mix"}).json()
    url = f"/api/admin/music/playlists/{playlist['id']}/songs"

    ordered = admin_client.put(url, json={"song_ids": [songs["Opening"], songs["After"], songs["Opening"]]}).json()

    assert [song["title"] for song in ordered["songs"]] == ["Opening", "After"]
    assert admin_client.put(url, json={"song_ids": ["nope"]}).status_code == 422
    assert admin_client.get("/api/admin/music/songs").json()[0]["title"] == "After"
    assert admin_client.get("/api/admin/music/playlists/nope").status_code == 404
