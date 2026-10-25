from datetime import time
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dabox.usb import UsbStick


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class GameWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: time
    end: time

    @model_validator(mode="after")
    def _end_after_start(self) -> "GameWindow":
        if self.end <= self.start:
            raise ValueError("game window must end after it starts")
        return self


class LimitSettings(BaseModel):
    """Everything the parent picks in the first-run setup (design doc section 4)."""

    model_config = ConfigDict(extra="forbid")

    daily_quota_minutes: int = Field(ge=15, le=720)
    shared_quota: bool
    overrun_minutes: int = Field(ge=0, le=120)
    # None means "no games on this day".
    game_windows: dict[Weekday, GameWindow | None]
    bedtimes: dict[Weekday, time]
    bedtime_overrun: bool
    usb_playback: bool
    usb_games: bool

    @model_validator(mode="after")
    def _every_day_is_set(self) -> "LimitSettings":
        all_days = set(Weekday)
        if set(self.game_windows) != all_days:
            raise ValueError("game_windows must have an entry for every day")
        if set(self.bedtimes) != all_days:
            raise ValueError("bedtimes must have an entry for every day")
        return self


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(pattern=r"^\d{4,8}$")
    timezone: str
    limits: LimitSettings


class MediaSource(StrEnum):
    BOX = "box"
    USB = "usb"


class Film(BaseModel):
    """A single video: a folder with one video in it, or a loose video (DESIGN_CORRECTIONS_2.md, 2.1)."""

    id: str
    title: str
    year: int | None
    plot: str | None
    path: Path
    # The film's own folder, or the video file itself for a loose file.
    folder: Path
    art_path: Path | None
    source: MediaSource
    stick_label: str | None
    fingerprint: str


class Track(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    track_number: int | None
    path: Path
    fingerprint: str


class Album(BaseModel):
    id: str
    title: str
    artist: str
    art_path: Path | None
    folder: Path
    tracks: list[Track]
    source: MediaSource
    stick_label: str | None


class Episode(BaseModel):
    """One video in a group."""

    id: str
    title: str
    # From an "S01E02" marker. Season 0: the group's videos have no markers.
    season: int
    # The episode number, or the video's place in the group (1, 2, ...) without markers.
    number: int
    path: Path
    fingerprint: str
    # The sub-folder inside the group ("Season 1"), or "" for the group's own folder.
    section: str = ""


class Show(BaseModel):
    """A group: a folder with several videos, played in order (DESIGN_CORRECTIONS_2.md, 2.1).
    The name "Show" stays so the ids of TV shows on the box stay the same."""

    id: str
    title: str
    folder: Path
    art_path: Path | None
    episodes: list[Episode]
    source: MediaSource = MediaSource.BOX
    stick_label: str | None = None


class Game(BaseModel):
    id: str
    title: str
    # The file name without its extension. Art sites use this full name.
    file_stem: str
    system: str
    path: Path
    art_path: Path | None
    fingerprint: str
    source: MediaSource
    stick_label: str | None


class ScanReport(BaseModel):
    """What a scan of one drive (or the box) found and skipped, for the USB drive check."""

    videos: int = 0
    groups: int = 0
    albums: int = 0
    songs: int = 0
    games: int = 0
    # Files that are not media, by extension (".xlsx": 1).
    other_files: dict[str, int] = {}
    # System and junk folders that were not read ($RECYCLE.BIN, System Volume Information, ...).
    skipped_folders: int = 0
    # Files the box could not read, with the reason (the first few).
    unreadable: list[str] = []


class Library(BaseModel):
    films: list[Film]
    albums: list[Album]
    shows: list[Show]
    games: list[Game]
    sticks: list[UsbStick]
    # One report for each stick, by the stick's id.
    reports: dict[str, ScanReport] = {}
