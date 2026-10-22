import io
from pathlib import Path

from fastapi.testclient import TestClient

from dabox.services import Services
from tests.conftest import TEST_PIN, limits_payload


def test_login_before_setup_says_setup_required(phone_client: TestClient) -> None:
    assert phone_client.get("/api/admin/session").json() == {"logged_in": False, "setup_required": True}
    assert phone_client.post("/api/admin/login", json={"pin": "1234"}).status_code == 409


def test_admin_routes_need_login(phone_client: TestClient, completed_setup: None) -> None:
    assert phone_client.get("/api/admin/status").status_code == 401
    assert phone_client.post("/api/admin/parent-mode", json={"enabled": True}).status_code == 401


def test_wrong_pin(phone_client: TestClient, completed_setup: None) -> None:
    response = phone_client.post("/api/admin/login", json={"pin": "0000"})
    assert response.status_code == 401
    assert response.json()["detail"]["attempts_before_lockout"] == 4


def test_login_status_and_logout(admin_client: TestClient) -> None:
    status = admin_client.get("/api/admin/status").json()
    assert status == {
        "parent_mode": False,
        "setup_required": False,
        "timezone": "Europe/London",
        "film_count": 2,
        "album_count": 1,
    }
    admin_client.post("/api/admin/logout")
    assert admin_client.get("/api/admin/status").status_code == 401


def test_parent_mode_from_admin(admin_client: TestClient, box_client: TestClient) -> None:
    admin_client.post("/api/admin/parent-mode", json={"enabled": True})
    assert box_client.get("/box/state").json()["parent_mode"] is True


def test_hide_and_show_content(admin_client: TestClient, box_client: TestClient) -> None:
    album_id = admin_client.get("/api/admin/content").json()["albums"][0]["id"]

    admin_client.post(f"/api/admin/content/{album_id}/hidden", json={"hidden": True})
    assert box_client.get("/box/music/albums").json() == []
    assert admin_client.get("/api/admin/content").json()["albums"][0]["hidden"] is True

    admin_client.post(f"/api/admin/content/{album_id}/hidden", json={"hidden": False})
    assert len(box_client.get("/box/music/albums").json()) == 1

    assert admin_client.post("/api/admin/content/unknown/hidden", json={"hidden": True}).status_code == 404


def test_settings_round_trip(admin_client: TestClient) -> None:
    changed = limits_payload() | {"daily_quota_minutes": 90}
    assert admin_client.put("/api/admin/settings", json=changed).status_code == 200
    assert admin_client.get("/api/admin/settings").json()["daily_quota_minutes"] == 90
    assert admin_client.put("/api/admin/settings", json=limits_payload() | {"daily_quota_minutes": 5}).status_code == 422


def test_change_pin(admin_client: TestClient, services: Services) -> None:
    assert admin_client.post("/api/admin/pin", json={"current_pin": "0000", "new_pin": "9999"}).status_code == 403
    assert admin_client.post("/api/admin/pin", json={"current_pin": TEST_PIN, "new_pin": "9999"}).status_code == 200
    assert services.auth.check_pin("9999")


def test_rerun_setup(admin_client: TestClient, box_client: TestClient) -> None:
    admin_client.post("/api/admin/setup/rerun")
    assert box_client.get("/box/state").json()["setup_required"] is True


def test_upload_film_with_poster(admin_client: TestClient, media_dir: Path, box_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admin/upload/film",
        data={"title": "Moana", "year": "2016"},
        files={
            "video": ("moana.mp4", io.BytesIO(b"video bytes"), "video/mp4"),
            "poster": ("art.JPG", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg"),
        },
    )

    assert response.status_code == 200, response.text
    assert (media_dir / "Films" / "Moana (2016)" / "moana.mp4").read_bytes() == b"video bytes"
    assert (media_dir / "Films" / "Moana (2016)" / "poster.jpg").exists()
    assert "Moana" in [film["title"] for film in box_client.get("/box/films").json()]


def test_upload_rejects_wrong_type_and_duplicates(admin_client: TestClient) -> None:
    wrong_type = admin_client.post(
        "/api/admin/upload/film",
        data={"title": "Virus"},
        files={"video": ("virus.exe", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert wrong_type.status_code == 422

    for expected in (200, 409):
        response = admin_client.post(
            "/api/admin/upload/film",
            data={"title": "Twice"},
            files={"video": ("twice.mkv", io.BytesIO(b"x"), "video/x-matroska")},
        )
        assert response.status_code == expected


def test_upload_music_uses_form_names(admin_client: TestClient, media_dir: Path) -> None:
    response = admin_client.post(
        "/api/admin/upload/music",
        data={"artist": "New Artist", "album": "../../escape"},
        files=[("files", ("01 Song.mp3", io.BytesIO(b"x"), "audio/mpeg"))],
    )

    assert response.status_code == 200, response.text
    assert (media_dir / "Music" / "New Artist" / "escape" / "01 Song.mp3").exists()
