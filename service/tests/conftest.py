from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox.app import build_services, create_app
from dabox.config import ServiceConfig
from dabox.services import Services
from dabox.limits import PlayerSnapshot
from dabox.limits_service import FakePower
from dabox.metadata import HttpError
from dabox.system import FakeNetwork, FakeTimezone
from dabox.usb import FakeUsb

BOX_ADDRESS = ("127.0.0.1", 50000)
PHONE_ADDRESS = ("192.168.1.20", 50000)
TEST_PIN = "2468"


JPEG_BYTES = b"\xff\xd8\xff fake jpeg"


class FakeAgent:
    """Stands in for the player agent: what is playing, and what the service asked it to do."""

    def __init__(self) -> None:
        self.state = "idle"
        self.kind: str | None = None
        self.stopped = 0
        self.messages: list[str] = []

    def play(self, kind: str) -> None:
        self.state, self.kind = "playing", kind

    def status(self) -> PlayerSnapshot:
        return PlayerSnapshot(state=self.state, kind=self.kind)

    def stop(self) -> None:
        self.stopped += 1
        self.state, self.kind = "idle", None

    def notify(self, message: str) -> None:
        self.messages.append(message)


class FakeHttp:
    """Answers metadata requests from a dict of URL prefix -> JSON or bytes, and records the URLs."""

    def __init__(self) -> None:
        self.responses: dict[str, object] = {}
        self.requested: list[str] = []

    def _find(self, url: str) -> object:
        self.requested.append(url)
        for prefix in sorted(self.responses, key=len, reverse=True):
            if url.startswith(prefix):
                return self.responses[prefix]
        raise HttpError(404, url)

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> object:
        return self._find(url)

    def get_bytes(self, url: str) -> bytes:
        return self._find(url)  # type: ignore[return-value]


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
    write_file(media / "TV" / "Bluey" / "Season 01" / "Bluey S01E02 - Hospital.mp4", b"episode two")
    write_file(media / "TV" / "Bluey" / "Season 01" / "Bluey S01E01 - The Pool.mp4", b"episode one")
    write_file(media / "TV" / "Bluey" / "Season 2" / "03 Bike.mp4", b"episode three")
    write_file(media / "TV" / "Bluey" / "poster.jpg", b"\xff\xd8\xff fake jpeg")
    return media


@pytest.fixture
def timezone_backend() -> FakeTimezone:
    return FakeTimezone()


@pytest.fixture
def usb_root(tmp_path: Path) -> Path:
    root = tmp_path / "usb"
    root.mkdir()
    return root


@pytest.fixture
def fake_http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def fake_agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
def fake_power() -> FakePower:
    return FakePower()


@pytest.fixture
def services(
    tmp_path: Path, media_dir: Path, timezone_backend: FakeTimezone, usb_root: Path, fake_http: FakeHttp,
    fake_agent: FakeAgent, fake_power: FakePower,
) -> Services:
    config = ServiceConfig(
        media_dir=media_dir, data_dir=tmp_path / "data", host="127.0.0.1", port=80, dev_mode=True,
        core_dirs=(tmp_path / "cores",),
    )
    write_file(tmp_path / "cores" / "nestopia_libretro.so", b"core")
    return build_services(config, FakeNetwork(), timezone_backend, FakeUsb(usb_root), fake_http, fake_agent, fake_power)


@pytest.fixture
def box_client(services: Services):
    with TestClient(create_app(services, run_workers=False), client=BOX_ADDRESS) as client:
        yield client


@pytest.fixture
def phone_client(services: Services, box_client: TestClient):
    # Depends on box_client so the app lifespan (library scan) has run.
    with TestClient(create_app(services, run_workers=False), client=PHONE_ADDRESS) as client:
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
