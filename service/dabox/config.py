import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceConfig:
    media_dir: Path
    data_dir: Path
    host: str
    port: int
    # Dev mode swaps real system calls (nmcli, timedatectl, udisks) for fakes so the
    # service runs on a Mac.
    dev_mode: bool
    # Dev mode only: every folder in here counts as a mounted USB stick.
    fake_usb_dir: Path | None = None
    agent_url: str = "http://127.0.0.1:8091"
    # Where libretro cores live. Games for systems without a core are not shown.
    core_dirs: tuple[Path, ...] = ()


def load_service_config() -> ServiceConfig:
    return ServiceConfig(
        media_dir=Path(os.environ.get("DABOX_MEDIA_DIR", "/srv/dabox/media")),
        data_dir=Path(os.environ.get("DABOX_DATA_DIR", "/var/lib/dabox")),
        host=os.environ.get("DABOX_HOST", "0.0.0.0"),
        port=int(os.environ.get("DABOX_PORT", "80")),
        dev_mode=os.environ.get("DABOX_DEV") == "1",
        fake_usb_dir=Path(os.environ["DABOX_FAKE_USB_DIR"]) if os.environ.get("DABOX_FAKE_USB_DIR") else None,
        agent_url=os.environ.get("DABOX_AGENT_URL", "http://127.0.0.1:8091"),
        core_dirs=tuple(Path(folder) for folder in os.environ.get("DABOX_CORE_DIRS", "").split(":") if folder),
    )
