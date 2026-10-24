import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Request

from dabox.auth import AdminAuth
from dabox.box_state import BoxState
from dabox.channels import Guide
from dabox.durations import Durations
from dabox.library import LibraryIndex
from dabox.limits_service import LimitsService
from dabox.maintenance import Updater
from dabox.metadata import MetadataService
from dabox.models import Album, Film, Game
from dabox.playlists import Playlists
from dabox.software_update import SoftwareUpdates
from dabox.store import Store
from dabox.system import NetworkBackend
from dabox.usb import UsbBackend, UsbStick
from dabox.usb_copy import UsbCopier

SESSION_COOKIE = "dabox_session"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class Services:
    store: Store
    auth: AdminAuth
    box_state: BoxState
    library: LibraryIndex
    network: NetworkBackend
    usb: UsbBackend
    metadata: MetadataService
    durations: Durations
    guide: Guide
    limits: LimitsService
    updater: Updater
    software: SoftwareUpdates
    usb_copier: UsbCopier
    playlists: Playlists
    core_dirs: tuple[Path, ...]
    incoming_dir: Path
    admin_port: int
    # Set to wake the metadata and guide workers after the library changes.
    metadata_wanted: threading.Event = field(default_factory=threading.Event)
    guide_wanted: threading.Event = field(default_factory=threading.Event)

    def rescan_library(self, sticks: list[UsbStick] | None = None) -> None:
        self.library.rescan(sticks)
        self.metadata_wanted.set()
        self.guide_wanted.set()

    def item_or_404(self, item_id: str) -> Film | Album | Game:
        item = self.library.find(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="No such item")
        return item


def get_services(request: Request) -> Services:
    return request.app.state.services


def require_box_client(request: Request) -> None:
    """The box API is for the UI and agent on the box itself, never for the network."""
    host = request.client.host if request.client else ""
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="The box API is only available on the box")


def require_parent_mode(request: Request) -> None:
    """Box routes that only a parent may use on the TV (Copy from USB)."""
    if not get_services(request).box_state.parent_mode:
        raise HTTPException(status_code=403, detail="Only in parent mode")


def require_admin(request: Request) -> None:
    services = get_services(request)
    if not services.auth.is_session_valid(request.cookies.get(SESSION_COOKIE), datetime.now()):
        raise HTTPException(status_code=401, detail="Log in with the PIN")
