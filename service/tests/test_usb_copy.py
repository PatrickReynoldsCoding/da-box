"""Copy from USB on the box, for drives with any layout (DESIGN_CORRECTIONS_1.md "Upload", and
DESIGN_CORRECTIONS_2.md part 3: grouped by kind, Copy everything, into the box's own layout)."""

import errno
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox import copying, usb_copy
from dabox.background import BackgroundWorkers
from dabox.library import item_id
from dabox.services import Services
from dabox.usb_copy import stick_items
from tests.conftest import write_file


def make_drive(usb_root: Path) -> Path:
    """The old layout and loose things mixed, as on real drives."""
    drive = usb_root / "BIGDRIVE"
    write_file(drive / "Films" / "Cars (2006)" / "Cars.mkv", b"cars film bytes")
    write_file(drive / "Films" / "Cars (2006)" / "movie.nfo", b"<movie><title>Cars</title></movie>")
    write_file(drive / "Films" / "Cars (2006)" / "._Cars.mkv", b"mac junk")
    # The same file as the box's Frozen: it is on the box already.
    write_file(drive / "Films" / "Frozen (2013)" / "Frozen (2013).mkv")
    # One Bluey episode is on the box, one is new.
    write_file(drive / "TV" / "Bluey" / "Season 01" / "Bluey S01E01 - The Pool.mp4", b"episode one")
    write_file(drive / "TV" / "Bluey" / "Season 01" / "Bluey S01E04 - Takeaway.mp4", b"episode four")
    write_file(drive / "Video" / "Nature" / "Nature 1 of 2.avi", b"nature one")
    write_file(drive / "Video" / "Nature" / "Nature 2 of 2.avi", b"nature two")
    write_file(drive / "Video" / "Lesson.mp4", b"lesson")
    write_file(drive / "Video" / "Lesson.srt", b"subtitles")
    write_file(drive / "Music" / "Stick Band" / "Stick Album" / "01 Song.mp3", b"stick song")
    write_file(drive / "Music" / "(16) Nick Lowe - Raining.mp3", b"loose song")
    write_file(drive / "Music" / "07 - Hello Goodbye.mp3", b"untagged song")
    write_file(drive / "Games" / "nes" / "Rocket.nes", b"nes rom bytes")
    write_file(drive / "Games" / "nes" / "Rocket.png", b"\x89PNG art")
    write_file(drive / "Mortage calculator ver 2.xlsx", b"not media")
    return drive


@pytest.fixture
def drive(services: Services, admin_client: TestClient, usb_root: Path) -> Path:
    path = make_drive(usb_root)
    BackgroundWorkers(services).check_usb_once()
    return path


@pytest.fixture
def parent_box(services: Services, box_client: TestClient, drive: Path) -> TestClient:
    services.box_state.set_parent_mode(True)
    return box_client


def wait_for_copy(client: TestClient) -> dict:
    for _ in range(500):
        progress = client.get("/box/usb/copy").json()
        if progress["state"] != "copying":
            return progress
        time.sleep(0.01)
    raise AssertionError("The copy did not end")


def tree_items(client: TestClient) -> dict[str, dict]:
    sticks = client.get("/box/usb/tree").json()
    return {item["id"]: item for folder in sticks[0]["folders"] for item in folder["items"]}


def by_title(client: TestClient) -> dict[str, dict]:
    return {item["title"]: item for item in tree_items(client).values()}


def copy_everything(client: TestClient) -> dict:
    """What the TV's "Copy everything" sends: every item that is not on the box yet."""
    sticks = client.get("/box/usb/tree").json()
    item_ids = [item["id"] for folder in sticks[0]["folders"] for item in folder["items"] if not item["on_box"]]
    started = client.post("/box/usb/copy", json={"stick_id": sticks[0]["stick_id"], "item_ids": item_ids})
    assert started.status_code == 200, started.text
    return wait_for_copy(client)


def test_tree_groups_the_drive_by_kind(parent_box: TestClient) -> None:
    sticks = parent_box.get("/box/usb/tree").json()

    assert [stick["label"] for stick in sticks] == ["BIGDRIVE"]
    folders = {folder["key"]: folder for folder in sticks[0]["folders"]}
    assert [folder["name"] for folder in sticks[0]["folders"]] == ["Videos", "Albums", "Games"]
    videos = {item["title"]: item for item in folders["videos"]["items"]}
    assert sorted(videos) == ["Bluey", "Cars", "Frozen", "Lesson", "Nature"]
    assert videos["Frozen"]["on_box"] and videos["Frozen"]["bytes"] == 0
    # The video's folder without its hidden files.
    assert videos["Cars"]["bytes"] == len(b"cars film bytes") + len(b"<movie><title>Cars</title></movie>")
    # A loose video with its subtitles.
    assert videos["Lesson"]["bytes"] == len(b"lesson") + len(b"subtitles")
    # Only the new episode counts.
    assert (videos["Bluey"]["on_box"], videos["Bluey"]["bytes"], videos["Bluey"]["subtitle"]) == (False, len(b"episode four"), "2 videos")
    assert videos["Nature"]["subtitle"] == "2 videos"
    albums = {(item["subtitle"], item["title"]) for item in folders["music"]["items"]}
    assert albums == {("Stick Band", "Stick Album"), ("Nick Lowe", "Unknown Album"), ("Unknown Artist", "Unknown Album")}
    assert folders["games"]["items"][0]["subtitle"] == "NES"
    # Ids are unique even where two albums share one folder (the loose songs in Music/).
    assert len(tree_items(parent_box)) == 9


def test_copy_from_usb_needs_parent_mode(services: Services, box_client: TestClient, drive: Path) -> None:
    assert box_client.get("/box/usb/tree").status_code == 403
    assert box_client.post("/box/usb/copy", json={"stick_id": "x", "item_ids": []}).status_code == 403
    assert box_client.post("/box/usb/copy/stop").status_code == 403
    # Home shows the progress in kid mode too.
    assert box_client.get("/box/usb/copy").json()["state"] == "idle"


def test_space_check_adds_up_the_ticked_items(parent_box: TestClient) -> None:
    items = tree_items(parent_box)
    stick_id = parent_box.get("/box/usb/tree").json()[0]["stick_id"]

    check = parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": list(items)}).json()

    assert check["items"] == len(items) - 1
    assert check["skipped"] == 1
    assert check["bytes_needed"] == sum(item["bytes"] for item in items.values())
    assert check["fits"]
    assert parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": ["videos:nope"]}).status_code == 422


def test_copy_does_not_start_without_space(parent_box: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stick_id = parent_box.get("/box/usb/tree").json()[0]["stick_id"]
    monkeypatch.setattr(usb_copy, "free_bytes", lambda media_dir: 1000)

    check = parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": list(tree_items(parent_box))}).json()
    response = parent_box.post("/box/usb/copy", json={"stick_id": stick_id, "item_ids": list(tree_items(parent_box))})

    assert (check["fits"], check["bytes_free"]) == (False, 1000)
    assert response.status_code == 409
    assert parent_box.get("/box/usb/copy").json()["state"] == "idle"


def test_copy_everything_puts_each_item_in_the_box_layout(services: Services, parent_box: TestClient, media_dir: Path) -> None:
    lesson_usb_id = next(tile["id"] for tile in parent_box.get("/box/videos").json() if tile["title"] == "Lesson")
    services.store.set_hidden(lesson_usb_id, True)

    progress = copy_everything(parent_box)

    assert progress["state"] == "done", progress
    assert (progress["items_done"], progress["items_total"]) == (8, 8)
    assert progress["bytes_done"] == progress["bytes_total"] > 0
    assert progress["message"] == "Copied 8 items from USB."
    videos = media_dir / "Videos"
    assert (videos / "Cars (2006)" / "Cars.mkv").read_bytes() == b"cars film bytes"
    assert (videos / "Cars (2006)" / "movie.nfo").exists()
    assert not (videos / "Cars (2006)" / "._Cars.mkv").exists()
    assert (videos / "Lesson" / "Lesson.mp4").exists() and (videos / "Lesson" / "Lesson.srt").exists()
    assert sorted(path.name for path in (videos / "Nature").iterdir()) == ["Nature 1 of 2.avi", "Nature 2 of 2.avi"]
    # The group that is on the box in part is finished in its own folder.
    assert (media_dir / "TV" / "Bluey" / "Season 01" / "Bluey S01E04 - Takeaway.mp4").exists()
    assert not (videos / "Bluey").exists()
    music = media_dir / "Music"
    assert (music / "Stick Band" / "Stick Album" / "01 Song.mp3").exists()
    assert (music / "Nick Lowe" / "Unknown Album" / "16 Raining.mp3").exists()
    assert (music / "Unknown Artist" / "Unknown Album" / "07 Hello Goodbye.mp3").exists()
    assert (media_dir / "Games" / "nes" / "Rocket.nes").exists() and (media_dir / "Games" / "nes" / "Rocket.png").exists()
    assert not (media_dir / "Mortage calculator ver 2.xlsx").exists()
    assert not list(media_dir.rglob("*.partial"))

    # The library was scanned: the copies are box items with the same names, hidden stays hidden.
    tiles = {tile["title"]: tile for tile in parent_box.get("/box/videos").json()}
    assert (tiles["Lesson"]["source"], tiles["Lesson"]["hidden"]) == ("box", True)
    assert (tiles["Nature"]["source"], tiles["Nature"]["kind"]) == ("box", "group")
    bluey = services.library.find_show(item_id("show", "TV/Bluey"))
    assert bluey is not None and len(bluey.episodes) == 4
    albums = {(album.artist, album.title, album.source) for album in services.library.library.albums}
    assert {("Nick Lowe", "Unknown Album", "box"), ("Unknown Artist", "Unknown Album", "box")} <= albums
    # Copying again finds nothing new.
    assert all(item["on_box"] for item in tree_items(parent_box).values())


def test_a_different_item_with_the_same_name_gets_its_own_folder(
    services: Services, parent_box: TestClient, media_dir: Path,
) -> None:
    write_file(media_dir / "Videos" / "Lesson" / "Lesson.mp4", b"a different lesson")
    services.rescan_library()
    assert not by_title(parent_box)["Lesson"]["on_box"]

    copy_everything(parent_box)

    assert (media_dir / "Videos" / "Lesson" / "Lesson.mp4").read_bytes() == b"a different lesson"
    assert (media_dir / "Videos" / "Lesson (2)" / "Lesson.mp4").read_bytes() == b"lesson"


def test_pulled_drive_stops_the_copy_and_leaves_no_half_item(
    services: Services, parent_box: TestClient, drive: Path, media_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stick = services.library.library.sticks[0]
    items = [item for item in stick_items(stick, services.library.library, media_dir) if item.title in ("Cars", "Stick Album")]
    items.sort(key=lambda item: item.title)
    real_write = copying._write_file
    calls = []

    def write_then_pull(source: Path, target: Path, count_bytes) -> None:
        calls.append(source)
        if len(calls) == 3:
            # The drive goes away while the album copies.
            for path in sorted(drive.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            drive.rmdir()
            raise OSError(errno.EIO, "Input/output error")
        real_write(source, target, count_bytes)

    monkeypatch.setattr(copying, "_write_file", write_then_pull)
    scans = []
    services.usb_copier.start(stick, items, lambda: scans.append(True), background=False)
    progress = services.usb_copier.progress()

    assert progress.state == "stopped"
    assert progress.message == "USB removed. Copied 1 of 2. Plug it in again to finish."
    assert (media_dir / "Videos" / "Cars (2006)" / "Cars.mkv").exists()
    assert not (media_dir / "Music" / "Stick Band").exists() or not any((media_dir / "Music" / "Stick Band").iterdir())
    assert not list(media_dir.rglob("*.partial"))
    assert scans == [True]


def test_stop_ends_the_copy(services: Services, parent_box: TestClient, media_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stick = services.library.library.sticks[0]
    items = [item for item in stick_items(stick, services.library.library, media_dir) if item.title in ("Cars", "Rocket")]
    real_run = usb_copy.run_copy

    def stop_then_run(plan, count_bytes) -> None:
        services.usb_copier.stop()
        real_run(plan, count_bytes)

    monkeypatch.setattr(usb_copy, "run_copy", stop_then_run)
    services.usb_copier.start(stick, items, lambda: None, background=False)

    progress = services.usb_copier.progress()
    assert (progress.state, progress.message) == ("stopped", "Copy stopped. Copied 0 of 2.")
    assert not (media_dir / "Videos" / "Cars (2006)").exists()
    assert not list(media_dir.rglob("*.partial"))


def test_copy_one_game_on_the_box(services: Services, parent_box: TestClient, media_dir: Path) -> None:
    rocket = next(game for game in parent_box.get("/box/games").json() if game["title"] == "Rocket")
    frozen = next(tile for tile in parent_box.get("/box/videos").json() if tile["title"] == "Frozen")

    assert parent_box.post(f"/box/content/{rocket['id']}/copy-to-box").status_code == 200
    progress = wait_for_copy(parent_box)

    assert (progress["state"], progress["items_done"]) == ("done", 1)
    assert (media_dir / "Games" / "nes" / "Rocket.nes").read_bytes() == b"nes rom bytes"
    assert [game["source"] for game in parent_box.get("/box/games").json() if game["title"] == "Rocket"] == ["box"]
    assert parent_box.post(f"/box/content/{frozen['id']}/copy-to-box").status_code == 409
    services.box_state.set_parent_mode(False)
    assert parent_box.post(f"/box/content/{rocket['id']}/copy-to-box").status_code == 403


def test_copy_one_group_on_the_box(services: Services, parent_box: TestClient, media_dir: Path) -> None:
    nature = next(tile for tile in parent_box.get("/box/videos").json() if tile["title"] == "Nature")
    services.store.set_hidden(nature["id"], True)

    assert parent_box.post(f"/box/content/{nature['id']}/copy-to-box").status_code == 200
    assert wait_for_copy(parent_box)["state"] == "done"

    box_nature = next(tile for tile in parent_box.get("/box/videos").json() if tile["title"] == "Nature")
    assert (box_nature["source"], box_nature["kind"], box_nature["hidden"]) == ("box", "group", True)
    assert box_nature["id"] == item_id("show", "Videos/Nature")


def test_admin_copies_a_game_to_the_box(services: Services, admin_client: TestClient, drive: Path, media_dir: Path) -> None:
    rocket = next(game for game in admin_client.get("/api/admin/games").json() if game["title"] == "Rocket")

    response = admin_client.post(f"/api/admin/content/{rocket['id']}/copy-to-box")

    assert response.status_code == 200, response.text
    assert (media_dir / "Games" / "nes" / "Rocket.nes").exists()
    # Saves follow the file's content, so the box copy keeps the same save key.
    box_copy = next(game for game in admin_client.get("/api/admin/games").json() if game["title"] == "Rocket")
    assert (box_copy["source"], box_copy["save_key"]) == ("box", rocket["save_key"])
