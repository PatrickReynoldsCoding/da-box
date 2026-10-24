"""Background threads: watch for USB sticks, fetch metadata for new items, and keep the TV guide filled."""

import logging
import threading
from datetime import timedelta

from dabox.metadata import MetadataError
from dabox.services import Services

log = logging.getLogger(__name__)

USB_POLL_SECONDS = 3.0
METADATA_IDLE_SECONDS = 60.0
GUIDE_IDLE_SECONDS = 300.0
LIMITS_TICK_SECONDS = 2.0


class BackgroundWorkers:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._stick_ids: list[str] | None = None

    def start(self) -> None:
        for target in (self._watch_usb, self._fetch_metadata, self._keep_guide, self._enforce_limits):
            thread = threading.Thread(target=target, daemon=True, name=target.__name__)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        self._services.metadata_wanted.set()
        self._services.guide_wanted.set()
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
        for item in services.metadata.items_to_fetch([*library.films, *library.shows, *library.albums, *library.games]):
            if self._stop.is_set():
                break
            try:
                services.metadata.auto_fetch(item)
            except MetadataError as error:
                log.warning("Metadata for %s: %s", item.title, error)
            fetched += 1
        return fetched

    def update_guide_once(self) -> None:
        """Measures new box files, then makes sure this week (and on Sundays, next
        week) has a guide."""
        services = self._services
        library = services.library.library
        files = {}
        # USB films too: the limits need every film's length.
        for film in library.films:
            files[film.fingerprint] = film.path
        for show in library.shows:
            for episode in show.episodes:
                files[episode.fingerprint] = episode.path
        for album in library.albums:
            if album.source == "box":
                for track in album.tracks:
                    files[track.fingerprint] = track.path
        services.durations.measure_missing(files)

        guide = services.guide
        now = guide.now()
        guide.ensure_week(now)
        if now.weekday() == 6:
            guide.ensure_week(now + timedelta(days=1))

    def _keep_guide(self) -> None:
        while not self._stop.is_set():
            try:
                self.update_guide_once()
            except Exception:
                log.exception("Guide update failed")
            self._services.guide_wanted.wait(GUIDE_IDLE_SECONDS)
            self._services.guide_wanted.clear()

    def _enforce_limits(self) -> None:
        while not self._stop.is_set():
            try:
                self._services.limits.tick()
            except Exception:
                log.exception("Limits check failed")
            self._stop.wait(LIMITS_TICK_SECONDS)

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
