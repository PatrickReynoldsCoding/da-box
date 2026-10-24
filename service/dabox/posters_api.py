"""Posters and info in Settings on the TV (DESIGN_CORRECTIONS_2.md, part 4): the sources and their
keys, what was found, and Look up now. No parent mode: Settings is for anyone. Fixing a wrong
match on the TV needs parent mode, as it changes what the kids see."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dabox.metadata import Accounts, Candidate, LookupStatus, Metadata, MetadataError
from dabox.services import Services, get_services, require_admin, require_box_client, require_parent_mode

box_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client)])
parent_router = APIRouter(prefix="/box", dependencies=[Depends(require_box_client), Depends(require_parent_mode)])
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class AccountsUpdate(BaseModel):
    """Only the fields that are sent change. An empty string removes a key."""

    tmdb_api_key: str | None = None
    screenscraper_user: str | None = None
    screenscraper_password: str | None = None
    screenscraper_dev_id: str | None = None
    screenscraper_dev_password: str | None = None


class SearchRequest(BaseModel):
    title: str = ""
    year: int | None = None
    artist: str | None = None


def lookup_status(services: Services) -> LookupStatus:
    library = services.library.library
    return services.metadata.lookup_status([*library.films, *library.shows, *library.albums, *library.games])


def save_accounts(services: Services, update: AccountsUpdate) -> None:
    """Saves the keys that were sent, tries them once, and wakes the fetcher."""
    changes = {name: value.strip() for name, value in update.model_dump().items() if value is not None}
    accounts = Accounts(**{**services.metadata.store.accounts().model_dump(), **changes})
    services.metadata.save_accounts(accounts)
    services.metadata.check_accounts()
    services.metadata_wanted.set()


@box_router.get("/posters")
def box_lookup_status(services: Services = Depends(get_services)) -> LookupStatus:
    return lookup_status(services)


@box_router.put("/posters/accounts")
def box_save_accounts(update: AccountsUpdate, services: Services = Depends(get_services)) -> LookupStatus:
    save_accounts(services, update)
    return lookup_status(services)


@box_router.post("/posters/lookup")
def box_look_up_now(services: Services = Depends(get_services)) -> LookupStatus:
    """The Settings "Look up now" button: everything without posters and info is tried again."""
    services.metadata.look_up_again()
    services.metadata_wanted.set()
    return lookup_status(services)


@admin_router.get("/posters")
def admin_lookup_status(services: Services = Depends(get_services)) -> LookupStatus:
    return lookup_status(services)


@admin_router.put("/posters/accounts")
def admin_save_accounts(update: AccountsUpdate, services: Services = Depends(get_services)) -> LookupStatus:
    save_accounts(services, update)
    return lookup_status(services)


@admin_router.post("/posters/lookup")
def admin_look_up_now(services: Services = Depends(get_services)) -> LookupStatus:
    services.metadata.look_up_again()
    services.metadata_wanted.set()
    return lookup_status(services)


@parent_router.post("/content/{item_id}/metadata/search")
def box_search(item_id: str, body: SearchRequest, services: Services = Depends(get_services)) -> list[Candidate]:
    item = services.item_or_404(item_id)
    try:
        return services.metadata.search(item, body.title, body.year, body.artist)
    except MetadataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@parent_router.post("/content/{item_id}/metadata/apply")
def box_apply(item_id: str, candidate: Candidate, services: Services = Depends(get_services)) -> Metadata:
    item = services.item_or_404(item_id)
    try:
        return services.metadata.apply_candidate(item, candidate)
    except (MetadataError, OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
