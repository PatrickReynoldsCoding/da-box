"""Copy from USB on the box: list a stick as a tree, check the space, and copy the ticked items in the background.

One copy runs at a time. It copies item by item, skips items that are already on the
box, and scans the library (art and details follow) when it ends. The box can be used
while it runs.
"""

import errno
import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import monotonic

from pydantic import BaseModel

from dabox.copying import CopyItem, CopyPlan, carry_over, plan_copy, run_copy
from dabox.library import FILMS_FOLDER, GAMES_FOLDER, MUSIC_FOLDER, TV_FOLDER, ItemNamer, scan_films, scan_games, scan_music, scan_shows
from dabox.metadata import MetadataStore
from dabox.models import Album, Film, Game, Library, MediaSource, Show
from dabox.store import Store
from dabox.systems import SYSTEMS
from dabox.usb import UsbBackend, UsbStick

log = logging.getLogger(__name__)

# Room the box keeps free for its database, logs and art.
SPACE_RESERVE_BYTES = 500 * 1024 * 1024
TREE_FOLDERS = (("films", FILMS_FOLDER), ("tv", TV_FOLDER), ("music", MUSIC_FOLDER), ("games", GAMES_FOLDER))


class UsbTreeItem(BaseModel):
    # "<folder key>:<path on the stick>", for example "films:Films/Cars (2006)".
    id: str
    title: str
    subtitle: str | None
    # What the copy adds to the box. Items on the box add nothing.
    bytes: int
    on_box: bool


class UsbTreeFolder(BaseModel):
    key: str
    name: str
    items: list[UsbTreeItem]
    bytes: int


class UsbStickTree(BaseModel):
    stick_id: str
    label: str
    folders: list[UsbTreeFolder]


class SpaceCheck(BaseModel):
    items: int
    # Ticked items that are on the box already. The copy skips them.
    skipped: int
    bytes_needed: int
    bytes_free: int
    fits: bool


class CopyState(StrEnum):
    IDLE = "idle"
    COPYING = "copying"
    DONE = "done"
    # Stopped by the parent, or the stick was pulled out.
    STOPPED = "stopped"
    FAILED = "failed"


class CopyProgress(BaseModel):
    # Goes up by one for each copy, so the UI shows the end message once.
    job_id: int
    state: CopyState
    stick_label: str | None
    items_total: int
    items_done: int
    bytes_total: int
    bytes_done: int
    current: str | None
    skipped: list[str]
    errors: list[str]
    message: str | None
    seconds_since_end: float | None


@dataclass(frozen=True)
class StickItem:
    id: str
    folder_key: str
    item: CopyItem
    title: str
    subtitle: str | None
    plan: CopyPlan
    on_box: bool

    def tree_view(self) -> UsbTreeItem:
        return UsbTreeItem(
            id=self.id, title=self.title, subtitle=self.subtitle, bytes=0 if self.on_box else self.plan.size, on_box=self.on_box,
        )


class _BoxContent:
    """Fingerprints of what is on the box, to find stick items that are there already."""

    def __init__(self, library: Library) -> None:
        self.films = {film.fingerprint for film in library.films if film.source is MediaSource.BOX}
        self.albums = [{track.fingerprint for track in album.tracks} for album in library.albums if album.source is MediaSource.BOX]
        self.games = {game.fingerprint for game in library.games if game.source is MediaSource.BOX}
        self.episodes = frozenset(episode.fingerprint for show in library.shows for episode in show.episodes)


def _tree_id(folder_key: str, path: Path, stick: UsbStick) -> str:
    return f"{folder_key}:{path.relative_to(stick.path)}"


def _stick_item(item: CopyItem, stick: UsbStick, box: _BoxContent, media_dir: Path) -> StickItem:
    match item:
        case Film():
            plan = plan_copy(item, media_dir)
            on_box = item.fingerprint in box.films or plan.destination.exists()
            return StickItem(_tree_id("films", item.folder, stick), "films", item, item.title, str(item.year) if item.year else None, plan, on_box)
        case Show():
            plan = plan_copy(item, media_dir, box.episodes)
            on_box = all(episode.fingerprint in box.episodes for episode in item.episodes)
            count = len(item.episodes)
            return StickItem(_tree_id("tv", item.folder, stick), "tv", item, item.title, f"{count} episode{'s' * (count != 1)}", plan, on_box)
        case Album():
            plan = plan_copy(item, media_dir)
            fingerprints = {track.fingerprint for track in item.tracks}
            on_box = any(fingerprints <= known for known in box.albums) or plan.destination.exists()
            return StickItem(_tree_id("music", item.folder, stick), "music", item, item.title, item.artist, plan, on_box)
        case Game():
            plan = plan_copy(item, media_dir)
            on_box = item.fingerprint in box.games or plan.destination.exists()
            return StickItem(_tree_id("games", item.path, stick), "games", item, item.title, SYSTEMS[item.system].name, plan, on_box)


def stick_items(stick: UsbStick, library: Library, media_dir: Path) -> list[StickItem]:
    namer = ItemNamer(stick.path, stick)
    box = _BoxContent(library)
    found: list[CopyItem] = [*scan_films(namer), *scan_shows(stick.path), *scan_music(namer), *scan_games(namer)]
    return [_stick_item(item, stick, box, media_dir) for item in found]


def stick_item_for(item: Film | Album | Game, stick: UsbStick, library: Library, media_dir: Path) -> StickItem:
    """One library item from a stick, for "Copy to the box" on a single film, album or game."""
    return _stick_item(item, stick, _BoxContent(library), media_dir)


def stick_tree(stick: UsbStick, items: list[StickItem]) -> UsbStickTree:
    folders: list[UsbTreeFolder] = []
    for key, name in TREE_FOLDERS:
        views = sorted((item.tree_view() for item in items if item.folder_key == key), key=lambda view: view.title.lower())
        if views:
            folders.append(UsbTreeFolder(key=key, name=name, items=views, bytes=sum(view.bytes for view in views)))
    return UsbStickTree(stick_id=stick.id, label=stick.label, folders=folders)


def free_bytes(media_dir: Path) -> int:
    media_dir.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(media_dir).free


def check_space(items: list[StickItem], media_dir: Path) -> SpaceCheck:
    to_copy = [item for item in items if not item.on_box]
    needed = sum(item.plan.size for item in to_copy)
    available = free_bytes(media_dir)
    return SpaceCheck(
        items=len(to_copy), skipped=len(items) - len(to_copy), bytes_needed=needed, bytes_free=available,
        fits=needed + SPACE_RESERVE_BYTES <= available,
    )


class CopyStopped(Exception):
    pass


class UsbCopier:
    """Runs one copy job at a time and reports its progress."""

    def __init__(self, usb: UsbBackend, media_dir: Path, store: Store, metadata: MetadataStore) -> None:
        self._usb = usb
        self._media_dir = media_dir
        self._store = store
        self._metadata = metadata
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ended_at: float | None = None
        self._progress = CopyProgress(
            job_id=0, state=CopyState.IDLE, stick_label=None, items_total=0, items_done=0, bytes_total=0, bytes_done=0,
            current=None, skipped=[], errors=[], message=None, seconds_since_end=None,
        )

    def progress(self) -> CopyProgress:
        with self._lock:
            since = monotonic() - self._ended_at if self._ended_at is not None else None
            return self._progress.model_copy(deep=True, update={"seconds_since_end": since})

    def running(self) -> bool:
        with self._lock:
            return self._progress.state is CopyState.COPYING

    def start(self, stick: UsbStick, items: list[StickItem], on_end: Callable[[], None], background: bool = True) -> CopyProgress:
        """`on_end` runs after the job (also a stopped one), to scan the library."""
        to_copy = [item for item in items if not item.on_box]
        with self._lock:
            if self._progress.state is CopyState.COPYING:
                raise RuntimeError("A copy is already running")
            self._stop.clear()
            self._ended_at = None
            self._progress = CopyProgress(
                job_id=self._progress.job_id + 1, state=CopyState.COPYING, stick_label=stick.label,
                items_total=len(to_copy), items_done=0, bytes_total=sum(item.plan.size for item in to_copy), bytes_done=0,
                current=None, skipped=[item.title for item in items if item.on_box], errors=[], message=None, seconds_since_end=None,
            )
        if background:
            threading.Thread(target=self._run, args=(stick, to_copy, on_end), daemon=True, name="usb_copy").start()
        else:
            self._run(stick, to_copy, on_end)
        return self.progress()

    def stop(self) -> None:
        self._stop.set()

    def _count_bytes(self, count: int) -> None:
        if self._stop.is_set():
            raise CopyStopped()
        with self._lock:
            self._progress.bytes_done += count

    def _stick_present(self, stick: UsbStick) -> bool:
        try:
            return stick.path.is_dir() and any(found.id == stick.id for found in self._usb.sticks())
        except OSError:
            return False

    def _run(self, stick: UsbStick, items: list[StickItem], on_end: Callable[[], None]) -> None:
        try:
            state, message = self._copy_all(stick, items)
        except Exception as error:  # Never leave the job stuck in "copying".
            log.exception("USB copy failed")
            state, message = CopyState.FAILED, f"The copy failed: {error}"
        with self._lock:
            self._progress.current = None
        # Scan before the job reports its end, so the new items are there when the TV says "done".
        try:
            on_end()
        except Exception:
            log.exception("Library scan after the USB copy failed")
        with self._lock:
            self._progress.state = state
            self._progress.message = message
            self._ended_at = monotonic()
        log.info("USB copy from %s ended: %s", stick.label, message)

    def _copy_all(self, stick: UsbStick, items: list[StickItem]) -> tuple[CopyState, str]:
        total = len(items)
        for item in items:
            done = self._progress.items_done
            if self._stop.is_set():
                return CopyState.STOPPED, f"Copy stopped. Copied {done} of {total}."
            if not stick.path.is_dir():
                return CopyState.STOPPED, f"USB removed. Copied {done} of {total}. Plug it in again to finish."
            with self._lock:
                self._progress.current = item.title
            try:
                copied = self._copy_one(item)
            except CopyStopped:
                return CopyState.STOPPED, f"Copy stopped. Copied {done} of {total}."
            except OSError as error:
                if not self._stick_present(stick):
                    return CopyState.STOPPED, f"USB removed. Copied {done} of {total}. Plug it in again to finish."
                if error.errno == errno.ENOSPC:
                    return CopyState.FAILED, f"The box is full. Copied {done} of {total}."
                with self._lock:
                    self._progress.errors.append(f"{item.title}: {error.strerror or error}")
                continue
            if copied:
                with self._lock:
                    self._progress.items_done += 1
        return CopyState.DONE, self._done_message()

    def _copy_one(self, item: StickItem) -> bool:
        """Returns False if the item was skipped."""
        # Something may have put the item on the box since the check (the admin app, an upload).
        if not isinstance(item.item, Show) and item.plan.destination.exists():
            with self._lock:
                self._progress.skipped.append(item.title)
            return False
        run_copy(item.plan, self._count_bytes)
        if not isinstance(item.item, Show):
            carry_over(item.item, item.plan.destination, self._media_dir, self._store, self._metadata)
        return True

    def _done_message(self) -> str:
        progress = self._progress
        done = progress.items_done
        parts = [f"Copied {done} item{'s' * (done != 1)} from USB."]
        if progress.skipped:
            parts.append(f"{len(progress.skipped)} already on the box.")
        if progress.errors:
            parts.append(f"{len(progress.errors)} could not be copied.")
        return " ".join(parts)
