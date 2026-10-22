import io
import zipfile

from fastapi.testclient import TestClient

from dabox.services import Services


def test_appearance_reaches_the_box(admin_client: TestClient, box_client: TestClient) -> None:
    assert box_client.get("/box/state").json()["appearance"] == {"theme": "purple", "sounds": True}
    admin_client.put("/api/admin/appearance", json={"theme": "ocean", "sounds": False})
    assert box_client.get("/box/state").json()["appearance"] == {"theme": "ocean", "sounds": False}
    assert admin_client.put("/api/admin/appearance", json={"theme": "neon", "sounds": True}).status_code == 422


def test_backup_and_restore(services: Services, admin_client: TestClient) -> None:
    film_id = admin_client.get("/api/admin/content").json()["films"][0]["id"]
    admin_client.post(f"/api/admin/content/{film_id}/hidden", json={"hidden": True})
    admin_client.post(f"/api/admin/content/{film_id}/metadata/art-upload", files={"image": ("a.png", b"\x89PNG art", "image/png")})

    backup = admin_client.get("/api/admin/backup")
    assert backup.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(backup.content)).namelist()
    assert "dabox.db" in names and f"art/{film_id}.png" in names

    admin_client.post(f"/api/admin/content/{film_id}/hidden", json={"hidden": False})
    admin_client.delete(f"/api/admin/content/{film_id}/metadata")
    restored = admin_client.post("/api/admin/restore", files={"backup_file": ("b.zip", backup.content, "application/zip")})

    assert restored.status_code == 200, restored.text
    film = next(film for film in admin_client.get("/api/admin/content").json()["films"] if film["id"] == film_id)
    assert film["hidden"] is True
    assert admin_client.get(film["art_url"]).content == b"\x89PNG art"


def test_restore_rejects_bad_files(admin_client: TestClient, services: Services) -> None:
    assert admin_client.post("/api/admin/restore", files={"backup_file": ("x.zip", b"not a zip", "application/zip")}).status_code == 422

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("dabox.db", b"not sqlite")
        archive.writestr("art/../../evil.png", b"x")
    response = admin_client.post("/api/admin/restore", files={"backup_file": ("x.zip", buffer.getvalue(), "application/zip")})
    assert response.status_code == 422
    assert not (services.metadata.store.art_dir.parent.parent / "evil.png").exists()


def test_system_update_in_dev_mode(admin_client: TestClient) -> None:
    assert admin_client.get("/api/admin/system-update").json()["last_result"] is None
    assert admin_client.post("/api/admin/system-update").json()["last_result"] == "OK"


def test_update_result() -> None:
    from dabox.maintenance import update_result

    assert update_result({"ActiveState": "active"}, ["started"]) is None
    assert update_result({"ActiveState": "inactive", "Result": "success"}, []) is None
    assert update_result({"ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0"}, ["done"]) == "OK"
    assert update_result({"ActiveState": "failed", "Result": "exit-code", "ExecMainStatus": "100"}, ["E: x"]).startswith("Failed")
