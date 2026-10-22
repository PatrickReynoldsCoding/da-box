from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Request

from dabox.auth import AdminAuth
from dabox.box_state import BoxState
from dabox.library import LibraryIndex
from dabox.store import Store
from dabox.system import NetworkBackend

SESSION_COOKIE = "dabox_session"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class Services:
    store: Store
    auth: AdminAuth
    box_state: BoxState
    library: LibraryIndex
    network: NetworkBackend
    incoming_dir: Path
    admin_port: int


def get_services(request: Request) -> Services:
    return request.app.state.services


def require_box_client(request: Request) -> None:
    """The box API is for the UI and agent on the box itself, never for the network."""
    host = request.client.host if request.client else ""
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="The box API is only available on the box")


def require_admin(request: Request) -> None:
    services = get_services(request)
    if not services.auth.is_session_valid(request.cookies.get(SESSION_COOKIE), datetime.now()):
        raise HTTPException(status_code=401, detail="Log in with the PIN")
