"""API response shapes, built from the library. Pure functions only."""

import socket

from pydantic import BaseModel

from dabox.models import Album, Film, Library


class FilmView(BaseModel):
    id: str
    title: str
    year: int | None
    art_url: str | None
    path: str
    hidden: bool


class TrackView(BaseModel):
    id: str
    title: str
    artist: str
    path: str


class AlbumView(BaseModel):
    id: str
    title: str
    artist: str
    art_url: str | None
    track_count: int
    hidden: bool


class AlbumDetailView(AlbumView):
    tracks: list[TrackView]


def film_view(film: Film, hidden_ids: set[str], art_prefix: str) -> FilmView:
    return FilmView(
        id=film.id,
        title=film.title,
        year=film.year,
        art_url=f"{art_prefix}/{film.id}" if film.art_path else None,
        path=str(film.path),
        hidden=film.id in hidden_ids,
    )


def album_view(album: Album, hidden_ids: set[str], art_prefix: str) -> AlbumView:
    return AlbumView(
        id=album.id,
        title=album.title,
        artist=album.artist,
        art_url=f"{art_prefix}/{album.id}" if album.art_path else None,
        track_count=len(album.tracks),
        hidden=album.id in hidden_ids,
    )


def album_detail_view(album: Album, hidden_ids: set[str], art_prefix: str) -> AlbumDetailView:
    tracks = [TrackView(id=track.id, title=track.title, artist=track.artist, path=str(track.path)) for track in album.tracks]
    return AlbumDetailView(**album_view(album, hidden_ids, art_prefix).model_dump(), tracks=tracks)


def visible_films(library: Library, hidden_ids: set[str], show_hidden: bool) -> list[Film]:
    return [film for film in library.films if show_hidden or film.id not in hidden_ids]


def visible_albums(library: Library, hidden_ids: set[str], show_hidden: bool) -> list[Album]:
    return [album for album in library.albums if show_hidden or album.id not in hidden_ids]


def admin_urls(port: int, ip_address: str | None) -> list[str]:
    """Addresses a phone can use to open the admin app. The .local name needs mDNS (avahi)."""
    port_suffix = "" if port == 80 else f":{port}"
    host_name = socket.gethostname().split(".")[0]
    urls = [f"http://{host_name}.local{port_suffix}"]
    if ip_address:
        urls.append(f"http://{ip_address}{port_suffix}")
    return urls
