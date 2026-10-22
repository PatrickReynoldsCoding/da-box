"""Background threads: watch for USB sticks, and fetch metadata for new items."""

import logging
import threading

from dabox.metadata import MetadataError
from dabox.services import Services

log = logging.getLogger(__name__)

USB_POLL_SECONDS = 3.0
METADATA_IDLE_SECONDS = 60.0


class BackgroundWorkers:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._stick_ids: list[str] | None = None

    def start(self) -> None:
        for target in (self._watch_usb, self._fetch_metadata):
            thread = threading.Thread(target=target, daemon=True, name=target.__name__)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        self._services.metadata_wanted.set()
        for thread in self._threads:
            thread.join(timeout=5)

    def check_usb_once(self) -> bool:
        """Rescans the library if the set of sticks changed. Returns True if it did."""
        sticks = self._services.usb.sticks()
        stick_ids = [stick.id for stick in sticks]
        if stick_ids == self._stick_ids:
            return False
        self._stick_ids = stick_ids
        self._services.rescan_library(sticks)
        return True

    def fetch_metadata_once(self) -> int:
        services = self._services
        library = services.library.library
        fetched = 0
        for item in services.metadata.items_to_fetch([*library.films, *library.albums]):
            if self._stop.is_set():
                break
            try:
                services.metadata.auto_fetch(item)
            except MetadataError as error:
                log.warning("Metadata for %s: %s", item.title, error)
            fetched += 1
        return fetched

    def _watch_usb(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_usb_once()
            except Exception:  # A bad stick must never stop the watcher.
                log.exception("USB check failed")
            self._stop.wait(USB_POLL_SECONDS)

    def _fetch_metadata(self) -> None:
        while not self._stop.is_set():
            self._services.metadata_wanted.wait(METADATA_IDLE_SECONDS)
            self._services.metadata_wanted.clear()
            try:
                self.fetch_metadata_once()
            except Exception:
                log.exception("Metadata fetch failed")
