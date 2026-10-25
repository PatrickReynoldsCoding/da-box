"""API response shapes, built from the library and metadata. Pure functions only."""

import socket

from pydantic import BaseModel

from dabox.metadata import Metadata, MetadataStatus
from dabox.models import Album, Film, Library, MediaSource, Show


class FilmView(BaseModel):
    id: str
    title: str
    year: int | None
    plot: str | None
    # Length in seconds, if known. The UI uses it to grey out films that cannot finish today.
    seconds: float | None
    art_url: str | None
    path: str
    hidden: bool
    source: MediaSource
    stick_label: str | None
    metadata_status: MetadataStatus | None


class VideoTileView(BaseModel):
    """One tile on the Videos screen: a single video, or a group of videos."""

    kind: str  # "video" or "group"
    id: str
    title: str
    year: int | None
    art_url: str | None
    hidden: bool
    source: MediaSource
    stick_label: str | None
    # A video: its file and length. A group: how many videos it holds.
    path: str | None = None
    seconds: float | None = None
    video_count: int | None = None


class GroupVideoView(BaseModel):
    id: str
    title: str
    path: str
    seconds: float | None
    # "Season 1", or "" for videos in the group's own folder.
    section: str
    # "S5 E3", or None for videos without markers.
    code: str | None


class GroupDetailView(BaseModel):
    id: str
    title: str
    art_url: str | None
    hidden: bool
    source: MediaSource
    stick_label: str | None
    # Where Play starts: the video after the last one that played to its end.
    resume_index: int
    videos: list[GroupVideoView]


class TrackView(BaseModel):
    id: str
    title: str
    artist: str
    path: str


class AlbumView(BaseModel):
    id: str
    title: str
    artist: str
    year: int | None
    art_url: str | None
    track_count: int
    hidden: bool
    source: MediaSource
    stick_label: str | None
    metadata_status: MetadataStatus | None


class AlbumDetailView(AlbumView):
    tracks: list[TrackView]


def _art_url(item: Film | Album | Show, metadata: Metadata | None, art_prefix: str) -> str | None:
    has_art = item.art_path is not None or (metadata is not None and metadata.art_file is not None)
    return f"{art_prefix}/{item.id}" if has_art else None


def film_view(film: Film, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str, seconds: float | None = None) -> FilmView:
    return FilmView(
        id=film.id,
        title=(metadata.title if metadata and metadata.title else film.title),
        year=(metadata.year if metadata and metadata.year else film.year),
        plot=(metadata.plot if metadata and metadata.plot else film.plot),
        seconds=seconds or None,
        art_url=_art_url(film, metadata, art_prefix),
        path=str(film.path),
        hidden=film.id in hidden_ids,
        source=film.source,
        stick_label=film.stick_label,
        metadata_status=metadata.status if metadata else None,
    )


def video_tile(film: Film, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str, seconds: float | None) -> VideoTileView:
    view = film_view(film, hidden_ids, metadata, art_prefix, seconds)
    return VideoTileView(
        kind="video", id=view.id, title=view.title, year=view.year, art_url=view.art_url, hidden=view.hidden,
        source=view.source, stick_label=view.stick_label, path=view.path, seconds=view.seconds,
    )


def group_tile(show: Show, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str) -> VideoTileView:
    return VideoTileView(
        kind="group", id=show.id, title=(metadata.title if metadata and metadata.title else show.title),
        year=metadata.year if metadata else None, art_url=_art_url(show, metadata, art_prefix),
        hidden=show.id in hidden_ids, source=show.source, stick_label=show.stick_label, video_count=len(show.episodes),
    )


def group_detail_view(
    show: Show, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str,
    durations: dict[str, float], resume_index: int,
) -> GroupDetailView:
    tile = group_tile(show, hidden_ids, metadata, art_prefix)
    videos = [
        GroupVideoView(
            id=episode.id, title=episode.title, path=str(episode.path), seconds=durations.get(episode.fingerprint) or None,
            section=episode.section, code=f"S{episode.season} E{episode.number}" if episode.season else None,
        )
        for episode in show.episodes
    ]
    return GroupDetailView(
        id=tile.id, title=tile.title, art_url=tile.art_url, hidden=tile.hidden, source=tile.source,
        stick_label=tile.stick_label, resume_index=resume_index if 0 <= resume_index < len(videos) else 0, videos=videos,
    )


def album_view(album: Album, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str) -> AlbumView:
    return AlbumView(
        id=album.id,
        title=(metadata.title if metadata and metadata.title else album.title),
        artist=(metadata.artist if metadata and metadata.artist else album.artist),
        year=metadata.year if metadata else None,
        art_url=_art_url(album, metadata, art_prefix),
        track_count=len(album.tracks),
        hidden=album.id in hidden_ids,
        source=album.source,
        stick_label=album.stick_label,
        metadata_status=metadata.status if metadata else None,
    )


def album_detail_view(album: Album, hidden_ids: set[str], metadata: Metadata | None, art_prefix: str) -> AlbumDetailView:
    tracks = [TrackView(id=track.id, title=track.title, artist=track.artist, path=str(track.path)) for track in album.tracks]
    return AlbumDetailView(**album_view(album, hidden_ids, metadata, art_prefix).model_dump(), tracks=tracks)


def _is_visible(item: Film | Album | Show, hidden_ids: set[str], show_hidden: bool, usb_allowed: bool) -> bool:
    if show_hidden:
        return True
    return item.id not in hidden_ids and (usb_allowed or item.source is not MediaSource.USB)


def visible_films(library: Library, hidden_ids: set[str], show_hidden: bool, usb_allowed: bool) -> list[Film]:
    return [film for film in library.films if _is_visible(film, hidden_ids, show_hidden, usb_allowed)]


def visible_shows(library: Library, hidden_ids: set[str], show_hidden: bool, usb_allowed: bool) -> list[Show]:
    return [show for show in library.shows if _is_visible(show, hidden_ids, show_hidden, usb_allowed)]


def visible_albums(library: Library, hidden_ids: set[str], show_hidden: bool, usb_allowed: bool) -> list[Album]:
    return [album for album in library.albums if _is_visible(album, hidden_ids, show_hidden, usb_allowed)]


def admin_urls(port: int, ip_address: str | None) -> list[str]:
    """Addresses a phone can use to open the admin app. The .local name needs mDNS (avahi)."""
    port_suffix = "" if port == 80 else f":{port}"
    host_name = socket.gethostname().split(".")[0]
    urls = [f"http://{host_name}.local{port_suffix}"]
    if ip_address:
        urls.append(f"http://{ip_address}{port_suffix}")
    return urls
