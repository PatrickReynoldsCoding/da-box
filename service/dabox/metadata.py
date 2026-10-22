"""Art and details for films and albums.

Order of trust: what the parent typed or picked > what was fetched > .nfo and
images next to the media > the file name. The box fetches automatically only for
items with no art of their own.
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from dabox.models import Album, Film, Game
from dabox.systems import SYSTEMS, thumbnail_file_name
from dabox.store import Store

USER_AGENT = "da-box/0.1 ( https://github.com/PatrickReynoldsCoding/da-box )"
LIBRETRO_THUMBNAILS = "https://thumbnails.libretro.com"
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
COVER_ART_API = "https://coverartarchive.org"

# Art downloads may only come from these hosts (and their sub-domains).
ART_HOSTS = ("image.tmdb.org", "coverartarchive.org", "archive.org", "thumbnails.libretro.com")

_ACCOUNTS_KEY = "metadata_accounts"


class MetadataStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    NO_ACCOUNT = "no_account"
    FAILED = "failed"
    MANUAL = "manual"


class Metadata(BaseModel):
    status: MetadataStatus
    title: str | None = None
    year: int | None = None
    plot: str | None = None
    artist: str | None = None
    art_file: str | None = None
    provider: str | None = None
    provider_id: str | None = None


class Candidate(BaseModel):
    provider: str
    provider_id: str
    title: str
    year: int | None
    artist: str | None
    description: str | None
    preview_url: str | None


class ArtOption(BaseModel):
    preview_url: str
    full_url: str


class Accounts(BaseModel):
    tmdb_api_key: str = ""


class HttpClient(Protocol):
    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any: ...
    def get_bytes(self, url: str) -> bytes: ...


class HttpError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


class UrllibClient:
    """Plain urllib. It uses HTTPS_PROXY from the environment, which on the box is
    the local allow-list proxy (install/files/tinyproxy.conf)."""

    def _open(self, url: str, headers: dict[str, str] | None) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise HttpError(error.code, url) from error

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        return json.loads(self._open(url, {"Accept": "application/json", **(headers or {})}))

    def get_bytes(self, url: str) -> bytes:
        return self._open(url, None)


def is_allowed_art_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == allowed or host.endswith("." + allowed) for allowed in ART_HOSTS)


def image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG"):
        return ".png"
    return None


def year_from_date(date: str | None) -> int | None:
    return int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None


class TmdbProvider:
    name = "tmdb"

    def __init__(self, client: HttpClient, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    def _get(self, path: str, params: dict[str, str]) -> Any:
        headers: dict[str, str] = {}
        # A v4 "read access token" is long; a v3 API key is 32 characters.
        if len(self._api_key) > 40:
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            params = {**params, "api_key": self._api_key}
        return self._client.get_json(f"{TMDB_API}{path}?{urllib.parse.urlencode(params)}", headers)

    def search(self, title: str, year: int | None) -> list[Candidate]:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        results = self._get("/search/movie", params).get("results", [])
        candidates: list[Candidate] = []
        for result in results[:8]:
            poster = result.get("poster_path")
            candidates.append(
                Candidate(
                    provider=self.name,
                    provider_id=str(result["id"]),
                    title=result.get("title") or "",
                    year=year_from_date(result.get("release_date")),
                    artist=None,
                    description=result.get("overview") or None,
                    preview_url=f"{TMDB_IMAGES}/w185{poster}" if poster else None,
                )
            )
        return candidates

    def details(self, provider_id: str) -> Metadata:
        movie = self._get(f"/movie/{provider_id}", {})
        return Metadata(
            status=MetadataStatus.MATCHED,
            title=movie.get("title"),
            year=year_from_date(movie.get("release_date")),
            plot=movie.get("overview") or None,
            provider=self.name,
            provider_id=provider_id,
        )

    def art_options(self, provider_id: str) -> list[ArtOption]:
        images = self._get(f"/movie/{provider_id}/images", {"include_image_language": "en,null"})
        options: list[ArtOption] = []
        for poster in images.get("posters", [])[:20]:
            file_path = poster["file_path"]
            options.append(ArtOption(preview_url=f"{TMDB_IMAGES}/w185{file_path}", full_url=f"{TMDB_IMAGES}/w780{file_path}"))
        return options


class MusicBrainzProvider:
    name = "musicbrainz"
    # MusicBrainz asks for at most one request per second.
    _MIN_INTERVAL = 1.1

    def __init__(self, client: HttpClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _get(self, url: str) -> Any:
        with self._lock:
            wait = self._MIN_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
        return self._client.get_json(url)

    def search(self, artist: str, album: str) -> list[Candidate]:
        query = f'releasegroup:"{album}"' + (f' AND artist:"{artist}"' if artist else "")
        url = f"{MUSICBRAINZ_API}/release-group/?{urllib.parse.urlencode({'query': query, 'fmt': 'json', 'limit': '8'})}"
        candidates: list[Candidate] = []
        for group in self._get(url).get("release-groups", []):
            credits = group.get("artist-credit") or [{}]
            candidates.append(
                Candidate(
                    provider=self.name,
                    provider_id=group["id"],
                    title=group.get("title") or "",
                    year=year_from_date(group.get("first-release-date")),
                    artist=credits[0].get("name"),
                    description=group.get("primary-type"),
                    preview_url=f"{COVER_ART_API}/release-group/{group['id']}/front-250",
                )
            )
        return candidates

    def details(self, candidate: Candidate) -> Metadata:
        return Metadata(
            status=MetadataStatus.MATCHED,
            title=candidate.title,
            year=candidate.year,
            artist=candidate.artist,
            provider=self.name,
            provider_id=candidate.provider_id,
        )

    def art_options(self, provider_id: str) -> list[ArtOption]:
        try:
            listing = self._client.get_json(f"{COVER_ART_API}/release-group/{provider_id}")
        except HttpError as error:
            if error.status == 404:
                return []
            raise
        options: list[ArtOption] = []
        for image in listing.get("images", []):
            thumbnails = image.get("thumbnails", {})
            preview = thumbnails.get("250") or thumbnails.get("small") or image["image"]
            full = thumbnails.get("1200") or thumbnails.get("large") or image["image"]
            options.append(ArtOption(preview_url=preview.replace("http://", "https://"), full_url=full.replace("http://", "https://")))
        return options


class MetadataStore:
    def __init__(self, store: Store, art_dir: Path) -> None:
        self._store = store
        self.art_dir = art_dir
        art_dir.mkdir(parents=True, exist_ok=True)

    def get(self, item_id: str) -> Metadata | None:
        raw = self._store.get_metadata(item_id)
        return Metadata.model_validate(raw) if raw is not None else None

    def all(self) -> dict[str, Metadata]:
        return {item_id: Metadata.model_validate(raw) for item_id, raw in self._store.all_metadata().items()}

    def put(self, item_id: str, metadata: Metadata) -> None:
        self._store.put_metadata(item_id, metadata.model_dump(mode="json"))

    def delete(self, item_id: str) -> None:
        existing = self.get(item_id)
        if existing and existing.art_file:
            (self.art_dir / existing.art_file).unlink(missing_ok=True)
        self._store.delete_metadata(item_id)

    def save_art(self, item_id: str, data: bytes) -> str:
        extension = image_extension(data)
        if extension is None:
            raise ValueError("The file is not a JPEG or PNG image")
        for old in self.art_dir.glob(f"{item_id}.*"):
            old.unlink()
        file_name = f"{item_id}{extension}"
        (self.art_dir / file_name).write_bytes(data)
        return file_name

    def accounts(self) -> Accounts:
        raw = self._store.get(_ACCOUNTS_KEY)
        return Accounts.model_validate(raw) if raw is not None else Accounts()

    def save_accounts(self, accounts: Accounts) -> None:
        self._store.put(_ACCOUNTS_KEY, accounts.model_dump())


class MetadataError(Exception):
    pass


class MetadataService:
    """Finds, stores and edits metadata. Callers pass in the library item."""

    def __init__(self, store: MetadataStore, client: HttpClient) -> None:
        self.store = store
        self._client = client
        self._musicbrainz = MusicBrainzProvider(client)

    def _tmdb(self) -> TmdbProvider | None:
        key = self.store.accounts().tmdb_api_key
        return TmdbProvider(self._client, key) if key else None

    def search(self, item: Film | Album | Game, title: str, year: int | None, artist: str | None) -> list[Candidate]:
        if isinstance(item, Game):
            raise MetadataError("Games get box art by their file name. Upload a picture to change it.")
        if isinstance(item, Film):
            tmdb = self._tmdb()
            if tmdb is None:
                raise MetadataError("Add a TMDB API key in Settings to search for films")
            return tmdb.search(title or item.title, year)
        return self._musicbrainz.search(artist if artist is not None else item.artist, title or item.title)

    def apply_candidate(self, item: Film | Album, candidate: Candidate) -> Metadata:
        if isinstance(item, Film):
            tmdb = self._tmdb()
            if tmdb is None:
                raise MetadataError("Add a TMDB API key in Settings")
            metadata = tmdb.details(candidate.provider_id)
            options = tmdb.art_options(candidate.provider_id)
        else:
            metadata = self._musicbrainz.details(candidate)
            options = self._musicbrainz.art_options(candidate.provider_id)
        if options:
            metadata.art_file = self.store.save_art(item.id, self._client.get_bytes(options[0].full_url))
        self.store.put(item.id, metadata)
        return metadata

    def art_options(self, item: Film | Album | Game) -> list[ArtOption]:
        metadata = self.store.get(item.id)
        if isinstance(item, Game) or metadata is None or metadata.provider_id is None:
            return []
        if metadata.provider == TmdbProvider.name:
            tmdb = self._tmdb()
            return tmdb.art_options(metadata.provider_id) if tmdb else []
        return self._musicbrainz.art_options(metadata.provider_id)

    def set_art_from_url(self, item: Film | Album, url: str) -> Metadata:
        if not is_allowed_art_url(url):
            raise MetadataError("Art can only come from the metadata sites")
        return self.set_art(item, self._client.get_bytes(url))

    def set_art(self, item: Film | Album, data: bytes) -> Metadata:
        metadata = self.store.get(item.id) or Metadata(status=MetadataStatus.MANUAL)
        try:
            metadata.art_file = self.store.save_art(item.id, data)
        except ValueError as error:
            raise MetadataError(str(error)) from error
        self.store.put(item.id, metadata)
        return metadata

    def edit(self, item: Film | Album, title: str | None, year: int | None, plot: str | None) -> Metadata:
        metadata = self.store.get(item.id) or Metadata(status=MetadataStatus.MANUAL)
        metadata.title = title or None
        metadata.year = year
        metadata.plot = plot or None
        if metadata.status is not MetadataStatus.MATCHED:
            metadata.status = MetadataStatus.MANUAL
        self.store.put(item.id, metadata)
        return metadata

    def _fetch_game_art(self, game: Game) -> Metadata:
        """libretro-thumbnails names box art after the game's No-Intro file name."""
        system = SYSTEMS[game.system]
        url = (
            f"{LIBRETRO_THUMBNAILS}/{urllib.parse.quote(system.thumbnails_name)}/Named_Boxarts/"
            f"{urllib.parse.quote(thumbnail_file_name(game.file_stem))}.png"
        )
        try:
            data = self._client.get_bytes(url)
        except HttpError as error:
            if error.status != 404:
                raise
            metadata = Metadata(status=MetadataStatus.NOT_FOUND)
            self.store.put(game.id, metadata)
            return metadata
        metadata = Metadata(status=MetadataStatus.MATCHED, provider="libretro-thumbnails", art_file=self.store.save_art(game.id, data))
        self.store.put(game.id, metadata)
        return metadata

    def auto_fetch(self, item: Film | Album | Game) -> Metadata:
        """Best guess for an item with no art of its own: the first search result."""
        try:
            if isinstance(item, Game):
                return self._fetch_game_art(item)
            if isinstance(item, Film):
                tmdb = self._tmdb()
                if tmdb is None:
                    metadata = Metadata(status=MetadataStatus.NO_ACCOUNT)
                    self.store.put(item.id, metadata)
                    return metadata
                candidates = tmdb.search(item.title, item.year)
            else:
                candidates = self._musicbrainz.search(item.artist, item.title)
            if not candidates:
                metadata = Metadata(status=MetadataStatus.NOT_FOUND)
                self.store.put(item.id, metadata)
                return metadata
            return self.apply_candidate(item, candidates[0])
        except (HttpError, OSError, ValueError, KeyError) as error:
            metadata = Metadata(status=MetadataStatus.FAILED)
            self.store.put(item.id, metadata)
            raise MetadataError(f"Fetch failed: {error}") from error

    def items_to_fetch(self, items: list[Film | Album | Game]) -> list[Film | Album | Game]:
        """Items with no art of their own and no metadata record yet."""
        records = self.store.all()
        return [item for item in items if item.art_path is None and item.id not in records]

    def save_accounts(self, accounts: Accounts) -> None:
        """Items that waited for an account get another try."""
        self.store.save_accounts(accounts)
        for item_id, record in self.store.all().items():
            if record.status is MetadataStatus.NO_ACCOUNT:
                self.store.delete(item_id)
