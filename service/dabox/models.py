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


class Library(BaseModel):
    films: list[Film]
    albums: list[Album]
    sticks: list[UsbStick]
