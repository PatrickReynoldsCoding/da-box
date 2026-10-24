"""Playlists: named lists of songs on the box, in an order. Made by the parent or on the box."""

import secrets
import threading
from enum import StrEnum

from pydantic import BaseModel

from dabox.store import Store

NAME_MAX_LENGTH = 30
_PLAYLISTS_KEY = "playlists"


class MadeOn(StrEnum):
    BOX = "box"
    ADMIN = "admin"


class Playlist(BaseModel):
    id: str
    name: str
    made_on: MadeOn
    song_ids: list[str]


class PlaylistNotFound(Exception):
    pass


class PlaylistRejected(Exception):
    pass


def can_change(playlist: Playlist, parent: bool) -> bool:
    """A kid changes only the playlists made on the box. The parent changes all of them."""
    return parent or playlist.made_on is MadeOn.BOX


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise PlaylistRejected("Give the playlist a name")
    if len(cleaned) > NAME_MAX_LENGTH:
        raise PlaylistRejected(f"A playlist name can have up to {NAME_MAX_LENGTH} letters")
    return cleaned


class Playlists:
    """Saved in the box store. Every change takes `known_song_ids` (the songs on the box now),
    and drops songs that are gone, so a deleted song leaves its playlists."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.Lock()

    def all(self) -> list[Playlist]:
        raw = self._store.get(_PLAYLISTS_KEY) or []
        playlists = [Playlist.model_validate(entry) for entry in raw]
        return sorted(playlists, key=lambda playlist: playlist.name.lower())

    def get(self, playlist_id: str) -> Playlist:
        for playlist in self.all():
            if playlist.id == playlist_id:
                return playlist
        raise PlaylistNotFound(playlist_id)

    def _save(self, playlists: list[Playlist]) -> None:
        self._store.put(_PLAYLISTS_KEY, [playlist.model_dump(mode="json") for playlist in playlists])

    def create(self, name: str, made_on: MadeOn) -> Playlist:
        playlist = Playlist(id=secrets.token_hex(6), name=clean_name(name), made_on=made_on, song_ids=[])
        with self._lock:
            self._save([*self.all(), playlist])
        return playlist

    def delete(self, playlist_id: str) -> None:
        with self._lock:
            playlists = self.all()
            if not any(playlist.id == playlist_id for playlist in playlists):
                raise PlaylistNotFound(playlist_id)
            self._save([playlist for playlist in playlists if playlist.id != playlist_id])

    def _change(self, playlist_id: str, known_song_ids: set[str], change) -> Playlist:
        with self._lock:
            playlists = self.all()
            for index, playlist in enumerate(playlists):
                if playlist.id == playlist_id:
                    changed = change(playlist.model_copy(update={"song_ids": [s for s in playlist.song_ids if s in known_song_ids]}))
                    playlists[index] = changed
                    self._save(playlists)
                    return changed
        raise PlaylistNotFound(playlist_id)

    def rename(self, playlist_id: str, name: str, known_song_ids: set[str]) -> Playlist:
        cleaned = clean_name(name)
        return self._change(playlist_id, known_song_ids, lambda playlist: playlist.model_copy(update={"name": cleaned}))

    def add_song(self, playlist_id: str, song_id: str, known_song_ids: set[str]) -> Playlist:
        if song_id not in known_song_ids:
            raise PlaylistRejected("Only songs on the box can go on a playlist. Copy the album to the box first.")

        def add(playlist: Playlist) -> Playlist:
            if song_id in playlist.song_ids:
                return playlist
            return playlist.model_copy(update={"song_ids": [*playlist.song_ids, song_id]})

        return self._change(playlist_id, known_song_ids, add)

    def remove_song(self, playlist_id: str, song_id: str, known_song_ids: set[str]) -> Playlist:
        return self._change(
            playlist_id, known_song_ids,
            lambda playlist: playlist.model_copy(update={"song_ids": [s for s in playlist.song_ids if s != song_id]}),
        )

    def set_songs(self, playlist_id: str, song_ids: list[str], known_song_ids: set[str]) -> Playlist:
        """Sets the order (and removes songs). The same song can be on a playlist only once."""
        unknown = [song_id for song_id in song_ids if song_id not in known_song_ids]
        if unknown:
            raise PlaylistRejected("Only songs on the box can go on a playlist")
        ordered = list(dict.fromkeys(song_ids))
        return self._change(playlist_id, known_song_ids, lambda playlist: playlist.model_copy(update={"song_ids": ordered}))
