import re
import shutil
from pathlib import Path
from typing import BinaryIO

from dabox.library import AUDIO_EXTENSIONS, FILMS_FOLDER, MUSIC_FOLDER, UNKNOWN_ARTIST, VIDEO_EXTENSIONS

_UNSAFE_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_ALLOWED_ART_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})


class UploadRejected(Exception):
    pass


def safe_path_component(name: str) -> str:
    """Makes a user-typed name safe to use as one folder or file name."""
    cleaned = _UNSAFE_CHARACTERS.sub("", name).strip().strip(".")
    if not cleaned:
        raise UploadRejected(f"'{name}' is not a usable name")
    return cleaned[:150]


def _checked_file_name(file_name: str, allowed_extensions: frozenset[str]) -> str:
    safe_name = safe_path_component(Path(file_name).name)
    if Path(safe_name).suffix.lower() not in allowed_extensions:
        raise UploadRejected(f"'{file_name}' is not a supported file type")
    return safe_name


def film_folder(media_dir: Path, title: str, year: int | None) -> Path:
    folder_name = safe_path_component(title) + (f" ({year})" if year else "")
    return media_dir / FILMS_FOLDER / folder_name


def film_destination(media_dir: Path, title: str, year: int | None, file_name: str) -> Path:
    return film_folder(media_dir, title, year) / _checked_file_name(file_name, VIDEO_EXTENSIONS)


def film_poster_destination(media_dir: Path, title: str, year: int | None, file_name: str) -> Path:
    extension = Path(_checked_file_name(file_name, _ALLOWED_ART_EXTENSIONS)).suffix.lower()
    return film_folder(media_dir, title, year) / f"poster{'.png' if extension == '.png' else '.jpg'}"


def music_destination(media_dir: Path, artist: str, album: str, file_name: str) -> Path:
    artist_folder = safe_path_component(artist or UNKNOWN_ARTIST)
    album_folder = safe_path_component(album or "Unknown album")
    return media_dir / MUSIC_FOLDER / artist_folder / album_folder / _checked_file_name(file_name, AUDIO_EXTENSIONS)


def save_stream(source: BinaryIO, destination: Path) -> None:
    """Writes to a temporary name first, so a broken upload never looks like a real file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    with partial.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    partial.replace(destination)
