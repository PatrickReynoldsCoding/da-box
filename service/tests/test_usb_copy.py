import errno
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox import copying, usb_copy
from dabox.background import BackgroundWorkers
from dabox.services import Services
from dabox.usb_copy import stick_items
from tests.conftest import write_file


def make_drive(usb_root: Path) -> Path:
    drive = usb_root / "BIGDRIVE"
    write_file(drive / "Films" / "Cars (2006)" / "Cars.mkv", b"cars film bytes")
    write_file(drive / "Films" / "Cars (2006)" / "movie.nfo", b"<movie><title>Cars</title></movie>")
    write_file(drive / "Films" / "Cars (2006)" / "._Cars.mkv", b"mac junk")
    # The same file as the box's Frozen: it is on the box already.
    write_file(drive / "Films" / "Frozen (2013)" / "Frozen (2013).mkv")
    # One Bluey episode is on the box, one is new.
    write_file(drive / "TV" / "Bluey" / "Season 01" / "Bluey S01E01 - The Pool.mp4", b"episode one")
    write_file(drive / "TV" / "Bluey" / "Season 01" / "Bluey S01E04 - Takeaway.mp4", b"episode four")
    write_file(drive / "TV" / "Paw Pals" / "Season 01" / "Paw Pals S01E01 - Pilot.mp4", b"paw pilot")
    write_file(drive / "Music" / "Stick Band" / "Stick Album" / "01 Song.mp3", b"stick song")
    write_file(drive / "Games" / "nes" / "Rocket.nes", b"nes rom bytes")
    write_file(drive / "Games" / "nes" / "Rocket.png", b"\x89PNG art")
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


def test_tree_lists_the_drive_in_four_folders(parent_box: TestClient) -> None:
    sticks = parent_box.get("/box/usb/tree").json()

    assert [stick["label"] for stick in sticks] == ["BIGDRIVE"]
    folders = {folder["key"]: folder for folder in sticks[0]["folders"]}
    assert [folder["name"] for folder in sticks[0]["folders"]] == ["Films", "TV", "Music", "Games"]
    films = {item["title"]: item for item in folders["films"]["items"]}
    assert films["Frozen"]["on_box"] and films["Frozen"]["bytes"] == 0
    # The film folder without its hidden files.
    assert films["Cars"]["bytes"] == len(b"cars film bytes") + len(b"<movie><title>Cars</title></movie>")
    shows = {item["title"]: item for item in folders["tv"]["items"]}
    # Only the new episode counts.
    assert (shows["Bluey"]["on_box"], shows["Bluey"]["bytes"]) == (False, len(b"episode four"))
    assert shows["Paw Pals"]["subtitle"] == "1 episode"
    assert folders["games"]["items"][0]["subtitle"] == "NES"
    assert folders["films"]["bytes"] == films["Cars"]["bytes"]


def test_copy_from_usb_needs_parent_mode(services: Services, box_client: TestClient, drive: Path) -> None:
    assert box_client.get("/box/usb/tree").status_code == 403
    assert box_client.post("/box/usb/copy", json={"stick_id": "x", "item_ids": []}).status_code == 403
    assert box_client.post("/box/usb/copy/stop").status_code == 403
    # Home shows the progress in kid mode too.
    assert box_client.get("/box/usb/copy").json()["state"] == "idle"


def test_space_check_adds_up_the_ticked_items(parent_box: TestClient) -> None:
    items = tree_items(parent_box)
    stick_id = parent_box.get("/box/usb/tree").json()[0]["stick_id"]
    ticked = list(items)

    check = parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": ticked}).json()

    assert check["items"] == len(items) - 1
    assert check["skipped"] == 1
    assert check["bytes_needed"] == sum(item["bytes"] for item in items.values())
    assert check["fits"]
    assert parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": ["films:Nope"]}).status_code == 422


def test_copy_does_not_start_without_space(parent_box: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stick_id = parent_box.get("/box/usb/tree").json()[0]["stick_id"]
    monkeypatch.setattr(usb_copy, "free_bytes", lambda media_dir: 1000)

    check = parent_box.post("/box/usb/check", json={"stick_id": stick_id, "item_ids": list(tree_items(parent_box))}).json()
    response = parent_box.post("/box/usb/copy", json={"stick_id": stick_id, "item_ids": list(tree_items(parent_box))})

    assert (check["fits"], check["bytes_free"]) == (False, 1000)
    assert response.status_code == 409
    assert parent_box.get("/box/usb/copy").json()["state"] == "idle"


def test_copy_puts_everything_on_the_box(services: Services, parent_box: TestClient, media_dir: Path) -> None:
    stick_id = parent_box.get("/box/usb/tree").json()[0]["stick_id"]
    cars_usb_id = next(film["id"] for film in parent_box.get("/box/films").json() if film["title"] == "Cars")
    services.store.set_hidden(cars_usb_id, True)

    started = parent_box.post("/box/usb/copy", json={"stick_id": stick_id, "item_ids": list(tree_items(parent_box))})
    assert started.status_code == 200, started.text
    progress = wait_for_copy(parent_box)

    assert progress["state"] == "done", progress
    assert (progress["items_done"], progress["items_total"], progress["skipped"]) == (5, 5, ["Frozen"])
    assert progress["bytes_done"] == progress["bytes_total"] > 0
    assert progress["message"] == "Copied 5 items from USB. 1 already on the box."
    assert (media_dir / "Films" / "Cars (2006)" / "Cars.mkv").read_bytes() == b"cars film bytes"
    assert not (media_dir / "Films" / "Cars (2006)" / "._Cars.mkv").exists()
    assert (media_dir / "TV" / "Bluey" / "Season 01" / "Bluey S01E04 - Takeaway.mp4").exists()
    assert (media_dir / "TV" / "Paw Pals" / "Season 01" / "Paw Pals S01E01 - Pilot.mp4").exists()
    assert (media_dir / "Music" / "Stick Band" / "Stick Album" / "01 Song.mp3").exists()
    assert (media_dir / "Games" / "nes" / "Rocket.nes").exists() and (media_dir / "Games" / "nes" / "Rocket.png").exists()
    assert not list(media_dir.rglob("*.partial"))
    # The library was scanned: Cars is a box film now, and stays hidden.
    cars = [film for film in parent_box.get("/box/films").json() if film["title"] == "Cars"]
    assert [(film["source"], film["hidden"]) for film in cars] == [("box", True)]
    assert {show.title: len(show.episodes) for show in services.library.library.shows} == {"Bluey": 4, "Paw Pals": 1}
    # Copying again finds nothing new.
    assert all(item["on_box"] for item in tree_items(parent_box).values())


def test_pulled_drive_stops_the_copy_and_leaves_no_half_item(
    services: Services, parent_box: TestClient, drive: Path, media_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stick = services.library.library.sticks[0]
    items = [item for item in stick_items(stick, services.library.library, media_dir) if item.folder_key in ("films", "music")]
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
    assert (media_dir / "Films" / "Cars (2006)" / "Cars.mkv").exists()
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
    assert not (media_dir / "Films" / "Cars (2006)").exists()
    assert not list(media_dir.rglob("*.partial"))


def test_copy_one_game_on_the_box(services: Services, parent_box: TestClient, media_dir: Path) -> None:
    rocket = next(game for game in parent_box.get("/box/games").json() if game["title"] == "Rocket")
    frozen = next(film for film in parent_box.get("/box/films").json() if film["title"] == "Frozen")

    assert parent_box.post(f"/box/content/{rocket['id']}/copy-to-box").status_code == 200
    progress = wait_for_copy(parent_box)

    assert (progress["state"], progress["items_done"]) == ("done", 1)
    assert (media_dir / "Games" / "nes" / "Rocket.nes").read_bytes() == b"nes rom bytes"
    assert [game["source"] for game in parent_box.get("/box/games").json() if game["title"] == "Rocket"] == ["box"]
    assert parent_box.post(f"/box/content/{frozen['id']}/copy-to-box").status_code == 409
    services.box_state.set_parent_mode(False)
    assert parent_box.post(f"/box/content/{rocket['id']}/copy-to-box").status_code == 403


def test_admin_copies_a_game_to_the_box(services: Services, admin_client: TestClient, drive: Path, media_dir: Path) -> None:
    rocket = next(game for game in admin_client.get("/api/admin/games").json() if game["title"] == "Rocket")

    response = admin_client.post(f"/api/admin/content/{rocket['id']}/copy-to-box")

    assert response.status_code == 200, response.text
    assert (media_dir / "Games" / "nes" / "Rocket.nes").exists()
    # Saves follow the file's content, so the box copy keeps the same save key.
    box_copy = next(game for game in admin_client.get("/api/admin/games").json() if game["title"] == "Rocket")
    assert (box_copy["source"], box_copy["save_key"]) == ("box", rocket["save_key"])
