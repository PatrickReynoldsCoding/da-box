from pathlib import Path

from fastapi.testclient import TestClient

from dabox.services import Services
from dabox.software_update import is_newer, version_numbers
from tests.conftest import FakeHttp

LATEST_URL = "https://api.github.com/repos/PatrickReynoldsCoding/da-box/releases/latest"


def test_version_numbers() -> None:
    assert version_numbers("v1.2.3") == (1, 2, 3)
    assert version_numbers("0.4") == (0, 4, 0)
    assert version_numbers("v0.2.0-3-gabc1234") == (0, 2, 0)
    assert version_numbers("unknown") is None
    assert version_numbers("abc1234") is None


def test_is_newer() -> None:
    assert is_newer("v0.3.0", "v0.2.9")
    assert not is_newer("v0.2.0", "v0.2.0")
    # A checkout a few commits past the release is not older than it.
    assert not is_newer("v0.2.0", "v0.2.0-3-gabc1234")
    assert is_newer("v0.2.0", "unknown")
    assert not is_newer("nightly", "v0.1.0")


def test_no_release_yet(admin_client: TestClient) -> None:
    status = admin_client.get("/api/admin/software").json()
    assert status["latest"] is None
    assert status["available"] is False
    assert status["check_error"] == "There is no release on GitHub yet."
    assert admin_client.post("/api/admin/software/update").status_code == 409


def test_update_from_the_admin_app(admin_client: TestClient, fake_http: FakeHttp) -> None:
    fake_http.responses[LATEST_URL] = {"tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/v9.0.0"}

    status = admin_client.post("/api/admin/software/check").json()
    assert status["installed"] == "unknown"
    assert status["latest"] == "v9.0.0"
    assert status["available"] is True

    started = admin_client.post("/api/admin/software/update")
    assert started.status_code == 200, started.text
    assert started.json()["last_result"] == "OK"


def test_up_to_date(admin_client: TestClient, fake_http: FakeHttp, services: Services, tmp_path: Path) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("v9.0.0\n")
    services.software._version_file = version_file
    fake_http.responses[LATEST_URL] = {"tag_name": "v9.0.0"}

    status = admin_client.post("/api/admin/software/check").json()
    assert status["installed"] == "v9.0.0"
    assert status["available"] is False
    assert admin_client.post("/api/admin/software/update").json()["detail"] == "da-box is up to date."


def test_the_tv_needs_parent_mode(box_client: TestClient, completed_setup: None, services: Services, fake_http: FakeHttp) -> None:
    fake_http.responses[LATEST_URL] = {"tag_name": "v9.0.0"}
    assert box_client.get("/box/software").status_code == 403
    assert box_client.post("/box/software/update").status_code == 403

    services.box_state.set_parent_mode(True)
    assert box_client.post("/box/software/check").json()["available"] is True
    assert box_client.post("/box/software/update").status_code == 200


def test_the_network_cannot_use_the_box_routes(phone_client: TestClient, services: Services) -> None:
    services.box_state.set_parent_mode(True)
    assert phone_client.get("/box/software").status_code == 403
