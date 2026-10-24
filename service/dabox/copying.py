"""Copies films, albums, games and TV shows from a USB stick to the box, keeping their metadata and hidden state.

Files are written under a hidden ".partial" name and renamed at the end. A new folder
(a film, an album, a new show) is built whole under its ".partial" name, so a pulled
stick never leaves half an item on the box.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dabox.library import FILMS_FOLDER, GAMES_FOLDER, MUSIC_FOLDER, TV_FOLDER, ItemNamer
from dabox.metadata import MetadataStore
from dabox.models import Album, Film, Game, MediaSource, Show
from dabox.store import Store
from dabox.uploads import safe_path_component

_COPY_CHUNK = 4 * 1024 * 1024

CopyItem = Film | Album | Game | Show
# Called after each chunk with the number of bytes written. It may raise to stop the copy.
ByteCounter = Callable[[int], None]


class CopyRejected(Exception):
    pass


@dataclass(frozen=True)
class CopyFile:
    source: Path
    target: Path
    size: int


@dataclass(frozen=True)
class CopyPlan:
    """What one item puts on the box. `destination` is the folder or file that appears."""

    destination: Path
    files: list[CopyFile]
    # The whole item goes into a folder that is not on the box yet.
    new_folder: bool

    @property
    def size(self) -> int:
        return sum(file.size for file in self.files)


def copy_destination(item: CopyItem, media_dir: Path) -> Path:
    match item:
        case Film():
            return media_dir / FILMS_FOLDER / safe_path_component(item.folder.name)
        case Album():
            return media_dir / MUSIC_FOLDER / safe_path_component(item.artist) / safe_path_component(item.title)
        case Game():
            return media_dir / GAMES_FOLDER / item.system / safe_path_component(item.path.name)
        case Show():
            return media_dir / TV_FOLDER / safe_path_component(item.folder.name)


def _visible_files(folder: Path) -> list[Path]:
    """Every file under the folder, without hidden files and folders (for example macOS "._" files)."""
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    )


def _copy_file(source: Path, target: Path) -> CopyFile:
    return CopyFile(source, target, source.stat().st_size)


def plan_copy(item: CopyItem, media_dir: Path, box_episode_fingerprints: frozenset[str] = frozenset()) -> CopyPlan:
    """A show can already be on the box in part: only its missing episodes and files are copied."""
    destination = copy_destination(item, media_dir)
    match item:
        case Film() if item.folder.is_dir():
            files = [_copy_file(path, destination / path.relative_to(item.folder)) for path in _visible_files(item.folder)]
            return CopyPlan(destination, files, new_folder=True)
        case Film():
            return CopyPlan(destination, [_copy_file(item.path, destination)], new_folder=False)
        case Album():
            # Only the album's own files, not other things in the folder.
            sources = [track.path for track in item.tracks] + ([item.art_path] if item.art_path is not None else [])
            return CopyPlan(destination, [_copy_file(path, destination / path.name) for path in sources], new_folder=True)
        case Game():
            files = [_copy_file(item.path, destination)]
            if item.art_path is not None and not destination.with_suffix(item.art_path.suffix).exists():
                files.append(_copy_file(item.art_path, destination.with_suffix(item.art_path.suffix)))
            return CopyPlan(destination, files, new_folder=False)
        case Show():
            on_box = {episode.path for episode in item.episodes if episode.fingerprint in box_episode_fingerprints}
            files = [
                _copy_file(path, destination / path.relative_to(item.folder))
                for path in _visible_files(item.folder)
                if path not in on_box and not (destination / path.relative_to(item.folder)).exists()
            ]
            return CopyPlan(destination, files, new_folder=not destination.exists())


def _partial_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.partial")


def _write_file(source: Path, target: Path, count_bytes: ByteCounter | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, target.open("wb") as writer:
        while chunk := reader.read(_COPY_CHUNK):
            writer.write(chunk)
            if count_bytes is not None:
                count_bytes(len(chunk))


def run_copy(plan: CopyPlan, count_bytes: ByteCounter | None = None) -> None:
    if plan.new_folder:
        partial = _partial_path(plan.destination)
        shutil.rmtree(partial, ignore_errors=True)
        try:
            for file in plan.files:
                _write_file(file.source, partial / file.target.relative_to(plan.destination), count_bytes)
            partial.mkdir(parents=True, exist_ok=True)
            partial.rename(plan.destination)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        return
    for file in plan.files:
        partial = _partial_path(file.target)
        try:
            _write_file(file.source, partial, count_bytes)
            partial.rename(file.target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


def copy_to_box(item: Film | Album | Game, media_dir: Path) -> Path:
    if item.source is not MediaSource.USB:
        raise CopyRejected("This item is already on the box")
    plan = plan_copy(item, media_dir)
    if plan.destination.exists():
        raise CopyRejected(f"'{plan.destination.name}' is already on the box")
    run_copy(plan)
    return plan.destination


def box_id_after_copy(item: Film | Album | Game, destination: Path, media_dir: Path) -> str:
    """The id the copied item gets on the box (box ids come from paths)."""
    namer = ItemNamer(media_dir, None)
    match item:
        case Film():
            video = destination / item.path.name if item.folder.is_dir() else destination
            return namer.file_id("film", video, item.fingerprint)
        case Album():
            return namer.album_id(destination, [])
        case Game():
            return namer.file_id("game", destination, item.fingerprint)


def carry_over(item: Film | Album | Game, destination: Path, media_dir: Path, store: Store, metadata: MetadataStore) -> None:
    """Box items get path-based ids, so the copy gets the stick item's metadata and hidden state."""
    new_id = box_id_after_copy(item, destination, media_dir)
    record = metadata.get(item.id)
    if record is not None:
        if record.art_file:
            cached = metadata.art_dir / record.art_file
            if cached.is_file():
                record.art_file = metadata.save_art(new_id, cached.read_bytes())
        metadata.put(new_id, record)
    if item.id in store.hidden_item_ids():
        store.set_hidden(new_id, True)
