import logging

import uvicorn

from dabox.app import create_app, default_services
from dabox.config import load_service_config


def run_service() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_service_config()
    config.media_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(default_services(config))
    # proxy_headers=False: the loopback check must see the real peer address.
    uvicorn.run(app, host=config.host, port=config.port, proxy_headers=False)


if __name__ == "__main__":
    run_service()
