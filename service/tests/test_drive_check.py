"""The USB drive check (DESIGN_CORRECTIONS_2.md, part 5)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dabox.background import BackgroundWorkers
from dabox.services import Services
from dabox.usb import drive_views, parse_lsblk
from tests.conftest import write_file

DRIVES = Path(__file__).parent / "drives"


def test_drive_views_say_why_a_drive_is_not_read() -> None:
    sample = json.loads((DRIVES / "mac-drives.json").read_text())
    views = drive_views(parse_lsblk(json.dumps(sample["lsblk"])), {})
    assert [(view.label, view.supported, view.mounted) for view in views] == [("Mac HD", False, False), ("Backup", False, False)]
    assert "cannot read hfsplus" in views[0].problem


def test_drive_views_show_the_mount_error() -> None:
    sample = json.loads((DRIVES / "usb-stick-exfat-flat.json").read_text())
    [view] = drive_views(parse_lsblk(json.dumps(sample["lsblk"])), {"/dev/sdb1": "Error mounting: wrong fs type"})
    assert (view.label, view.mounted, view.problem) == ("STICK", False, "Error mounting: wrong fs type")


def test_drive_check_counts_what_was_found_and_skipped(
    admin_client: TestClient, box_client: TestClient, services: Services, usb_root: Path,
) -> None:
    drive = usb_root / "Untitled"
    write_file(drive / "Video" / "Lesson.mp4", b"lesson")
    write_file(drive / "Video" / "Nature" / "Nature 1 of 2.avi", b"one")
    write_file(drive / "Video" / "Nature" / "Nature 2 of 2.avi", b"two")
    write_file(drive / "Music" / "(16) Nick Lowe - Raining.mp3", b"song")
    write_file(drive / "Games" / "Plumber.sfc", b"snes, no core on this box")
    write_file(drive / "Games" / "Rocket.nes", b"nes, has a core")
    write_file(drive / "Mortage calculator ver 2.xlsx", b"sheet")
    write_file(drive / "$RECYCLE.BIN" / "deleted.mp4", b"deleted")
    BackgroundWorkers(services).check_usb_once()
    lesson = next(film for film in services.library.library.films if film.title == "Lesson")
    admin_client.post(f"/api/admin/content/{lesson.id}/hidden", json={"hidden": True})

    for client, path in ((box_client, "/box/usb/drives"), (admin_client, "/api/admin/usb/drives")):
        [check] = client.get(path).json()
        assert check["drive"]["label"] == "Untitled" and check["drive"]["mounted"] is True
        report = check["report"]
        assert (report["videos"], report["groups"], report["albums"], report["songs"], report["games"]) == (1, 1, 1, 1, 2)
        assert report["other_files"] == {".xlsx": 1}
        assert report["skipped_folders"] == 1
        assert (check["games_without_core"], check["hidden"]) == (1, 1)


def test_drive_check_is_not_for_the_network(phone_client: TestClient) -> None:
    assert phone_client.get("/box/usb/drives").status_code == 403
    assert phone_client.get("/api/admin/usb/drives").status_code == 401
