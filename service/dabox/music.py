"""Artists, songs, search and shuffle, built from the albums. Pure functions only."""

import random
from typing import Literal

from pydantic import BaseModel

from dabox.models import Album, MediaSource
from dabox.views import AlbumView

SEARCH_LIMIT = 50
# mpv gets every song on its command line, so "Shuffle all" plays a random part of a big library.
SHUFFLE_ALL_LIMIT = 500


class SongView(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    album_id: str
    path: str
    art_url: str | None
    source: MediaSource
    stick_label: str | None
    # The song's album is hidden.
    hidden: bool


class ArtistView(BaseModel):
    name: str
    album_count: int
    art_url: str | None


class SearchHit(BaseModel):
    kind: Literal["artist", "album", "song"]
    title: str
    subtitle: str | None
    art_url: str | None
    # Set for an artist: the name to open.
    artist: str | None = None
    # Set for an album.
    album_id: str | None = None
    # Set for a song.
    song: SongView | None = None


AlbumWithView = tuple[Album, AlbumView]


def songs_of(album: Album, view: AlbumView) -> list[SongView]:
    return [
        SongView(
            id=track.id, title=track.title, artist=track.artist, album=view.title, album_id=album.id, path=str(track.path),
            art_url=view.art_url, source=album.source, stick_label=album.stick_label, hidden=view.hidden,
        )
        for track in album.tracks
    ]


def _song_sort_key(song: SongView) -> tuple[str, str]:
    return song.title.casefold(), song.artist.casefold()


def all_songs(albums: list[AlbumWithView]) -> list[SongView]:
    """Every song, A to Z."""
    return sorted((song for album, view in albums for song in songs_of(album, view)), key=_song_sort_key)


def artists(albums: list[AlbumWithView]) -> list[ArtistView]:
    """One entry for each album artist, A to Z. Names that differ only in case are one artist."""
    by_key: dict[str, list[AlbumView]] = {}
    for _, view in albums:
        by_key.setdefault(view.artist.casefold(), []).append(view)
    found = [
        ArtistView(
            name=views[0].artist, album_count=len(views),
            art_url=next((view.art_url for view in views if view.art_url), None),
        )
        for views in by_key.values()
    ]
    return sorted(found, key=lambda artist: artist.name.casefold())


def search(albums: list[AlbumWithView], text: str) -> list[SearchHit]:
    """Artists, then albums, then songs whose name has the text in it."""
    needle = " ".join(text.split()).casefold()
    if not needle:
        return []
    hits = [
        SearchHit(kind="artist", title=artist.name, subtitle=f"{artist.album_count} album{'s' * (artist.album_count != 1)}",
                  art_url=artist.art_url, artist=artist.name)
        for artist in artists(albums) if needle in artist.name.casefold()
    ][:SEARCH_LIMIT]
    hits += [
        SearchHit(kind="album", title=view.title, subtitle=view.artist, art_url=view.art_url, album_id=view.id)
        for _, view in sorted(albums, key=lambda pair: pair[1].title.casefold()) if needle in view.title.casefold()
    ][:SEARCH_LIMIT]
    hits += [
        SearchHit(kind="song", title=song.title, subtitle=song.artist, art_url=song.art_url, song=song)
        for song in all_songs(albums) if needle in song.title.casefold()
    ][:SEARCH_LIMIT]
    return hits


def shuffled(songs: list[SongView], limit: int | None = None, rng: random.Random | None = None) -> list[SongView]:
    order = list(songs)
    (rng or random).shuffle(order)
    return order[:limit] if limit is not None else order
