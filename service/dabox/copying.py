"""Copies videos, groups, albums and games from a USB stick to the box, keeping their metadata and hidden state.

Each item goes into the box's own layout with a clean name, wherever it was on the stick
(DESIGN_CORRECTIONS_2.md, part 3): Videos/<name>/, Music/<artist>/<album>/, Games/<system>/.
Files are written under a hidden ".partial" name and renamed at the end. A new folder
(a video, an album, a new group) is built whole under its ".partial" name, so a pulled
stick never leaves half an item on the box.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dabox.library import GAMES_FOLDER, MUSIC_FOLDER, VIDEOS_FOLDER, ItemNamer, item_id
from dabox.metadata import MetadataStore
from dabox.models import Album, Film, Game, Library, MediaSource, Show
from dabox.store import Store
from dabox.uploads import safe_path_component

_COPY_CHUNK = 4 * 1024 * 1024
# What goes with a loose video: its art, details and subtitles.
_COMPANION_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"})

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


def _video_name(film: Film) -> str:
    return f"{film.title} ({film.year})" if film.year else film.title


def _free_name(path: Path) -> Path:
    """`path`, or "<name> (2)", "<name> (3)", ... if something else has that name."""
    if not path.exists():
        return path
    number = 2
    while path.with_name(f"{path.name} ({number})").exists():
        number += 1
    return path.with_name(f"{path.name} ({number})")


def copy_destination(item: CopyItem, media_dir: Path) -> Path:
    """Where the item goes in the box's layout (before a clash with another item is solved)."""
    match item:
        case Film():
            return media_dir / VIDEOS_FOLDER / safe_path_component(_video_name(item))
        case Album():
            return media_dir / MUSIC_FOLDER / safe_path_component(item.artist) / safe_path_component(item.title)
        case Game():
            return media_dir / GAMES_FOLDER / item.system / safe_path_component(item.path.name)
        case Show():
            return media_dir / VIDEOS_FOLDER / safe_path_component(item.title)


def _visible_files(folder: Path) -> list[Path]:
    """Every file under the folder, without hidden files and folders (for example macOS "._" files)."""
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    )


def _companions(video: Path) -> list[Path]:
    """A loose video's own art, details and subtitles: files that start with its name."""
    return sorted(
        path for path in video.parent.iterdir()
        if path.is_file() and path != video and not path.name.startswith(".") and path.stem.startswith(video.stem)
        and path.suffix.lower() in _COMPANION_EXTENSIONS
    )


def _copy_file(source: Path, target: Path) -> CopyFile:
    return CopyFile(source, target, source.stat().st_size)


def _track_file_name(track_number: int | None, title: str, suffix: str, taken: set[str]) -> str:
    """"07 Hello Goodbye.mp3"; a second song with the same name gets " (2)"."""
    stem = safe_path_component(f"{track_number:02d} {title}" if track_number else title)
    name, number = f"{stem}{suffix}", 2
    while name.casefold() in taken:
        name, number = f"{stem} ({number}){suffix}", number + 1
    taken.add(name.casefold())
    return name


def box_group_folders(library: Library) -> dict[str, Path]:
    """Each box group video's fingerprint -> its group's folder, to finish a group that is on the box in part."""
    return {
        episode.fingerprint: show.folder
        for show in library.shows if show.source is MediaSource.BOX for episode in show.episodes
    }


def plan_copy(item: CopyItem, media_dir: Path, box_groups: dict[str, Path] | None = None) -> CopyPlan:
    """A group can already be on the box in part: then only its missing videos go into that
    box group's folder (`box_groups`, from box_group_folders)."""
    box_groups = box_groups or {}
    destination = copy_destination(item, media_dir)
    match item:
        case Film():
            destination = _free_name(destination)
            sources = _visible_files(item.folder) if item.folder.is_dir() else [item.path, *_companions(item.path)]
            root = item.folder if item.folder.is_dir() else item.path.parent
            return CopyPlan(destination, [_copy_file(path, destination / path.relative_to(root)) for path in sources], new_folder=True)
        case Album():
            destination = _free_name(destination)
            taken: set[str] = set()
            files = [
                _copy_file(track.path, destination / _track_file_name(track.track_number, track.title, track.path.suffix.lower(), taken))
                for track in item.tracks
            ]
            if item.art_path is not None:
                files.append(_copy_file(item.art_path, destination / f"cover{item.art_path.suffix.lower()}"))
            return CopyPlan(destination, files, new_folder=True)
        case Game():
            files = [_copy_file(item.path, destination)]
            if item.art_path is not None and not destination.with_suffix(item.art_path.suffix).exists():
                files.append(_copy_file(item.art_path, destination.with_suffix(item.art_path.suffix)))
            return CopyPlan(destination, files, new_folder=False)
        case Show():
            existing = next((box_groups[episode.fingerprint] for episode in item.episodes if episode.fingerprint in box_groups), None)
            # Another group with the same name is not this one.
            destination = existing if existing is not None else _free_name(destination)
            on_box = {episode.path for episode in item.episodes if episode.fingerprint in box_groups}
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


def copy_to_box(item: CopyItem, media_dir: Path, box_groups: dict[str, Path] | None = None) -> Path:
    if item.source is not MediaSource.USB:
        raise CopyRejected("This item is already on the box")
    plan = plan_copy(item, media_dir, box_groups)
    if not plan.files or (plan.destination.exists() and not isinstance(item, Show)):
        raise CopyRejected(f"'{plan.destination.name}' is already on the box")
    run_copy(plan)
    return plan.destination


def box_id_after_copy(item: CopyItem, destination: Path, media_dir: Path) -> str:
    """The id the copied item gets on the box (box ids come from paths)."""
    namer = ItemNamer(media_dir, None)
    match item:
        case Film():
            root = item.folder if item.folder.is_dir() else item.path.parent
            return namer.file_id("film", destination / item.path.relative_to(root), item.fingerprint)
        case Album():
            return namer.album_id(destination, [])
        case Game():
            return namer.file_id("game", destination, item.fingerprint)
        case Show():
            return item_id("show", str(destination.relative_to(media_dir)))


def carry_over(item: CopyItem, destination: Path, media_dir: Path, store: Store, metadata: MetadataStore) -> None:
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
