"""Backup and restore, system updates, and appearance (theme and sounds)."""

import io
import re
import sqlite3
import subprocess
import tempfile
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from dabox.store import Store

_APPEARANCE_KEY = "appearance"
_DB_NAME = "dabox.db"
_ART_FOLDER = "art/"
_SAFE_ART_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class Theme(StrEnum):
    PURPLE = "purple"
    OCEAN = "ocean"
    FOREST = "forest"
    SUNSET = "sunset"


class Appearance(BaseModel):
    theme: Theme = Theme.PURPLE
    sounds: bool = True


def load_appearance(store: Store) -> Appearance:
    raw = store.get(_APPEARANCE_KEY)
    return Appearance.model_validate(raw) if raw is not None else Appearance()


def save_appearance(store: Store, appearance: Appearance) -> None:
    store.put(_APPEARANCE_KEY, appearance.model_dump(mode="json"))


# ---- Backup ----

class RestoreRejected(Exception):
    pass


def make_backup(store: Store, art_dir: Path) -> bytes:
    """A zip with a consistent copy of the database and the art cache."""
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / _DB_NAME
        source = sqlite3.connect(store.path)
        target = sqlite3.connect(copy)
        with target:
            source.backup(target)
        source.close()
        target.close()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, _DB_NAME)
            for art in sorted(art_dir.glob("*")):
                if art.is_file():
                    archive.write(art, _ART_FOLDER + art.name)
    return buffer.getvalue()


def _check_database(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / _DB_NAME
        path.write_bytes(data)
        try:
            connection = sqlite3.connect(path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            connection.close()
        except sqlite3.DatabaseError as error:
            raise RestoreRejected("The backup's database is damaged") from error
    if not {"settings", "hidden_items"} <= tables:
        raise RestoreRejected("This is not a da-box backup")


def restore_backup(data: bytes, store: Store, art_dir: Path) -> None:
    """Replaces the database and the art cache. Only known file names are taken
    from the zip, so a bad zip cannot write anywhere else."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise RestoreRejected("This file is not a backup zip") from error
    names = archive.namelist()
    if _DB_NAME not in names:
        raise RestoreRejected("This is not a da-box backup")
    database = archive.read(_DB_NAME)
    _check_database(database)

    art_files: dict[str, bytes] = {}
    for name in names:
        if name.startswith(_ART_FOLDER) and _SAFE_ART_NAME.match(name.removeprefix(_ART_FOLDER)):
            art_files[name.removeprefix(_ART_FOLDER)] = archive.read(name)

    partial = store.path.with_name(store.path.name + ".restoring")
    partial.write_bytes(database)
    partial.replace(store.path)
    art_dir.mkdir(parents=True, exist_ok=True)
    for old in art_dir.glob("*"):
        if old.is_file():
            old.unlink()
    for name, content in art_files.items():
        (art_dir / name).write_bytes(content)


# ---- System updates ----

class UpdateStatus(BaseModel):
    running: bool
    last_result: str | None
    log: list[str]


class Updater(Protocol):
    def start(self) -> None: ...
    def status(self) -> UpdateStatus: ...


_UPDATE_UNIT = "dabox-update.service"


class SystemdUpdater:
    """Starts a root update unit and reports on it. dabox-update.service (the default) opens
    the firewall, upgrades the Debian packages, and closes the firewall again
    (install/files/dabox-update). dabox-upgrade.service updates da-box itself."""

    def __init__(self, unit: str = _UPDATE_UNIT) -> None:
        self._unit = unit

    def start(self) -> None:
        subprocess.run(["systemctl", "start", "--no-block", self._unit], check=True, timeout=30)

    def status(self) -> UpdateStatus:
        show = subprocess.run(
            ["systemctl", "show", "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus", self._unit],
            capture_output=True, text=True, timeout=10,
        ).stdout
        values = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
        journal = subprocess.run(
            ["journalctl", "-u", self._unit, "-n", "15", "-o", "short", "--no-pager", "-q"],
            capture_output=True, text=True, timeout=10,
        ).stdout.splitlines()
        return UpdateStatus(
            running=values.get("ActiveState") in ("activating", "active"),
            last_result=update_result(values, journal),
            log=journal,
        )


def update_result(values: dict[str, str], journal: list[str]) -> str | None:
    """systemd keeps no start time for this oneshot unit, so the log shows when it ran."""
    if values.get("ActiveState") in ("activating", "active") or not journal:
        return None
    if values.get("Result") == "success" and values.get("ExecMainStatus", "0") == "0":
        return "OK"
    return f"Failed ({values.get('Result')}). See the log below."


class FakeUpdater:
    def __init__(self) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1

    def status(self) -> UpdateStatus:
        return UpdateStatus(running=False, last_result="OK" if self.started else None, log=["Dev mode: nothing was updated."] if self.started else [])


# ---- Removing da-box ----

class Remover(Protocol):
    def start(self, purge: bool) -> None: ...


class SystemdRemover:
    """Starts dabox-remove@keep.service or dabox-remove@purge.service (root). It runs
    install/uninstall.sh (installed as /opt/dabox/bin/dabox-uninstall) and restarts the
    machine into plain Linux. This service stops on the way, so nothing reports back."""

    def start(self, purge: bool) -> None:
        unit = f"dabox-remove@{'purge' if purge else 'keep'}.service"
        subprocess.run(["systemctl", "start", "--no-block", unit], check=True, timeout=30)


class FakeRemover:
    def __init__(self) -> None:
        self.started: list[bool] = []

    def start(self, purge: bool) -> None:
        self.started.append(purge)
