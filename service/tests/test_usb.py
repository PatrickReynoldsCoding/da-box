import json
from pathlib import Path

from fastapi.testclient import TestClient

from dabox.app import create_app
from dabox.background import BackgroundWorkers
from dabox.library import file_fingerprint
from dabox.nfo import parse_movie_nfo
from dabox.services import Services
from dabox.usb import BlockDevice, mount_options, parse_lsblk, usb_filesystems
from tests.conftest import BOX_ADDRESS, limits_payload, write_file

LSBLK_OUTPUT = json.dumps({
    "blockdevices": [
        {"path": "/dev/vda", "fstype": None, "label": None, "uuid": None, "mountpoint": None, "tran": None,
         "children": [{"path": "/dev/vda1", "fstype": "ext4", "label": None, "uuid": "root", "mountpoint": "/", "tran": None}]},
        {"path": "/dev/sda", "fstype": None, "label": None, "uuid": None, "mountpoint": None, "tran": "usb",
         "children": [
             {"path": "/dev/sda1", "fstype": "vfat", "label": "KIDS", "uuid": "AB-12", "mountpoint": None, "tran": None},
             {"path": "/dev/sda2", "fstype": "swap", "label": None, "uuid": "sw", "mountpoint": None, "tran": None},
         ]},
    ]
})


def test_parse_lsblk_finds_usb_partitions_only() -> None:
    found = usb_filesystems(parse_lsblk(LSBLK_OUTPUT))
    assert found == [BlockDevice(path="/dev/sda1", filesystem="vfat", label="KIDS", uuid="AB-12", mountpoint=None, on_usb=True)]


# lsblk on Linux Mint 22 (util-linux 2.39): a flat list, and only the disk has TRAN.
FLAT_LSBLK_OUTPUT = json.dumps({
    "blockdevices": [
        {"path": "/dev/sda", "fstype": None, "label": None, "uuid": None, "mountpoint": None, "tran": "usb", "pkname": None},
        {"path": "/dev/sda1", "fstype": "exfat", "label": "Untitled", "uuid": "F29B-F8EA", "mountpoint": None, "tran": None, "pkname": "sda"},
        {"path": "/dev/nvme0n1", "fstype": None, "label": None, "uuid": None, "mountpoint": None, "tran": "nvme", "pkname": None},
        {"path": "/dev/nvme0n1p2", "fstype": "ext4", "label": None, "uuid": "root", "mountpoint": "/", "tran": None, "pkname": "nvme0n1"},
    ]
})


def test_parse_flat_lsblk_finds_usb_partitions_by_parent() -> None:
    found = usb_filesystems(parse_lsblk(FLAT_LSBLK_OUTPUT))
    assert found == [BlockDevice(path="/dev/sda1", filesystem="exfat", label="Untitled", uuid="F29B-F8EA", mountpoint=None, on_usb=True)]


def test_mount_options_are_read_only_and_readable_by_all() -> None:
    assert mount_options("vfat") == "ro,noexec,nosuid,nodev,umask=0022"
    assert mount_options("ext4") == "ro,noexec,nosuid,nodev"


def test_parse_movie_nfo() -> None:
    details = parse_movie_nfo("<movie><title>Moana</title><year>2016</year><plot> Sea story. </plot></movie>")
    assert (details.title, details.year, details.plot) == ("Moana", 2016, "Sea story.")
    assert parse_movie_nfo("https://www.imdb.com/title/tt3521164/") is None
    assert parse_movie_nfo("<tvshow><title>x</title></tvshow>") is None


def test_fingerprint_ignores_name_and_folder(tmp_path: Path) -> None:
    content = bytes(range(256)) * 1000
    first = write_file(tmp_path / "a" / "film.mkv", content)
    second = write_file(tmp_path / "b" / "other name.mkv", content)
    different = write_file(tmp_path / "c.mkv", content + b"x")
    assert file_fingerprint(first) == file_fingerprint(second) != file_fingerprint(different)


def make_stick(usb_root: Path, name: str, film_bytes: bytes = b"usb film bytes") -> Path:
    stick = usb_root / name
    write_file(stick / "Films" / "Cars (2006)" / "Cars.mkv", film_bytes)
    write_file(stick / "Films" / "Cars (2006)" / "movie.nfo", b"<movie><title>Cars</title><plot>Fast car.</plot></movie>")
    write_file(stick / "Music" / "Stick Band" / "Stick Album" / "01 Song.mp3", b"song")
    return stick


def test_usb_items_merge_into_the_library_with_a_badge(services: Services, box_client: TestClient, usb_root: Path) -> None:
    box_client.post("/box/setup/complete", json={"pin": "2468", "timezone": "Europe/London", "limits": limits_payload()})
    make_stick(usb_root, "KIDS")
    assert BackgroundWorkers(services).check_usb_once()

    films = box_client.get("/box/films").json()
    cars = next(film for film in films if film["title"] == "Cars")
    assert (cars["source"], cars["stick_label"], cars["plot"]) == ("usb", "KIDS", "Fast car.")
    assert cars["id"].startswith("u")
    assert [album["source"] for album in box_client.get("/box/music/albums").json()] == ["usb", "box"]


def test_hidden_usb_item_stays_hidden_on_another_stick(services: Services, box_client: TestClient, usb_root: Path) -> None:
    box_client.post("/box/setup/complete", json={"pin": "2468", "timezone": "Europe/London", "limits": limits_payload()})
    workers = BackgroundWorkers(services)
    first = make_stick(usb_root, "FIRST")
    workers.check_usb_once()
    cars_id = next(film["id"] for film in box_client.get("/box/films").json() if film["title"] == "Cars")
    services.store.set_hidden(cars_id, True)

    first.rename(usb_root / "SECOND")
    workers.check_usb_once()

    assert "Cars" not in [film["title"] for film in box_client.get("/box/films").json()]


def test_usb_playback_setting_hides_usb_items(services: Services, box_client: TestClient, usb_root: Path) -> None:
    limits = limits_payload() | {"usb_playback": False}
    box_client.post("/box/setup/complete", json={"pin": "2468", "timezone": "Europe/London", "limits": limits})
    make_stick(usb_root, "KIDS")
    BackgroundWorkers(services).check_usb_once()

    assert "Cars" not in [film["title"] for film in box_client.get("/box/films").json()]
    services.box_state.set_parent_mode(True)
    assert "Cars" in [film["title"] for film in box_client.get("/box/films").json()]


def test_stick_removal_removes_items(services: Services, box_client: TestClient, usb_root: Path) -> None:
    box_client.post("/box/setup/complete", json={"pin": "2468", "timezone": "Europe/London", "limits": limits_payload()})
    workers = BackgroundWorkers(services)
    stick = make_stick(usb_root, "KIDS")
    workers.check_usb_once()
    assert len(box_client.get("/box/films").json()) == 3

    for path in sorted(stick.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    stick.rmdir()
    assert workers.check_usb_once()
    assert len(box_client.get("/box/films").json()) == 2
    assert not workers.check_usb_once()


def test_copy_usb_film_to_box_keeps_hidden_state(
    services: Services, admin_client: TestClient, usb_root: Path, media_dir: Path
) -> None:
    make_stick(usb_root, "KIDS")
    BackgroundWorkers(services).check_usb_once()
    cars_id = next(film["id"] for film in admin_client.get("/api/admin/content").json()["films"] if film["title"] == "Cars")
    admin_client.post(f"/api/admin/content/{cars_id}/hidden", json={"hidden": True})

    response = admin_client.post(f"/api/admin/content/{cars_id}/copy-to-box")

    assert response.status_code == 200, response.text
    assert (media_dir / "Videos" / "Cars (2006)" / "Cars.mkv").read_bytes() == b"usb film bytes"
    copies = [film for film in response.json()["films"] if film["title"] == "Cars"]
    # The box copy and the stick copy are the same file, so only the box one is listed.
    assert [(film["source"], film["hidden"]) for film in copies] == [("box", True)]
    assert admin_client.post(f"/api/admin/content/{copies[0]['id']}/copy-to-box").status_code == 409


def test_copy_usb_album_to_box(services: Services, admin_client: TestClient, usb_root: Path, media_dir: Path) -> None:
    make_stick(usb_root, "KIDS")
    BackgroundWorkers(services).check_usb_once()
    album_id = next(album["id"] for album in admin_client.get("/api/admin/content").json()["albums"] if album["source"] == "usb")

    assert admin_client.post(f"/api/admin/content/{album_id}/copy-to-box").status_code == 200
    assert (media_dir / "Music" / "Stick Band" / "Stick Album" / "01 Song.mp3").exists()


def test_usb_list_in_admin(services: Services, admin_client: TestClient, usb_root: Path) -> None:
    make_stick(usb_root, "KIDS")
    BackgroundWorkers(services).check_usb_once()
    assert [stick["label"] for stick in admin_client.get("/api/admin/usb").json()] == ["KIDS"]


def test_box_ids_do_not_change_when_a_stick_is_added(services: Services, usb_root: Path) -> None:
    with TestClient(create_app(services, run_workers=False), client=BOX_ADDRESS) as client:
        before = {film["title"]: film["id"] for film in client.get("/box/films").json()}
        make_stick(usb_root, "KIDS")
        BackgroundWorkers(services).check_usb_once()
        after = {film["title"]: film["id"] for film in client.get("/box/films").json()}
    assert all(after[title] == film_id for title, film_id in before.items())
