from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox.app import build_services, create_app
from dabox.config import ServiceConfig
from dabox.services import Services
from dabox.system import FakeNetwork, FakeTimezone

BOX_ADDRESS = ("127.0.0.1", 50000)
PHONE_ADDRESS = ("192.168.1.20", 50000)
TEST_PIN = "2468"


def write_file(path: Path, content: bytes = b"not really media") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def limits_payload() -> dict:
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return {
        "daily_quota_minutes": 120,
        "shared_quota": True,
        "overrun_minutes": 20,
        "game_windows": {day: ({"start": "16:00", "end": "18:00"} if day not in ("sat", "sun") else None) for day in days},
        "bedtimes": {day: "19:30" for day in days},
        "bedtime_overrun": False,
        "usb_playback": True,
        "usb_games": True,
    }


def setup_payload() -> dict:
    return {"pin": TEST_PIN, "timezone": "Europe/London", "limits": limits_payload()}


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    write_file(media / "Films" / "Frozen (2013)" / "Frozen (2013).mkv")
    write_file(media / "Films" / "Frozen (2013)" / "poster.jpg", b"\xff\xd8\xff fake jpeg")
    write_file(media / "Films" / "Home Movie.mp4")
    write_file(media / "Films" / "notes.txt")
    write_file(media / "Music" / "The Band" / "First Album" / "01 - Opening.mp3")
    write_file(media / "Music" / "The Band" / "First Album" / "02 - Second Song.mp3")
    write_file(media / "Music" / "The Band" / "First Album" / "cover.jpg", b"\xff\xd8\xff fake jpeg")
    return media


@pytest.fixture
def timezone_backend() -> FakeTimezone:
    return FakeTimezone()


@pytest.fixture
def services(tmp_path: Path, media_dir: Path, timezone_backend: FakeTimezone) -> Services:
    config = ServiceConfig(media_dir=media_dir, data_dir=tmp_path / "data", host="127.0.0.1", port=80, dev_mode=True)
    return build_services(config, FakeNetwork(), timezone_backend)


@pytest.fixture
def box_client(services: Services):
    with TestClient(create_app(services), client=BOX_ADDRESS) as client:
        yield client


@pytest.fixture
def phone_client(services: Services, box_client: TestClient):
    # Depends on box_client so the app lifespan (library scan) has run.
    with TestClient(create_app(services), client=PHONE_ADDRESS) as client:
        yield client


@pytest.fixture
def completed_setup(box_client: TestClient) -> None:
    response = box_client.post("/box/setup/complete", json=setup_payload())
    assert response.status_code == 200, response.text


@pytest.fixture
def admin_client(phone_client: TestClient, completed_setup: None) -> TestClient:
    response = phone_client.post("/api/admin/login", json={"pin": TEST_PIN})
    assert response.status_code == 200, response.text
    return phone_client
