"""Copies a film or album from a USB stick to the box, keeping its metadata and hidden state."""

import shutil
from pathlib import Path

from dabox.library import FILMS_FOLDER, MUSIC_FOLDER, ItemNamer
from dabox.models import Album, Film, MediaSource
from dabox.uploads import safe_path_component


class CopyRejected(Exception):
    pass


def copy_destination(item: Film | Album, media_dir: Path) -> Path:
    if isinstance(item, Film):
        return media_dir / FILMS_FOLDER / safe_path_component(item.folder.name)
    return media_dir / MUSIC_FOLDER / safe_path_component(item.artist) / safe_path_component(item.title)


def box_id_after_copy(item: Film | Album, destination: Path, media_dir: Path) -> str:
    """The id the copied item gets on the box (box ids come from paths)."""
    namer = ItemNamer(media_dir, None)
    if isinstance(item, Film):
        video = destination / item.path.name if item.folder.is_dir() else destination
        return namer.file_id("film", video, item.fingerprint)
    return namer.album_id(destination, [])


def copy_to_box(item: Film | Album, media_dir: Path) -> Path:
    if item.source is not MediaSource.USB:
        raise CopyRejected("This item is already on the box")
    destination = copy_destination(item, media_dir)
    if destination.exists():
        raise CopyRejected(f"'{destination.name}' is already on the box")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    shutil.rmtree(partial, ignore_errors=True)
    if isinstance(item, Film) and not item.folder.is_dir():
        shutil.copyfile(item.path, partial)
    elif isinstance(item, Film):
        shutil.copytree(item.folder, partial, copy_function=shutil.copyfile)
    else:
        # Only the album's own files, not other things in the folder.
        partial.mkdir()
        for track in item.tracks:
            shutil.copyfile(track.path, partial / track.path.name)
        if item.art_path is not None:
            shutil.copyfile(item.art_path, partial / item.art_path.name)
    partial.rename(destination)
    return destination
