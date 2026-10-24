"""Art and details ("posters and info") for videos, groups, albums and games.

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

from dabox.models import Album, Film, Game, Show
from dabox.names import split_year
from dabox.systems import SYSTEMS, thumbnail_file_name
from dabox.store import Store

USER_AGENT = "da-box/0.1 ( https://github.com/PatrickReynoldsCoding/da-box )"
LIBRETRO_THUMBNAILS = "https://thumbnails.libretro.com"
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
COVER_ART_API = "https://coverartarchive.org"
SCREENSCRAPER_API = "https://api.screenscraper.fr/api2"
# Every site the box fetches from. The allow-list proxy (install/files/dabox-filter) must let them through.
SOURCE_URLS = (LIBRETRO_THUMBNAILS, TMDB_API, TMDB_IMAGES, MUSICBRAINZ_API, COVER_ART_API, SCREENSCRAPER_API, "https://archive.org")

# Art downloads may only come from these hosts (and their sub-domains).
ART_HOSTS = ("image.tmdb.org", "coverartarchive.org", "archive.org", "thumbnails.libretro.com")

_ACCOUNTS_KEY = "metadata_accounts"
_ACCOUNT_CHECKS_KEY = "metadata_account_checks"
_LAST_ERROR_KEY = "metadata_last_error"
# "Fargo (2014) Season 5" is searched as "Fargo", 2014.
_SEASON_WORDS = __import__("re").compile(r"(?i)\s*\b(?:season|series|s)\s*\d+\b.*$")
# ScreenScraper's ids for the box's systems.
SCREENSCRAPER_SYSTEMS = {"nes": 3, "snes": 4, "gb": 9, "gbc": 10, "gba": 12, "megadrive": 1, "psx": 57}


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
    # Why a fetch failed, for the TV's Settings and the admin app.
    error: str | None = None


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
    # ScreenScraper (game descriptions, optional): the user's account, and the developer id and
    # password its API also needs (free, asked for on the ScreenScraper forum).
    screenscraper_user: str = ""
    screenscraper_password: str = ""
    screenscraper_dev_id: str = ""
    screenscraper_dev_password: str = ""

    def screenscraper_set(self) -> bool:
        return all((self.screenscraper_user, self.screenscraper_password, self.screenscraper_dev_id, self.screenscraper_dev_password))


class AccountState(StrEnum):
    NOT_NEEDED = "not_needed"
    NOT_SET = "not_set"
    WORKING = "working"
    NOT_WORKING = "not_working"


class AccountView(BaseModel):
    """One source of posters and info, as Settings shows it. Never the key itself."""

    key: str
    name: str
    used_for: str
    state: AccountState
    reason: str | None = None


class LookupStatus(BaseModel):
    accounts: list[AccountView]
    # Items with posters and info (fetched, picked, or their own art next to the file).
    done: int
    waiting: int
    not_found: int
    failed: int
    # Videos and groups that wait for a TMDB key.
    no_account: int
    last_error: str | None


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


def search_terms(title: str) -> tuple[str, int | None]:
    """'Fargo (2014) Season 5' -> ('Fargo', 2014): what to search for a video or group."""
    without_season = _SEASON_WORDS.sub("", title).strip(" -,") or title
    return split_year(without_season)


def _tmdb_kind(provider_id: str) -> tuple[str, str]:
    """'tv:456' -> ('tv', '456'). Records from before TV search have the movie id alone."""
    kind, _, number = provider_id.partition(":")
    return (kind, number) if number else ("movie", kind)


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

    def check(self) -> None:
        """Raises HttpError (401) for a wrong key."""
        self._get("/configuration", {})

    def _search_kind(self, kind: str, title: str, year: int | None) -> list[Candidate]:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year" if kind == "movie" else "first_air_date_year"] = str(year)
        candidates: list[Candidate] = []
        for result in self._get(f"/search/{kind}", params).get("results", [])[:8]:
            poster = result.get("poster_path")
            candidates.append(Candidate(
                provider=self.name,
                provider_id=f"{kind}:{result['id']}",
                title=result.get("title") or result.get("name") or "",
                year=year_from_date(result.get("release_date") or result.get("first_air_date")),
                artist=None,
                description=(("TV series. " if kind == "tv" else "") + (result.get("overview") or "")) or None,
                preview_url=f"{TMDB_IMAGES}/w185{poster}" if poster else None,
            ))
        return candidates

    def search(self, title: str, year: int | None, prefer_tv: bool = False) -> list[Candidate]:
        """Films and TV series together (DESIGN_CORRECTIONS_2.md, 4.2): the kind the item more
        likely is comes first, and an exact title match before the rest."""
        kinds = ("tv", "movie") if prefer_tv else ("movie", "tv")
        found = [candidate for kind in kinds for candidate in self._search_kind(kind, title, year)]
        exact = [candidate for candidate in found if candidate.title.casefold() == title.casefold()]
        return (exact + [candidate for candidate in found if candidate not in exact])[:12]

    def details(self, provider_id: str) -> Metadata:
        kind, number = _tmdb_kind(provider_id)
        found = self._get(f"/{kind}/{number}", {})
        return Metadata(
            status=MetadataStatus.MATCHED,
            title=found.get("title") or found.get("name"),
            year=year_from_date(found.get("release_date") or found.get("first_air_date")),
            plot=found.get("overview") or None,
            provider=self.name,
            provider_id=f"{kind}:{number}",
        )

    def art_options(self, provider_id: str) -> list[ArtOption]:
        kind, number = _tmdb_kind(provider_id)
        images = self._get(f"/{kind}/{number}/images", {"include_image_language": "en,null"})
        options: list[ArtOption] = []
        for poster in images.get("posters", [])[:20]:
            file_path = poster["file_path"]
            options.append(ArtOption(preview_url=f"{TMDB_IMAGES}/w185{file_path}", full_url=f"{TMDB_IMAGES}/w780{file_path}"))
        return options


class ScreenScraperProvider:
    """Game names, descriptions and years from ScreenScraper (optional)."""

    name = "screenscraper"

    def __init__(self, client: HttpClient, accounts: Accounts) -> None:
        self._client = client
        self._accounts = accounts

    def _url(self, page: str, params: dict[str, str]) -> str:
        accounts = self._accounts
        base = {
            "devid": accounts.screenscraper_dev_id, "devpassword": accounts.screenscraper_dev_password,
            "softname": "da-box", "output": "json",
            "ssid": accounts.screenscraper_user, "sspassword": accounts.screenscraper_password,
        }
        return f"{SCREENSCRAPER_API}/{page}?{urllib.parse.urlencode({**base, **params})}"

    def check(self) -> None:
        self._client.get_json(self._url("ssuserInfos.php", {}))

    def game(self, game: Game) -> Metadata | None:
        """None if ScreenScraper does not know the game."""
        system_id = SCREENSCRAPER_SYSTEMS.get(game.system)
        if system_id is None:
            return None
        try:
            found = self._client.get_json(self._url("jeuInfos.php", {
                "systemeid": str(system_id), "romtype": "rom", "romnom": game.path.name,
            }))
        except HttpError as error:
            if error.status == 404:
                return None
            raise
        info = (found.get("response") or {}).get("jeu") or {}
        if not info:
            return None
        return Metadata(
            status=MetadataStatus.MATCHED,
            title=_pick_text(info.get("noms"), "region", ("wor", "us", "eu", "ss")),
            year=year_from_date(_pick_text(info.get("dates"), "region", ("wor", "us", "eu", "jp"))),
            plot=_pick_text(info.get("synopsis"), "langue", ("en",)),
            provider=self.name,
            provider_id=str(info.get("id") or ""),
        )


def _pick_text(entries: Any, key: str, preferred: tuple[str, ...]) -> str | None:
    """ScreenScraper lists one text per region or language: the preferred one, else the first."""
    if not isinstance(entries, list) or not entries:
        return None
    for wanted in preferred:
        for entry in entries:
            if isinstance(entry, dict) and entry.get(key) == wanted and entry.get("text"):
                return str(entry["text"]).strip() or None
    first = entries[0]
    return str(first.get("text", "")).strip() or None if isinstance(first, dict) else None


def error_text(error: Exception) -> str:
    """A short reason for Settings: 'TMDB: invalid key', 'No internet', ..."""
    if isinstance(error, HttpError):
        if error.status == 401:
            return "The key or password is wrong."
        if error.status in (403, 423, 426, 430, 431):
            return f"The site refused the request ({error.status})."
        if error.status == 429:
            return "Too many requests. The box tries again later."
        return f"The site answered {error.status}."
    if isinstance(error, OSError):
        return "No internet, or the site cannot be reached."
    return str(error) or error.__class__.__name__


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

    def _screenscraper(self) -> ScreenScraperProvider | None:
        accounts = self.store.accounts()
        return ScreenScraperProvider(self._client, accounts) if accounts.screenscraper_set() else None

    def search(self, item: Film | Show | Album | Game, title: str, year: int | None, artist: str | None) -> list[Candidate]:
        if isinstance(item, Game):
            raise MetadataError("Games get box art by their file name. Upload a picture to change it.")
        if isinstance(item, (Film, Show)):
            tmdb = self._tmdb()
            if tmdb is None:
                raise MetadataError("Add a TMDB key in Settings to search for videos")
            query, found_year = search_terms(title or item.title)
            return tmdb.search(query, year or found_year, prefer_tv=isinstance(item, Show))
        return self._musicbrainz.search(artist if artist is not None else item.artist, title or item.title)

    def apply_candidate(self, item: Film | Show | Album, candidate: Candidate) -> Metadata:
        if isinstance(item, (Film, Show)):
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

    def art_options(self, item: Film | Show | Album | Game) -> list[ArtOption]:
        metadata = self.store.get(item.id)
        if isinstance(item, Game) or metadata is None or metadata.provider_id is None:
            return []
        if metadata.provider == TmdbProvider.name:
            tmdb = self._tmdb()
            return tmdb.art_options(metadata.provider_id) if tmdb else []
        return self._musicbrainz.art_options(metadata.provider_id)

    def set_art_from_url(self, item: Film | Show | Album, url: str) -> Metadata:
        if not is_allowed_art_url(url):
            raise MetadataError("Art can only come from the metadata sites")
        return self.set_art(item, self._client.get_bytes(url))

    def set_art(self, item: Film | Show | Album | Game, data: bytes) -> Metadata:
        metadata = self.store.get(item.id) or Metadata(status=MetadataStatus.MANUAL)
        try:
            metadata.art_file = self.store.save_art(item.id, data)
        except ValueError as error:
            raise MetadataError(str(error)) from error
        self.store.put(item.id, metadata)
        return metadata

    def edit(self, item: Film | Show | Album | Game, title: str | None, year: int | None, plot: str | None) -> Metadata:
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

    def _fetch_game(self, game: Game) -> Metadata:
        """Box art from libretro-thumbnails; with a ScreenScraper account, also the name, year and description."""
        metadata = self._fetch_game_art(game)
        screenscraper = self._screenscraper()
        if screenscraper is None:
            return metadata
        details = screenscraper.game(game)
        if details is None:
            return metadata
        details.art_file = metadata.art_file
        self.store.put(game.id, details)
        return details

    def auto_fetch(self, item: Film | Show | Album | Game) -> Metadata:
        """Best guess for an item with no art of its own: the first search result."""
        try:
            if isinstance(item, Game):
                return self._fetch_game(item)
            if isinstance(item, (Film, Show)):
                tmdb = self._tmdb()
                if tmdb is None:
                    metadata = Metadata(status=MetadataStatus.NO_ACCOUNT)
                    self.store.put(item.id, metadata)
                    return metadata
                query, year = search_terms(item.title)
                candidates = tmdb.search(query, item.year if isinstance(item, Film) and item.year else year, prefer_tv=isinstance(item, Show))
            else:
                candidates = self._musicbrainz.search(item.artist, item.title)
            if not candidates:
                metadata = Metadata(status=MetadataStatus.NOT_FOUND)
                self.store.put(item.id, metadata)
                return metadata
            return self.apply_candidate(item, candidates[0])
        except (HttpError, OSError, ValueError, KeyError) as error:
            reason = error_text(error)
            self.store.put(item.id, Metadata(status=MetadataStatus.FAILED, error=reason))
            self.store._store.put(_LAST_ERROR_KEY, f"{item.title}: {reason}")
            raise MetadataError(f"Fetch failed: {error}") from error

    def items_to_fetch(self, items: list[Film | Show | Album | Game]) -> list[Film | Show | Album | Game]:
        """Items with no art of their own and no metadata record yet."""
        records = self.store.all()
        return [item for item in items if item.art_path is None and item.id not in records]

    def save_accounts(self, accounts: Accounts) -> None:
        """Items that waited for an account get another try."""
        self.store.save_accounts(accounts)
        for item_id, record in self.store.all().items():
            if record.status is MetadataStatus.NO_ACCOUNT:
                self.store.delete(item_id)

    # ---- Settings: accounts, status, look up now (DESIGN_CORRECTIONS_2.md, part 4) ----

    def check_accounts(self) -> None:
        """Tries each key that is set, once, and keeps the result for Settings."""
        checks: dict[str, dict] = {}
        providers = {"tmdb": self._tmdb(), "screenscraper": self._screenscraper()}
        for key, provider in providers.items():
            if provider is None:
                continue
            try:
                provider.check()
                checks[key] = {"working": True, "reason": None}
            except (HttpError, OSError, ValueError) as error:
                checks[key] = {"working": False, "reason": error_text(error)}
        self.store._store.put(_ACCOUNT_CHECKS_KEY, checks)

    def account_views(self) -> list[AccountView]:
        accounts = self.store.accounts()
        checks = self.store._store.get(_ACCOUNT_CHECKS_KEY) or {}

        def state(key: str, is_set: bool) -> tuple[AccountState, str | None]:
            if not is_set:
                return AccountState.NOT_SET, None
            check = checks.get(key)
            if check is None or check["working"]:
                return AccountState.WORKING, None
            return AccountState.NOT_WORKING, check["reason"]

        tmdb_state, tmdb_reason = state("tmdb", bool(accounts.tmdb_api_key))
        ss_state, ss_reason = state("screenscraper", accounts.screenscraper_set())
        return [
            AccountView(key="tmdb", name="TMDB", used_for="Posters and details for videos and groups", state=tmdb_state, reason=tmdb_reason),
            AccountView(key="musicbrainz", name="MusicBrainz", used_for="Album covers", state=AccountState.NOT_NEEDED),
            AccountView(key="libretro", name="libretro-thumbnails", used_for="Game box art", state=AccountState.NOT_NEEDED),
            AccountView(key="screenscraper", name="ScreenScraper (optional)", used_for="Game descriptions", state=ss_state, reason=ss_reason),
        ]

    def lookup_status(self, items: list[Film | Show | Album | Game]) -> LookupStatus:
        records = self.store.all()
        counts = {"done": 0, "waiting": 0, "not_found": 0, "failed": 0, "no_account": 0}
        for item in items:
            record = records.get(item.id)
            if record is None:
                counts["done" if item.art_path is not None else "waiting"] += 1
            elif record.status in (MetadataStatus.MATCHED, MetadataStatus.MANUAL) or item.art_path is not None:
                counts["done"] += 1
            else:
                counts[record.status.value] += 1
        return LookupStatus(accounts=self.account_views(), last_error=self.store._store.get(_LAST_ERROR_KEY), **counts)

    def look_up_again(self) -> int:
        """Forgets "not found", "failed" and "waits for a key", so the fetcher tries those items again."""
        again = 0
        for item_id, record in self.store.all().items():
            if record.status in (MetadataStatus.NOT_FOUND, MetadataStatus.FAILED, MetadataStatus.NO_ACCOUNT):
                self.store.delete(item_id)
                again += 1
        self.store._store.delete(_LAST_ERROR_KEY)
        return again
