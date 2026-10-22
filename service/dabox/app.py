from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dabox import admin_api, box_api, guide_api, limits_api
from dabox.auth import AdminAuth
from dabox.background import BackgroundWorkers
from dabox.box_state import BoxState
from dabox.channels import Guide
from dabox.durations import Durations
from dabox.config import ServiceConfig
from dabox.library import LibraryIndex
from dabox.limits import UsageStore
from dabox.limits_service import AgentClient, FakePower, HttpAgentClient, LimitsService, PowerBackend, SystemdPower
from dabox.metadata import HttpClient, MetadataService, MetadataStore, UrllibClient
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
from dabox.usb import FakeUsb, UdisksUsb, UsbBackend

ADMIN_WEB_DIR = Path(__file__).parent / "admin_web"


def build_services(
    config: ServiceConfig,
    network: NetworkBackend,
    timezone_backend: TimezoneBackend,
    usb: UsbBackend,
    http_client: HttpClient,
    agent: AgentClient,
    power: PowerBackend,
) -> Services:
    store = Store(config.data_dir / "dabox.db")
    auth = AdminAuth(store)
    box_state = BoxState(store, auth, timezone_backend)
    library = LibraryIndex(config.media_dir)
    durations = Durations(store)
    guide = Guide(store, library, durations, lambda: box_state.timezone)
    return Services(
        store=store,
        auth=auth,
        box_state=box_state,
        library=library,
        network=network,
        usb=usb,
        metadata=MetadataService(MetadataStore(store, config.data_dir / "art"), http_client),
        durations=durations,
        guide=guide,
        limits=LimitsService(UsageStore(store), box_state, guide.now, agent, power),
        core_dirs=config.core_dirs,
        incoming_dir=config.data_dir / "incoming",
        admin_port=config.port,
    )


def default_services(config: ServiceConfig) -> Services:
    agent = HttpAgentClient(config.agent_url)
    if config.dev_mode:
        return build_services(config, FakeNetwork(), FakeTimezone(), FakeUsb(config.fake_usb_dir), UrllibClient(), agent, FakePower())
    return build_services(config, NmcliNetwork(), TimedatectlTimezone(), UdisksUsb(), UrllibClient(), agent, SystemdPower())


def create_app(services: Services, run_workers: bool = True) -> FastAPI:
    workers = BackgroundWorkers(services)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # The service starts at boot, so this is how "shut-down turns parent mode off" works.
        services.box_state.set_parent_mode(False)
        services.rescan_library()
        if run_workers:
            workers.start()
        yield
        if run_workers:
            workers.stop()

    app = FastAPI(title="da-box", lifespan=lifespan)
    app.state.services = services
    app.state.workers = workers
    app.include_router(box_api.router)
    app.include_router(admin_api.public_router)
    app.include_router(admin_api.router)
    app.include_router(guide_api.box_router)
    app.include_router(guide_api.admin_router)
    app.include_router(limits_api.box_router)
    app.include_router(limits_api.admin_router)
    app.mount("/", StaticFiles(directory=ADMIN_WEB_DIR, html=True), name="admin-web")
    return app
