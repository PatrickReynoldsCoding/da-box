import hashlib
import re
import threading
from collections.abc import Iterable
from pathlib import Path

import mutagen

from dabox.models import Album, Episode, Film, Game, Library, MediaSource, Show, Track
from dabox.systems import SYSTEMS
from dabox.nfo import find_movie_nfo
from dabox.usb import UsbStick

FILMS_FOLDER = "Films"
MUSIC_FOLDER = "Music"
TV_FOLDER = "TV"
GAMES_FOLDER = "Games"

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"})
ART_FILE_NAMES = ("poster.jpg", "poster.png", "cover.jpg", "cover.png", "folder.jpg", "folder.png")

_FILM_NAME_PATTERN = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")
_TRACK_NUMBER_PATTERN = re.compile(r"^\s*(\d+)")
_LEADING_TRACK_NUMBER_PATTERN = re.compile(r"^\d+[\s._-]+")
_EPISODE_PATTERN = re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})")
_SEASON_FOLDER_PATTERN = re.compile(r"(?i)^season\s*(?P<season>\d+)$")
_GAME_TAGS_PATTERN = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_GAME_ART_EXTENSIONS = (".png", ".jpg")
_FINGERPRINT_CHUNK = 64 * 1024

UNKNOWN_ARTIST = "Unknown artist"


def item_id(kind: str, relative_path: str) -> str:
    """Stable id for a library item, built from its path inside the media folder."""
    return hashlib.sha1(f"{kind}:{relative_path}".encode()).hexdigest()[:16]


_fingerprint_cache: dict[tuple[str, int, int], str] = {}
_fingerprint_lock = threading.Lock()


def cached_fingerprint(path: Path) -> str:
    """file_fingerprint, remembered while the file's size and change time stay the same."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _fingerprint_lock:
        known = _fingerprint_cache.get(key)
    if known is None:
        known = file_fingerprint(path)
        with _fingerprint_lock:
            _fingerprint_cache[key] = known
    return known


def file_fingerprint(path: Path) -> str:
    """Identifies a file by its size and its first and last 64 KB, so the same file
    on any USB stick, in any folder, gets the same id."""
    size = path.stat().st_size
    digest = hashlib.sha1(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(_FINGERPRINT_CHUNK))
        if size > _FINGERPRINT_CHUNK:
            handle.seek(max(size - _FINGERPRINT_CHUNK, _FINGERPRINT_CHUNK))
            digest.update(handle.read(_FINGERPRINT_CHUNK))
    return digest.hexdigest()[:16]


class ItemNamer:
    """Gives ids to items. Box items use their path; USB items use file fingerprints."""

    def __init__(self, root: Path, stick: UsbStick | None) -> None:
        self.root = root
        self.stick = stick

    @property
    def source(self) -> MediaSource:
        return MediaSource.USB if self.stick else MediaSource.BOX

    @property
    def stick_label(self) -> str | None:
        return self.stick.label if self.stick else None

    def file_id(self, kind: str, path: Path, fingerprint: str) -> str:
        if self.stick:
            return "u" + item_id(kind, fingerprint)
        return item_id(kind, str(path.relative_to(self.root)))

    def album_id(self, folder: Path, tracks: list[Track]) -> str:
        if self.stick:
            return "u" + item_id("album", ",".join(sorted(track.id for track in tracks)))
        return item_id("album", str(folder.relative_to(self.root)))


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


def find_art(folder: Path, video: Path | None = None, folder_art: bool = True) -> Path | None:
    """Finds poster or cover art. `folder_art=False` skips poster.jpg and the like, for
    a video that shares its folder with other videos."""
    names = list(ART_FILE_NAMES) if folder_art else []
    if video is not None:
        names = [f"{video.stem}-poster.jpg", f"{video.stem}-poster.png", *names]
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _visible_entries(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir() if not path.name.startswith("."))


def _first_video_in(folder: Path) -> Path | None:
    videos = [path for path in _visible_entries(folder) if path.suffix.lower() in VIDEO_EXTENSIONS]
    return videos[0] if videos else None


def _film(namer: ItemNamer, video: Path, folder: Path, name: str, art: Path | None) -> Film:
    title, year = parse_film_name(name)
    nfo = find_movie_nfo(video)
    fingerprint = cached_fingerprint(video)
    return Film(
        id=namer.file_id("film", video, fingerprint),
        fingerprint=fingerprint,
        title=(nfo.title if nfo and nfo.title else title),
        year=(nfo.year if nfo and nfo.year else year),
        plot=nfo.plot if nfo else None,
        path=video,
        folder=folder,
        art_path=art,
        source=namer.source,
        stick_label=namer.stick_label,
    )


def scan_films(namer: ItemNamer) -> list[Film]:
    films_dir = namer.root / FILMS_FOLDER
    if not films_dir.is_dir():
        return []

    films: list[Film] = []
    for entry in _visible_entries(films_dir):
        if entry.is_dir():
            video = _first_video_in(entry)
            if video is not None:
                films.append(_film(namer, video, entry, entry.name, find_art(entry, video)))
        elif entry.suffix.lower() in VIDEO_EXTENSIONS:
            films.append(_film(namer, entry, entry, entry.stem, find_art(films_dir, entry, folder_art=False)))

    films.sort(key=lambda film: film.title.lower())
    return films


def _first_tag(tags: mutagen.FileType | None, key: str) -> str | None:
    if tags is None or tags.tags is None:
        return None
    values = tags.tags.get(key)
    return str(values[0]) if values else None


def read_track(path: Path, namer: ItemNamer) -> Track:
    """Reads tags from an audio file. Falls back to folder names for missing tags."""
    try:
        tags = mutagen.File(path, easy=True)
    except mutagen.MutagenError:
        tags = None

    album_folder = path.parent
    artist_folder = album_folder.parent
    fallback_artist = artist_folder.name if artist_folder != namer.root / MUSIC_FOLDER else UNKNOWN_ARTIST

    fingerprint = cached_fingerprint(path)
    return Track(
        id=namer.file_id("track", path, fingerprint),
        fingerprint=fingerprint,
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


def parse_episode(path: Path) -> tuple[int, int] | None:
    """(season, episode) from a name like "Bluey S01E05.mp4", or from the season folder
    and a leading number ("Season 2/03 The Pool.mp4")."""
    match = _EPISODE_PATTERN.search(path.stem)
    if match:
        return int(match.group("season")), int(match.group("episode"))
    season_match = _SEASON_FOLDER_PATTERN.match(path.parent.name)
    number = parse_track_number(path.stem)
    if season_match and number is not None:
        return int(season_match.group("season")), number
    return None


def episode_title(path: Path, show_title: str) -> str:
    """The part of the file name after SxxEyy, or the whole name."""
    stem = path.stem
    match = _EPISODE_PATTERN.search(stem)
    rest = stem[match.end():] if match else _LEADING_TRACK_NUMBER_PATTERN.sub("", stem)
    rest = rest.strip(" -._")
    return rest or (f"{show_title} {match.group(0).upper()}" if match else stem)


def scan_shows(media_dir: Path) -> list[Show]:
    tv_dir = media_dir / TV_FOLDER
    if not tv_dir.is_dir():
        return []
    namer = ItemNamer(media_dir, None)
    shows: list[Show] = []
    for show_folder in _visible_entries(tv_dir):
        if not show_folder.is_dir():
            continue
        episodes: list[Episode] = []
        for path in sorted(show_folder.rglob("*")):
            numbers = parse_episode(path) if path.suffix.lower() in VIDEO_EXTENSIONS and not path.name.startswith(".") else None
            if numbers is None:
                continue
            fingerprint = cached_fingerprint(path)
            episodes.append(
                Episode(
                    id=namer.file_id("episode", path, fingerprint),
                    title=episode_title(path, show_folder.name),
                    season=numbers[0],
                    number=numbers[1],
                    path=path,
                    fingerprint=fingerprint,
                )
            )
        if episodes:
            episodes.sort(key=lambda episode: (episode.season, episode.number))
            shows.append(
                Show(
                    id=item_id("show", str(show_folder.relative_to(media_dir))),
                    title=show_folder.name,
                    art_path=find_art(show_folder),
                    episodes=episodes,
                )
            )
    return shows


def game_title(stem: str) -> str:
    """'Super Game (USA) (Rev 1) [!]' -> 'Super Game'."""
    return _GAME_TAGS_PATTERN.sub("", stem).replace("_", " ").strip() or stem


def scan_games(namer: ItemNamer) -> list[Game]:
    games_dir = namer.root / GAMES_FOLDER
    if not games_dir.is_dir():
        return []
    games: list[Game] = []
    for system_folder in _visible_entries(games_dir):
        system = SYSTEMS.get(system_folder.name.lower())
        if system is None or not system_folder.is_dir():
            continue
        for path in sorted(system_folder.rglob("*")):
            if path.name.startswith(".") or path.suffix.lower() not in system.extensions:
                continue
            fingerprint = cached_fingerprint(path)
            art = next((path.with_suffix(extension) for extension in _GAME_ART_EXTENSIONS if path.with_suffix(extension).is_file()), None)
            games.append(Game(
                id=namer.file_id("game", path, fingerprint),
                title=game_title(path.stem),
                file_stem=path.stem,
                system=system.key,
                path=path,
                art_path=art,
                fingerprint=fingerprint,
                source=namer.source,
                stick_label=namer.stick_label,
            ))
    return games


def _track_sort_key(track: Track) -> tuple[int, str]:
    # Tracks without a number go after the numbered ones.
    return (track.track_number if track.track_number is not None else 10_000, track.path.name.lower())


def group_tracks_into_albums(tracks: Iterable[Track], namer: ItemNamer) -> list[Album]:
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
                id=namer.album_id(folder, ordered_tracks),
                title=first_track.album,
                artist=first_track.artist,
                art_path=find_art(folder),
                folder=folder,
                tracks=ordered_tracks,
                source=namer.source,
                stick_label=namer.stick_label,
            )
        )

    albums.sort(key=lambda album: (album.artist.lower(), album.title.lower()))
    return albums


def scan_music(namer: ItemNamer) -> list[Album]:
    music_dir = namer.root / MUSIC_FOLDER
    if not music_dir.is_dir():
        return []

    tracks: list[Track] = []
    for path in sorted(music_dir.rglob("*")):
        if path.suffix.lower() in AUDIO_EXTENSIONS and not path.name.startswith("."):
            tracks.append(read_track(path, namer))
    return group_tracks_into_albums(tracks, namer)


def films_not_on_box(usb_films: list[Film], box_films: list[Film]) -> list[Film]:
    """A film copied to the box, or the same film on two sticks, shows only once."""
    seen = {film.fingerprint for film in box_films}
    unique: list[Film] = []
    for film in usb_films:
        if film.fingerprint not in seen:
            seen.add(film.fingerprint)
            unique.append(film)
    return unique


def albums_not_on_box(usb_albums: list[Album], box_albums: list[Album]) -> list[Album]:
    seen: list[set[str]] = [{track.fingerprint for track in album.tracks} for album in box_albums]
    unique: list[Album] = []
    for album in usb_albums:
        fingerprints = {track.fingerprint for track in album.tracks}
        if not any(fingerprints <= known for known in seen):
            seen.append(fingerprints)
            unique.append(album)
    return unique


def games_not_on_box(usb_games: list[Game], box_games: list[Game]) -> list[Game]:
    seen = {game.fingerprint for game in box_games}
    unique: list[Game] = []
    for game in usb_games:
        if game.fingerprint not in seen:
            seen.add(game.fingerprint)
            unique.append(game)
    return unique


def scan_library(media_dir: Path, sticks: list[UsbStick]) -> Library:
    box_namer = ItemNamer(media_dir, None)
    films = scan_films(box_namer)
    albums = scan_music(box_namer)
    games = scan_games(box_namer)
    for stick in sticks:
        stick_namer = ItemNamer(stick.path, stick)
        films += films_not_on_box(scan_films(stick_namer), films)
        albums += albums_not_on_box(scan_music(stick_namer), albums)
        games += games_not_on_box(scan_games(stick_namer), games)
    return Library(
        films=sorted(films, key=lambda film: film.title.lower()),
        albums=sorted(albums, key=lambda album: (album.artist.lower(), album.title.lower())),
        shows=scan_shows(media_dir),
        games=sorted(games, key=lambda game: (game.title.lower(), game.system)),
        sticks=sticks,
    )


class LibraryIndex:
    """Holds the last scan of the media folder and the USB sticks. Rescan after the files change."""

    def __init__(self, media_dir: Path) -> None:
        self._media_dir = media_dir
        self._lock = threading.Lock()
        self._library = Library(films=[], albums=[], shows=[], games=[], sticks=[])

    @property
    def media_dir(self) -> Path:
        return self._media_dir

    @property
    def library(self) -> Library:
        return self._library

    def rescan(self, sticks: list[UsbStick] | None = None) -> Library:
        with self._lock:
            current_sticks = sticks if sticks is not None else self._library.sticks
            self._library = scan_library(self._media_dir, current_sticks)
            return self._library

    def find(self, item_id: str) -> Film | Album | Game | None:
        library = self._library
        for item in [*library.films, *library.albums, *library.games]:
            if item.id == item_id:
                return item
        return None

    def find_show(self, show_id: str) -> Show | None:
        return next((show for show in self._library.shows if show.id == show_id), None)
