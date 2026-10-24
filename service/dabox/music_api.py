"""Music routes: artists, songs, search and shuffle for the box UI, and playlists for the box and the admin app."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dabox.box_api import Listing
from dabox.models import MediaSource
from dabox.music import SHUFFLE_ALL_LIMIT, AlbumWithView, ArtistView, SearchHit, SongView, all_songs, artists, search, shuffled, songs_of
from dabox.playlists import MadeOn, Playlist, PlaylistNotFound, PlaylistRejected, can_change
from dabox.services import Services, get_services, require_admin, require_box_client
from dabox.views import album_view, visible_albums

BOX_ART_PREFIX = "/box/art"
ADMIN_ART_PREFIX = "/api/admin/art"

box_router = APIRouter(prefix="/box/music", dependencies=[Depends(require_box_client)])
admin_router = APIRouter(prefix="/api/admin/music", dependencies=[Depends(require_admin)])


class PlaylistView(BaseModel):
    id: str
    name: str
    made_on: MadeOn
    can_change: bool
    song_count: int
    art_url: str | None


class PlaylistDetailView(PlaylistView):
    songs: list[SongView]


class NameRequest(BaseModel):
    name: str


class SongRequest(BaseModel):
    song_id: str


class SongOrderRequest(BaseModel):
    song_ids: list[str]


def _visible_albums(services: Services) -> list[AlbumWithView]:
    """What the kid side may see (everything in parent mode)."""
    listing = Listing(services)
    visible = visible_albums(services.library.library, listing.hidden_ids, listing.show_hidden, listing.usb_allowed)
    return [(album, album_view(album, listing.hidden_ids, listing.metadata.get(album.id), BOX_ART_PREFIX)) for album in visible]


def _box_songs(services: Services, art_prefix: str) -> dict[str, SongView]:
    """Every song on the box, hidden ones too. Only these can go on a playlist."""
    hidden_ids = services.store.hidden_item_ids()
    metadata = services.metadata.store.all()
    songs: dict[str, SongView] = {}
    for album in services.library.library.albums:
        if album.source is MediaSource.BOX:
            for song in songs_of(album, album_view(album, hidden_ids, metadata.get(album.id), art_prefix)):
                songs[song.id] = song
    return songs


class _PlaylistAccess:
    """Playlists as one caller sees them: a kid on the box, the box in parent mode, or the admin app."""

    def __init__(self, services: Services, parent: bool, show_hidden: bool, art_prefix: str) -> None:
        self.services = services
        self.parent = parent
        self.show_hidden = show_hidden
        self.box_songs = _box_songs(services, art_prefix)

    @property
    def known_ids(self) -> set[str]:
        return set(self.box_songs)

    def _songs(self, playlist: Playlist) -> list[SongView]:
        songs = [self.box_songs[song_id] for song_id in playlist.song_ids if song_id in self.box_songs]
        return songs if self.show_hidden else [song for song in songs if not song.hidden]

    def view(self, playlist: Playlist) -> PlaylistView:
        songs = self._songs(playlist)
        return PlaylistView(
            id=playlist.id, name=playlist.name, made_on=playlist.made_on, can_change=can_change(playlist, self.parent),
            song_count=len(songs), art_url=next((song.art_url for song in songs if song.art_url), None),
        )

    def detail(self, playlist: Playlist) -> PlaylistDetailView:
        return PlaylistDetailView(**self.view(playlist).model_dump(), songs=self._songs(playlist))

    def get(self, playlist_id: str) -> Playlist:
        try:
            return self.services.playlists.get(playlist_id)
        except PlaylistNotFound as error:
            raise HTTPException(status_code=404, detail="No such playlist") from error

    def changeable(self, playlist_id: str) -> Playlist:
        playlist = self.get(playlist_id)
        if not can_change(playlist, self.parent):
            raise HTTPException(status_code=403, detail="Only a grown-up can change this playlist")
        return playlist


def _box_access(services: Services) -> _PlaylistAccess:
    parent = services.box_state.parent_mode
    return _PlaylistAccess(services, parent=parent, show_hidden=parent, art_prefix=BOX_ART_PREFIX)


def _admin_access(services: Services) -> _PlaylistAccess:
    return _PlaylistAccess(services, parent=True, show_hidden=True, art_prefix=ADMIN_ART_PREFIX)


def _rejected(error: PlaylistRejected) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


# ---- Shared playlist actions ----

def _list(access: _PlaylistAccess) -> list[PlaylistView]:
    return [access.view(playlist) for playlist in access.services.playlists.all()]


def _create(access: _PlaylistAccess, name: str, made_on: MadeOn) -> PlaylistDetailView:
    try:
        return access.detail(access.services.playlists.create(name, made_on))
    except PlaylistRejected as error:
        raise _rejected(error) from error


def _rename(access: _PlaylistAccess, playlist_id: str, name: str) -> PlaylistDetailView:
    access.changeable(playlist_id)
    try:
        return access.detail(access.services.playlists.rename(playlist_id, name, access.known_ids))
    except PlaylistRejected as error:
        raise _rejected(error) from error


def _delete(access: _PlaylistAccess, playlist_id: str) -> None:
    access.changeable(playlist_id)
    access.services.playlists.delete(playlist_id)


def _add_song(access: _PlaylistAccess, playlist_id: str, song_id: str) -> PlaylistDetailView:
    access.changeable(playlist_id)
    try:
        return access.detail(access.services.playlists.add_song(playlist_id, song_id, access.known_ids))
    except PlaylistRejected as error:
        raise _rejected(error) from error


# ---- Box ----

@box_router.get("/artists")
def box_artists(services: Services = Depends(get_services)) -> list[ArtistView]:
    return artists(_visible_albums(services))


@box_router.get("/songs")
def box_songs(services: Services = Depends(get_services)) -> list[SongView]:
    return all_songs(_visible_albums(services))


@box_router.get("/search")
def box_search(q: str = "", services: Services = Depends(get_services)) -> list[SearchHit]:
    return search(_visible_albums(services), q)


@box_router.get("/shuffle")
def box_shuffle(album_id: str | None = None, services: Services = Depends(get_services)) -> list[SongView]:
    """One album in a random order, or (without album_id) all music on the box. USB music is not in "all"."""
    albums = _visible_albums(services)
    if album_id is not None:
        for album, view in albums:
            if album.id == album_id:
                return shuffled(songs_of(album, view))
        raise HTTPException(status_code=404, detail="No such album")
    songs = [song for album, view in albums if album.source is MediaSource.BOX for song in songs_of(album, view)]
    return shuffled(songs, SHUFFLE_ALL_LIMIT)


@box_router.get("/playlists")
def box_playlists(services: Services = Depends(get_services)) -> list[PlaylistView]:
    return _list(_box_access(services))


@box_router.get("/playlists/{playlist_id}")
def box_playlist(playlist_id: str, services: Services = Depends(get_services)) -> PlaylistDetailView:
    access = _box_access(services)
    return access.detail(access.get(playlist_id))


@box_router.post("/playlists")
def box_create_playlist(body: NameRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _create(_box_access(services), body.name, MadeOn.BOX)


@box_router.put("/playlists/{playlist_id}")
def box_rename_playlist(playlist_id: str, body: NameRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _rename(_box_access(services), playlist_id, body.name)


@box_router.delete("/playlists/{playlist_id}")
def box_delete_playlist(playlist_id: str, services: Services = Depends(get_services)) -> None:
    _delete(_box_access(services), playlist_id)


@box_router.post("/playlists/{playlist_id}/songs")
def box_add_song(playlist_id: str, body: SongRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _add_song(_box_access(services), playlist_id, body.song_id)


@box_router.delete("/playlists/{playlist_id}/songs/{song_id}")
def box_remove_song(playlist_id: str, song_id: str, services: Services = Depends(get_services)) -> PlaylistDetailView:
    access = _box_access(services)
    access.changeable(playlist_id)
    return access.detail(services.playlists.remove_song(playlist_id, song_id, access.known_ids))


# ---- Admin app ----

@admin_router.get("/songs")
def admin_songs(services: Services = Depends(get_services)) -> list[SongView]:
    """The songs that can go on a playlist: all songs on the box, A to Z."""
    return sorted(_box_songs(services, ADMIN_ART_PREFIX).values(), key=lambda song: (song.title.casefold(), song.artist.casefold()))


@admin_router.get("/playlists")
def admin_playlists(services: Services = Depends(get_services)) -> list[PlaylistView]:
    return _list(_admin_access(services))


@admin_router.get("/playlists/{playlist_id}")
def admin_playlist(playlist_id: str, services: Services = Depends(get_services)) -> PlaylistDetailView:
    access = _admin_access(services)
    return access.detail(access.get(playlist_id))


@admin_router.post("/playlists")
def admin_create_playlist(body: NameRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _create(_admin_access(services), body.name, MadeOn.ADMIN)


@admin_router.put("/playlists/{playlist_id}")
def admin_rename_playlist(playlist_id: str, body: NameRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _rename(_admin_access(services), playlist_id, body.name)


@admin_router.delete("/playlists/{playlist_id}")
def admin_delete_playlist(playlist_id: str, services: Services = Depends(get_services)) -> None:
    _delete(_admin_access(services), playlist_id)


@admin_router.post("/playlists/{playlist_id}/songs")
def admin_add_song(playlist_id: str, body: SongRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    return _add_song(_admin_access(services), playlist_id, body.song_id)


@admin_router.put("/playlists/{playlist_id}/songs")
def admin_set_songs(playlist_id: str, body: SongOrderRequest, services: Services = Depends(get_services)) -> PlaylistDetailView:
    """The songs in their new order. Leaving a song out removes it."""
    access = _admin_access(services)
    access.get(playlist_id)
    try:
        return access.detail(services.playlists.set_songs(playlist_id, body.song_ids, access.known_ids))
    except PlaylistRejected as error:
        raise _rejected(error) from error
