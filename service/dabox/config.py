import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceConfig:
    media_dir: Path
    data_dir: Path
    host: str
    port: int
    # Dev mode swaps real system calls (nmcli, timedatectl) for fakes so the
    # service runs on a Mac.
    dev_mode: bool


def load_service_config() -> ServiceConfig:
    return ServiceConfig(
        media_dir=Path(os.environ.get("DABOX_MEDIA_DIR", "/srv/dabox/media")),
        data_dir=Path(os.environ.get("DABOX_DATA_DIR", "/var/lib/dabox")),
        host=os.environ.get("DABOX_HOST", "0.0.0.0"),
        port=int(os.environ.get("DABOX_PORT", "80")),
        dev_mode=os.environ.get("DABOX_DEV") == "1",
    )
