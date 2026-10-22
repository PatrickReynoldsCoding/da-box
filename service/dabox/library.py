import hashlib
import re
import threading
from collections.abc import Iterable
from pathlib import Path

import mutagen

from dabox.models import Album, Film, Library, Track

FILMS_FOLDER = "Films"
MUSIC_FOLDER = "Music"

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"})
ART_FILE_NAMES = ("poster.jpg", "poster.png", "cover.jpg", "cover.png", "folder.jpg", "folder.png")

_FILM_NAME_PATTERN = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")
_TRACK_NUMBER_PATTERN = re.compile(r"^\s*(\d+)")
_LEADING_TRACK_NUMBER_PATTERN = re.compile(r"^\d+[\s._-]+")

UNKNOWN_ARTIST = "Unknown artist"


def item_id(kind: str, relative_path: str) -> str:
    """Stable id for a library item, built from its path inside the media folder."""
    return hashlib.sha1(f"{kind}:{relative_path}".encode()).hexdigest()[:16]


def parse_film_name(name: str) -> tuple[str, int | None]:
    match = _FILM_NAME_PATTERN.match(name)
    if match is None:
        return name.strip(), None
    return match.group("title").strip(), int(match.group("year"))


def parse_track_number(raw: str | None) -> int | None:
    if raw is None:
        return None
    match = _TRACK_NUMBER_PATTERN.match(raw)
    return int(match.group(1)) if match else None


def title_from_file_name(path: Path) -> str:
    return _LEADING_TRACK_NUMBER_PATTERN.sub("", path.stem).strip() or path.stem


def find_art(folder: Path) -> Path | None:
    for name in ART_FILE_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _first_video_in(folder: Path) -> Path | None:
    videos = sorted(path for path in folder.iterdir() if path.suffix.lower() in VIDEO_EXTENSIONS)
    return videos[0] if videos else None


def scan_films(media_dir: Path) -> list[Film]:
    films_dir = media_dir / FILMS_FOLDER
    if not films_dir.is_dir():
        return []

    films: list[Film] = []
    for entry in sorted(films_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            video = _first_video_in(entry)
            if video is None:
                continue
            title, year = parse_film_name(entry.name)
            art = find_art(entry)
        elif entry.suffix.lower() in VIDEO_EXTENSIONS:
            video = entry
            title, year = parse_film_name(entry.stem)
            art = None
        else:
            continue
        relative = str(video.relative_to(media_dir))
        films.append(Film(id=item_id("film", relative), title=title, year=year, path=video, art_path=art))

    films.sort(key=lambda film: film.title.lower())
    return films


def _first_tag(tags: mutagen.FileType | None, key: str) -> str | None:
    if tags is None or tags.tags is None:
        return None
    values = tags.tags.get(key)
    return str(values[0]) if values else None


def read_track(path: Path, media_dir: Path) -> Track:
    """Reads tags from an audio file. Falls back to folder names for missing tags."""
    try:
        tags = mutagen.File(path, easy=True)
    except mutagen.MutagenError:
        tags = None

    album_folder = path.parent
    artist_folder = album_folder.parent
    fallback_artist = artist_folder.name if artist_folder != media_dir / MUSIC_FOLDER else UNKNOWN_ARTIST

    return Track(
        id=item_id("track", str(path.relative_to(media_dir))),
        title=_first_tag(tags, "title") or title_from_file_name(path),
        artist=_first_tag(tags, "albumartist") or _first_tag(tags, "artist") or fallback_artist,
        album=_first_tag(tags, "album") or album_folder.name,
        track_number=parse_track_number(_first_tag(tags, "tracknumber")),
        path=path,
    )


def read_album_tags(path: Path) -> tuple[str | None, str | None]:
    """Returns (artist, album) from an audio file's tags, used to file uploads."""
    try:
        tags = mutagen.File(path, easy=True)
    except mutagen.MutagenError:
        return None, None
    artist = _first_tag(tags, "albumartist") or _first_tag(tags, "artist")
    return artist, _first_tag(tags, "album")


def _track_sort_key(track: Track) -> tuple[int, str]:
    # Tracks without a number go after the numbered ones.
    return (track.track_number if track.track_number is not None else 10_000, track.path.name.lower())


def group_tracks_into_albums(tracks: Iterable[Track], media_dir: Path) -> list[Album]:
    """Groups tracks by the folder they are in. One folder is one album."""
    tracks_by_folder: dict[Path, list[Track]] = {}
    for track in tracks:
        tracks_by_folder.setdefault(track.path.parent, []).append(track)

    albums: list[Album] = []
    for folder, folder_tracks in tracks_by_folder.items():
        ordered_tracks = sorted(folder_tracks, key=_track_sort_key)
        first_track = ordered_tracks[0]
        albums.append(
            Album(
                id=item_id("album", str(folder.relative_to(media_dir))),
                title=first_track.album,
                artist=first_track.artist,
                art_path=find_art(folder),
                tracks=ordered_tracks,
            )
        )

    albums.sort(key=lambda album: (album.artist.lower(), album.title.lower()))
    return albums


def scan_music(media_dir: Path) -> list[Album]:
    music_dir = media_dir / MUSIC_FOLDER
    if not music_dir.is_dir():
        return []

    tracks: list[Track] = []
    for path in sorted(music_dir.rglob("*")):
        if path.suffix.lower() in AUDIO_EXTENSIONS and not path.name.startswith("."):
            tracks.append(read_track(path, media_dir))
    return group_tracks_into_albums(tracks, media_dir)


def scan_library(media_dir: Path) -> Library:
    return Library(films=scan_films(media_dir), albums=scan_music(media_dir))


class LibraryIndex:
    """Holds the last scan of the media folder. Rescan after the files change."""

    def __init__(self, media_dir: Path) -> None:
        self._media_dir = media_dir
        self._lock = threading.Lock()
        self._library = Library(films=[], albums=[])

    @property
    def media_dir(self) -> Path:
        return self._media_dir

    @property
    def library(self) -> Library:
        return self._library

    def rescan(self) -> Library:
        with self._lock:
            self._library = scan_library(self._media_dir)
            return self._library
