"""Finds videos, music and games on the box and on USB drives, in any folder layout.

DESIGN_CORRECTIONS_2.md, parts 1 and 2: every folder is read (system and junk folders are
skipped); a folder with one video is a video, a folder with several videos is a group, and
songs group into albums by their tags, like iTunes. The box's own Films/, TV/, Music/ and
Games/ folders follow the same rules, and their items keep the ids they had.
"""

import hashlib
import os
import re
import threading
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import mutagen

from dabox.models import Album, Episode, Film, Game, Library, MediaSource, ScanReport, Show, Track
from dabox.names import (
    clean_name,
    episode_marker,
    episode_marker_span,
    natural_key,
    split_artist_title,
    split_year,
    strip_track_number,
    without_common_start,
)
from dabox.nfo import find_movie_nfo
from dabox.systems import SYSTEMS, GameSystem
from dabox.usb import UsbStick

FILMS_FOLDER = "Films"
MUSIC_FOLDER = "Music"
TV_FOLDER = "TV"
GAMES_FOLDER = "Games"
# Where Copy from USB puts videos and groups (DESIGN_CORRECTIONS_2.md, part 3).
VIDEOS_FOLDER = "Videos"

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".mpg", ".mpeg", ".wmv", ".flv"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma"})
ART_FILE_NAMES = ("poster.jpg", "poster.png", "cover.jpg", "cover.png", "folder.jpg", "folder.png")
# Files that belong to the media next to them: art, details and subtitles.
_COMPANION_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".cue", ".m3u", ".m3u8"})

# Never read: Windows, macOS and Linux system folders, and NAS thumbnails.
_SKIPPED_FOLDERS = frozenset({
    "$recycle.bin", "recycler", "system volume information", ".trashes", ".spotlight-v100", ".fseventsd",
    ".temporaryitems", "lost+found", "@eadir", "#recycle", ".thumbnails",
})
# Folders that hold videos but are never one video or one group themselves.
_GENERIC_FOLDERS = frozenset({
    "video", "videos", "movie", "movies", "film", "films", "tv", "tv shows", "shows", "series", "media",
    "temp", "tmp", "downloads", "download", "new folder", "my videos", "kids",
})
# Sub-folders that make their parent a group: "Season 1", "S02", "Disc 1", "Specials".
_SECTION_FOLDER = re.compile(
    r"(?i)^(?:(?:season|series|staffel|saison|disc|disk|cd|part|volume|vol|book|s)\s*[-_.]?\s*\d+\b.*"
    r"|specials?|extras?|bonus(?: features)?|featurettes?|behind the scenes)$"
)
_GAME_TAGS_PATTERN = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_GAME_ART_EXTENSIONS = (".png", ".jpg")
_FINGERPRINT_CHUNK = 64 * 1024
# The report keeps only the first few unreadable files.
_REPORT_LIMIT = 10

UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"

# Folder names that say which system a game is for, when its extension does not (.zip, .bin).
_SYSTEM_FOLDER_NAMES: dict[str, str] = {
    **{key: key for key in SYSTEMS},
    "famicom": "nes", "nintendo": "nes", "super nintendo": "snes", "super famicom": "snes", "sfc": "snes",
    "game boy": "gb", "gameboy": "gb", "game boy color": "gbc", "gameboy color": "gbc",
    "game boy advance": "gba", "gameboy advance": "gba", "mega drive": "megadrive", "genesis": "megadrive",
    "sega genesis": "megadrive", "sega mega drive": "megadrive", "md": "megadrive",
    "playstation": "psx", "ps1": "psx", "playstation 1": "psx",
}
_SHARED_GAME_EXTENSIONS = frozenset({".zip", ".bin"})


def _systems_by_extension() -> dict[str, list[GameSystem]]:
    found: dict[str, list[GameSystem]] = {}
    for system in SYSTEMS.values():
        for extension in system.extensions - _SHARED_GAME_EXTENSIONS:
            found.setdefault(extension, []).append(system)
    return found


_SYSTEMS_BY_EXTENSION = _systems_by_extension()
_GAME_EXTENSIONS = frozenset(_SYSTEMS_BY_EXTENSION) | _SHARED_GAME_EXTENSIONS


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

    def tag_album_id(self, artist: str, album: str, tracks: list[Track]) -> str:
        """An album whose songs are in more than one folder."""
        if self.stick:
            return self.album_id(self.root, tracks)
        return item_id("album", f"tags:{artist.casefold()}/{album.casefold()}")

    def group_id(self, folder: Path, episodes: list[Episode]) -> str:
        if self.stick:
            return "u" + item_id("show", ",".join(sorted(episode.fingerprint for episode in episodes)))
        return item_id("show", str(folder.relative_to(self.root)))


def parse_film_name(name: str) -> tuple[str, int | None]:
    return split_year(clean_name(name))


def parse_track_number(raw: str | None) -> int | None:
    if raw is None:
        return None
    match = re.match(r"^\s*(\d+)", raw)
    return int(match.group(1)) if match else None


def title_from_file_name(path: Path) -> str:
    return strip_track_number(path.stem)[0] or path.stem


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
    marker = episode_marker(path.stem)
    if marker:
        return marker
    season_match = re.match(r"(?i)^season\s*(\d+)$", path.parent.name)
    number = parse_track_number(path.stem)
    if season_match and number is not None:
        return int(season_match.group(1)), number
    return None


def episode_title(path: Path, show_title: str) -> str:
    """The part of the file name after SxxEyy, or the whole name."""
    stem = path.stem
    span = episode_marker_span(stem)
    rest = stem[span[1]:] if span else strip_track_number(stem)[0]
    rest = clean_name(rest.strip(" -._")) if rest.strip(" -._") else ""
    if rest:
        return rest
    return f"{show_title} {stem[span[0]:span[1]].upper()}" if span else stem


def game_title(stem: str) -> str:
    """'Super Game (USA) (Rev 1) [!]' -> 'Super Game'."""
    return _GAME_TAGS_PATTERN.sub("", stem).replace("_", " ").strip() or stem


def _first_tag(tags: mutagen.FileType | None, key: str) -> str | None:
    if tags is None or tags.tags is None:
        return None
    values = tags.tags.get(key)
    return str(values[0]).strip() or None if values else None


# ---- Walking a drive ----

@dataclass
class _Folder:
    path: Path
    videos: list[Path] = field(default_factory=list)
    children: list["_Folder"] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    def has_video(self) -> bool:
        return bool(self.videos) or any(child.has_video() for child in self.children)

    def all_videos(self) -> list[Path]:
        return [*self.videos, *(video for child in self.children for video in child.all_videos())]


@dataclass
class _Walk:
    tree: _Folder
    audio: list[Path]
    games: list[Path]
    report: ScanReport


def _walk(root: Path) -> _Walk:
    """Every folder under the root, without system, junk and hidden folders."""
    report = ScanReport()
    audio: list[Path] = []
    games: list[Path] = []
    folders: dict[Path, _Folder] = {root: _Folder(root)}
    # Art and details count as other files only if no media is in their folder or below it.
    companions: dict[Path, dict[str, int]] = {}
    media_folders: set[Path] = set()
    for current, dir_names, file_names in os.walk(root, onerror=lambda error: _note_unreadable(report, error)):
        here = Path(current)
        node = folders[here]
        kept = []
        for name in sorted(dir_names, key=natural_key):
            if name.startswith(".") or name.casefold() in _SKIPPED_FOLDERS:
                report.skipped_folders += 1
                continue
            kept.append(name)
            child = _Folder(here / name)
            folders[child.path] = child
            node.children.append(child)
        dir_names[:] = kept
        other: dict[str, int] = {}
        has_media = False
        for name in sorted(file_names, key=natural_key):
            if name.startswith("."):
                continue
            path = here / name
            extension = path.suffix.lower()
            if extension in VIDEO_EXTENSIONS:
                node.videos.append(path)
                has_media = True
            elif extension in AUDIO_EXTENSIONS:
                audio.append(path)
                has_media = True
            elif extension in _GAME_EXTENSIONS:
                games.append(path)
                has_media = True
            else:
                other[extension or "(no extension)"] = other.get(extension or "(no extension)", 0) + 1
        if has_media:
            media_folders.add(here)
        for extension, count in other.items():
            if extension in _COMPANION_EXTENSIONS:
                companions.setdefault(here, {})[extension] = count
            else:
                report.other_files[extension] = report.other_files.get(extension, 0) + count
    media_above = {parent for folder in media_folders for parent in (folder, *folder.parents)}
    for folder, counts in companions.items():
        if folder not in media_above:
            for extension, count in counts.items():
                report.other_files[extension] = report.other_files.get(extension, 0) + count
    return _Walk(folders[root], audio, games, report)


def _note_unreadable(report: ScanReport, error: OSError) -> None:
    if len(report.unreadable) < _REPORT_LIMIT:
        report.unreadable.append(f"{error.filename}: {error.strerror or error}")


def _note_file_error(report: ScanReport, path: Path, error: Exception) -> None:
    if len(report.unreadable) < _REPORT_LIMIT:
        report.unreadable.append(f"{path}: {getattr(error, 'strerror', None) or error}")


# ---- Videos and groups ----

def _folder_kind(folder: _Folder, in_tv_folder: bool) -> str:
    """"group", "single" (a folder with one video, named after the folder) or "container"."""
    if in_tv_folder:
        # Every folder in the box's TV/ is a group, as it was a show before (its id stays).
        return "group"
    if folder.name.casefold() in _GENERIC_FOLDERS:
        return "container"
    video_children = [child for child in folder.children if child.has_video()]
    if video_children and not all(_SECTION_FOLDER.match(child.name) for child in video_children):
        return "container"
    return "single" if len(folder.all_videos()) == 1 else "group"


def _find_videos(namer: ItemNamer, walk: _Walk) -> tuple[list[Film], list[Show]]:
    films: list[Film] = []
    shows: list[Show] = []

    def visit(folder: _Folder, depth: int, in_tv_folder: bool) -> None:
        kind = _folder_kind(folder, in_tv_folder) if depth > 0 else "container"
        if kind == "single":
            film = _single_video(namer, walk.report, folder.all_videos()[0], own_folder=folder.path)
            if film is not None:
                films.append(film)
            return
        if kind == "group":
            group = _group(namer, walk.report, folder.path, folder.all_videos())
            if group is not None:
                shows.append(group)
            return
        for video in folder.videos:
            film = _single_video(namer, walk.report, video, own_folder=None)
            if film is not None:
                films.append(film)
        children_in_tv = namer.stick is None and depth == 1 and folder.name == TV_FOLDER
        for child in folder.children:
            if child.has_video():
                visit(child, depth + 1, children_in_tv)

    visit(walk.tree, 0, False)
    return films, shows


def _single_video(namer: ItemNamer, report: ScanReport, video: Path, own_folder: Path | None) -> Film | None:
    """A video in its own folder is named after the folder; a loose video after its file."""
    named_by_folder = own_folder is not None and own_folder.name.casefold() not in _GENERIC_FOLDERS
    title, year = parse_film_name(own_folder.name if named_by_folder else video.stem)
    try:
        fingerprint = cached_fingerprint(video)
    except OSError as error:
        _note_file_error(report, video, error)
        return None
    nfo = find_movie_nfo(video)
    art = find_art(own_folder, video) if own_folder is not None else find_art(video.parent, video, folder_art=False)
    return Film(
        id=namer.file_id("film", video, fingerprint),
        fingerprint=fingerprint,
        title=(nfo.title if nfo and nfo.title else title),
        year=(nfo.year if nfo and nfo.year else year),
        plot=nfo.plot if nfo else None,
        path=video,
        folder=own_folder if own_folder is not None else video,
        art_path=art,
        source=namer.source,
        stick_label=namer.stick_label,
    )


def _group(namer: ItemNamer, report: ScanReport, folder: Path, videos: list[Path]) -> Show | None:
    """A folder of videos, in order: by S01E02 markers if every video has one, else by name."""
    fingerprints: dict[Path, str] = {}
    for video in videos:
        try:
            fingerprints[video] = cached_fingerprint(video)
        except OSError as error:
            _note_file_error(report, video, error)
    videos = [video for video in videos if video in fingerprints]
    if not videos:
        return None
    markers = {video: parse_episode(video) for video in videos}
    with_markers = all(markers.values())
    if with_markers:
        videos.sort(key=lambda video: (*markers[video], natural_key(str(video.relative_to(folder)))))
    else:
        videos.sort(key=lambda video: natural_key(str(video.relative_to(folder))))
    group_title = clean_name(folder.name)
    if with_markers:
        titles = [episode_title(video, group_title) for video in videos]
    else:
        titles = without_common_start([clean_name(video.stem) for video in videos])
    episodes = []
    for position, (video, title) in enumerate(zip(videos, titles), start=1):
        season, number = markers[video] if with_markers else (0, position)
        section = str(video.parent.relative_to(folder)) if video.parent != folder else ""
        episodes.append(Episode(
            id=namer.file_id("episode", video, fingerprints[video]), title=title, season=season, number=number,
            path=video, fingerprint=fingerprints[video], section=section,
        ))
    return Show(
        id=namer.group_id(folder, episodes), title=group_title, folder=folder, art_path=find_art(folder),
        episodes=episodes, source=namer.source, stick_label=namer.stick_label,
    )


# ---- Music ----

def _in_artist_album_layout(path: Path) -> bool:
    """Music/<Artist>/<Album>/<song>: the box's own layout, where folder names are reliable."""
    parents = path.parents
    return len(parents) >= 3 and parents[2].name.casefold() == MUSIC_FOLDER.casefold()


def read_track(path: Path, namer: ItemNamer) -> Track:
    """Tags first. Without tags, like iTunes: the artist from "Artist - Title" in the file name,
    else Unknown Artist; the album Unknown Album. Music/<Artist>/<Album>/ folders also count."""
    try:
        tags = mutagen.File(path, easy=True)
    except mutagen.MutagenError:
        tags = None
    name_artist, name_title = split_artist_title(path.stem)
    _, name_track = strip_track_number(path.stem)
    layout = _in_artist_album_layout(path)
    fingerprint = cached_fingerprint(path)
    return Track(
        id=namer.file_id("track", path, fingerprint),
        fingerprint=fingerprint,
        title=_first_tag(tags, "title") or name_title or path.stem,
        artist=(_first_tag(tags, "albumartist") or _first_tag(tags, "artist")
                or (path.parent.parent.name if layout else None) or name_artist or UNKNOWN_ARTIST),
        album=_first_tag(tags, "album") or (path.parent.name if layout else None) or UNKNOWN_ALBUM,
        track_number=parse_track_number(_first_tag(tags, "tracknumber")) or name_track,
        path=path,
    )


def _track_sort_key(track: Track) -> tuple[int, list[int | str]]:
    # Tracks without a number go after the numbered ones.
    return (track.track_number if track.track_number is not None else 10_000, natural_key(track.path.name))


def group_tracks_into_albums(tracks: Iterable[Track], namer: ItemNamer) -> list[Album]:
    """Songs with the same artist and album are one album, wherever they are on the drive."""
    by_album: dict[tuple[str, str], list[Track]] = {}
    for track in tracks:
        by_album.setdefault((track.artist.casefold(), track.album.casefold()), []).append(track)

    albums: list[Album] = []
    for album_tracks in by_album.values():
        ordered_tracks = sorted(album_tracks, key=_track_sort_key)
        first_track = ordered_tracks[0]
        folders = {track.path.parent for track in ordered_tracks}
        if len(folders) == 1:
            folder = folders.pop()
            album_id, art = namer.album_id(folder, ordered_tracks), find_art(folder)
        else:
            folder = Path(os.path.commonpath([str(track.path.parent) for track in ordered_tracks]))
            album_id, art = namer.tag_album_id(first_track.artist, first_track.album, ordered_tracks), None
        albums.append(Album(
            id=album_id, title=first_track.album, artist=first_track.artist, art_path=art, folder=folder,
            tracks=ordered_tracks, source=namer.source, stick_label=namer.stick_label,
        ))
    albums.sort(key=lambda album: (album.artist.lower(), album.title.lower()))
    return albums


def _find_music(namer: ItemNamer, walk: _Walk) -> list[Album]:
    tracks: list[Track] = []
    for path in walk.audio:
        try:
            tracks.append(read_track(path, namer))
        except OSError as error:
            _note_file_error(walk.report, path, error)
    return group_tracks_into_albums(tracks, namer)


# ---- Games ----

def _system_from_folders(path: Path, root: Path) -> GameSystem | None:
    for folder in path.relative_to(root).parents:
        key = _SYSTEM_FOLDER_NAMES.get(folder.name.casefold())
        if key is not None:
            return SYSTEMS[key]
    return None


def _cue_is_a_game(path: Path) -> bool:
    """A .cue sheet for a PlayStation disc points at .bin files; one for a music CD at audio."""
    try:
        text = path.read_text(errors="replace")[:4096].lower()
    except OSError:
        return False
    return ".bin" in text and not any(f"{extension}\"" in text for extension in AUDIO_EXTENSIONS)


def _zip_game_extension(path: Path) -> str | None:
    """The extension of the one game file inside a zip, if that is all it holds."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return None
    extensions = {Path(name).suffix.lower() for name in names}
    if len(names) == 1 and extensions <= set(_SYSTEMS_BY_EXTENSION):
        return extensions.pop()
    return None


def game_system(path: Path, root: Path) -> GameSystem | None:
    """The system a file is a game for, from its extension, or from folder names for .zip and .bin."""
    extension = path.suffix.lower()
    from_folders = _system_from_folders(path, root)
    if extension == ".zip":
        inner = _zip_game_extension(path)
        if inner is not None:
            candidates = _SYSTEMS_BY_EXTENSION[inner]
            return candidates[0] if len(candidates) == 1 else from_folders
        return from_folders if from_folders and ".zip" in from_folders.extensions else None
    if extension == ".bin":
        # A disc's .bin goes with its .cue (the .cue is the game); a lone .bin is a Mega Drive game.
        if path.with_suffix(".cue").exists():
            return None
        return from_folders if from_folders and ".bin" in from_folders.extensions else None
    if extension == ".cue" and not _cue_is_a_game(path):
        return None
    candidates = _SYSTEMS_BY_EXTENSION.get(extension, [])
    if len(candidates) == 1:
        return candidates[0]
    return from_folders if from_folders in candidates else None


def _find_games(namer: ItemNamer, walk: _Walk) -> list[Game]:
    games: list[Game] = []
    for path in walk.games:
        if path.suffix.lower() == ".bin" and path.with_suffix(".cue").exists():
            continue  # A disc's data: its .cue is the game.
        system = game_system(path, namer.root)
        if system is None:
            extension = path.suffix.lower()
            walk.report.other_files[extension] = walk.report.other_files.get(extension, 0) + 1
            continue
        try:
            fingerprint = cached_fingerprint(path)
        except OSError as error:
            _note_file_error(walk.report, path, error)
            continue
        art = next((path.with_suffix(extension) for extension in _GAME_ART_EXTENSIONS if path.with_suffix(extension).is_file()), None)
        games.append(Game(
            id=namer.file_id("game", path, fingerprint), title=game_title(path.stem), file_stem=path.stem,
            system=system.key, path=path, art_path=art, fingerprint=fingerprint, source=namer.source,
            stick_label=namer.stick_label,
        ))
    return games


# ---- Whole drives ----

@dataclass
class RootScan:
    films: list[Film]
    shows: list[Show]
    albums: list[Album]
    games: list[Game]
    report: ScanReport


def scan_root(root: Path, stick: UsbStick | None = None) -> RootScan:
    """Everything on one drive (a stick), or in the box's media folder (no stick)."""
    namer = ItemNamer(root, stick)
    if not root.is_dir():
        return RootScan([], [], [], [], ScanReport())
    walk = _walk(root)
    films, shows = _find_videos(namer, walk)
    albums = _find_music(namer, walk)
    games = _find_games(namer, walk)
    report = walk.report
    report.videos, report.groups, report.albums, report.games = len(films), len(shows), len(albums), len(games)
    report.songs = sum(len(album.tracks) for album in albums)
    return RootScan(
        films=sorted(films, key=lambda film: natural_key(film.title)),
        shows=sorted(shows, key=lambda show: natural_key(show.title)),
        albums=albums,
        games=sorted(games, key=lambda game: (game.title.lower(), game.system)),
        report=report,
    )


def films_not_on_box(usb_films: list[Film], box_films: list[Film]) -> list[Film]:
    """A film copied to the box, or the same film on two sticks, shows only once."""
    seen = {film.fingerprint for film in box_films}
    unique: list[Film] = []
    for film in usb_films:
        if film.fingerprint not in seen:
            seen.add(film.fingerprint)
            unique.append(film)
    return unique


def shows_not_on_box(usb_shows: list[Show], box_shows: list[Show]) -> list[Show]:
    """A group whose every video is in a known group shows only once."""
    seen = [{episode.fingerprint for episode in show.episodes} for show in box_shows]
    unique: list[Show] = []
    for show in usb_shows:
        fingerprints = {episode.fingerprint for episode in show.episodes}
        if not any(fingerprints <= known for known in seen):
            seen.append(fingerprints)
            unique.append(show)
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
    box = scan_root(media_dir)
    films, shows, albums, games = box.films, box.shows, box.albums, box.games
    reports = {}
    for stick in sticks:
        found = scan_root(stick.path, stick)
        reports[stick.id] = found.report
        films += films_not_on_box(found.films, films)
        shows += shows_not_on_box(found.shows, shows)
        albums += albums_not_on_box(found.albums, albums)
        games += games_not_on_box(found.games, games)
    return Library(
        films=sorted(films, key=lambda film: natural_key(film.title)),
        albums=sorted(albums, key=lambda album: (album.artist.lower(), album.title.lower())),
        shows=sorted(shows, key=lambda show: natural_key(show.title)),
        games=sorted(games, key=lambda game: (game.title.lower(), game.system)),
        sticks=sticks,
        reports=reports,
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

    def find(self, item_id: str) -> Film | Show | Album | Game | None:
        library = self._library
        for item in [*library.films, *library.shows, *library.albums, *library.games]:
            if item.id == item_id:
                return item
        return None

    def find_show(self, show_id: str) -> Show | None:
        return next((show for show in self._library.shows if show.id == show_id), None)
