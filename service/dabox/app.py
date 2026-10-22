from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dabox import admin_api, box_api
from dabox.auth import AdminAuth
from dabox.box_state import BoxState
from dabox.config import ServiceConfig
from dabox.library import LibraryIndex
from dabox.services import Services
from dabox.store import Store
from dabox.system import (
    FakeNetwork,
    FakeTimezone,
    NetworkBackend,
    NmcliNetwork,
    TimedatectlTimezone,
    TimezoneBackend,
)

ADMIN_WEB_DIR = Path(__file__).parent / "admin_web"


def build_services(
    config: ServiceConfig,
    network: NetworkBackend,
    timezone_backend: TimezoneBackend,
) -> Services:
    store = Store(config.data_dir / "dabox.db")
    auth = AdminAuth(store)
    return Services(
        store=store,
        auth=auth,
        box_state=BoxState(store, auth, timezone_backend),
        library=LibraryIndex(config.media_dir),
        network=network,
        incoming_dir=config.data_dir / "incoming",
        admin_port=config.port,
    )


def default_services(config: ServiceConfig) -> Services:
    if config.dev_mode:
        return build_services(config, FakeNetwork(), FakeTimezone())
    return build_services(config, NmcliNetwork(), TimedatectlTimezone())


def create_app(services: Services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # The service starts at boot, so this is how "shut-down turns parent mode off" works.
        services.box_state.set_parent_mode(False)
        services.library.rescan()
        yield

    app = FastAPI(title="da-box", lifespan=lifespan)
    app.state.services = services
    app.include_router(box_api.router)
    app.include_router(admin_api.public_router)
    app.include_router(admin_api.router)
    app.mount("/", StaticFiles(directory=ADMIN_WEB_DIR, html=True), name="admin-web")
    return app
