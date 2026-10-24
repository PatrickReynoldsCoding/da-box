"""The Videos screen: single videos and groups together (DESIGN_CORRECTIONS_2.md, part 2)."""

from pathlib import Path

from fastapi.testclient import TestClient

from dabox.background import BackgroundWorkers
from dabox.library import item_id
from dabox.services import Services
from tests.conftest import write_file


def test_videos_lists_single_videos_and_groups_by_name(box_client: TestClient, completed_setup: None) -> None:
    tiles = box_client.get("/box/videos").json()
    assert [(tile["kind"], tile["title"]) for tile in tiles] == [("group", "Bluey"), ("video", "Frozen"), ("video", "Home Movie")]
    bluey = tiles[0]
    assert (bluey["video_count"], bluey["path"], bluey["art_url"]) == (3, None, f"/box/art/{bluey['id']}")
    frozen = tiles[1]
    assert frozen["path"].endswith("Frozen (2013).mkv") and frozen["year"] == 2013


def test_group_opens_with_its_videos_in_order(box_client: TestClient, completed_setup: None) -> None:
    group_id = item_id("show", "TV/Bluey")
    group = box_client.get(f"/box/groups/{group_id}").json()
    assert group["title"] == "Bluey" and group["resume_index"] == 0
    assert [(video["code"], video["title"], video["section"]) for video in group["videos"]] == [
        ("S1 E1", "The Pool", "Season 01"), ("S1 E2", "Hospital", "Season 01"), ("S2 E3", "Bike", "Season 2"),
    ]
    assert box_client.get("/box/art/" + group_id).status_code == 200
    assert box_client.get("/box/groups/nope").status_code == 404


def test_group_remembers_where_to_play_from(box_client: TestClient, completed_setup: None) -> None:
    group_id = item_id("show", "TV/Bluey")
    assert box_client.post(f"/box/groups/{group_id}/resume", json={"index": 2}).status_code == 200
    assert box_client.get(f"/box/groups/{group_id}").json()["resume_index"] == 2
    # Past the end starts from the beginning again.
    box_client.post(f"/box/groups/{group_id}/resume", json={"index": 3})
    assert box_client.get(f"/box/groups/{group_id}").json()["resume_index"] == 0


def test_a_hidden_group_is_gone_for_kids_and_shown_in_parent_mode(
    admin_client: TestClient, box_client: TestClient, services: Services,
) -> None:
    group_id = item_id("show", "TV/Bluey")
    assert admin_client.post(f"/api/admin/content/{group_id}/hidden", json={"hidden": True}).status_code == 200
    assert group_id not in [tile["id"] for tile in box_client.get("/box/videos").json()]
    assert box_client.get(f"/box/groups/{group_id}").status_code == 404
    services.box_state.set_parent_mode(True)
    assert [tile["hidden"] for tile in box_client.get("/box/videos").json() if tile["id"] == group_id] == [True]
    content = admin_client.get("/api/admin/content").json()
    assert [(group["title"], group["hidden"]) for group in content["groups"]] == [("Bluey", True)]


def make_usb_videos(usb_root: Path) -> None:
    drive = usb_root / "Untitled"
    write_file(drive / "Video" / "Lesson.mp4", b"lesson")
    for number in (1, 2):
        write_file(drive / "Video" / "Nature Series" / f"Nature Series {number} of 2.avi", f"nature {number}".encode())


def test_usb_groups_show_with_the_usb_setting(
    box_client: TestClient, completed_setup: None, services: Services, usb_root: Path,
) -> None:
    make_usb_videos(usb_root)
    BackgroundWorkers(services).check_usb_once()
    tiles = {tile["title"]: tile for tile in box_client.get("/box/videos").json()}
    assert tiles["Nature Series"]["kind"] == "group" and tiles["Nature Series"]["source"] == "usb"
    assert tiles["Lesson"]["stick_label"] == "Untitled"

    limits = services.box_state.limits()
    services.box_state.save_limits(limits.model_copy(update={"usb_playback": False}))
    titles = [tile["title"] for tile in box_client.get("/box/videos").json()]
    assert "Nature Series" not in titles and "Lesson" not in titles


def test_usb_groups_are_not_used_in_channels(
    admin_client: TestClient, services: Services, usb_root: Path,
) -> None:
    make_usb_videos(usb_root)
    BackgroundWorkers(services).check_usb_once()
    pool = admin_client.get("/api/admin/pool").json()
    assert [item["title"] for item in pool if item["kind"] == "show"] == ["Bluey"]
