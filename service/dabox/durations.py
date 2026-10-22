"""How long each film, episode and track lasts. The channel schedule needs this.

Audio uses mutagen (fast). Video uses ffprobe. Results are saved by file
fingerprint, so each file is measured once.
"""

import json
import shutil
import subprocess
from pathlib import Path

import mutagen

from dabox.library import AUDIO_EXTENSIONS
from dabox.store import Store

_DURATIONS_KEY = "durations"


def probe_duration(path: Path) -> float | None:
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        try:
            audio = mutagen.File(path)
        except mutagen.MutagenError:
            audio = None
        if audio is not None and audio.info and audio.info.length:
            return float(audio.info.length)
    return _ffprobe_duration(path)


def _ffprobe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        duration = json.loads(result.stdout or "{}").get("format", {}).get("duration")
        return float(duration) if duration else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class Durations:
    """fingerprint -> seconds, kept in the settings table."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._cache: dict[str, float] = store.get(_DURATIONS_KEY) or {}

    def get(self, fingerprint: str) -> float | None:
        return self._cache.get(fingerprint)

    def measure_missing(self, files: dict[str, Path]) -> int:
        """files: fingerprint -> path. Returns how many it measured."""
        measured = 0
        for fingerprint, path in files.items():
            if fingerprint in self._cache:
                continue
            duration = probe_duration(path)
            # 0 means "could not measure", so the file is not tried again on every scan.
            self._cache[fingerprint] = duration or 0.0
            measured += 1
        if measured:
            self._store.put(_DURATIONS_KEY, self._cache)
        return measured

    def record(self, fingerprint: str, seconds: float) -> None:
        self._cache[fingerprint] = seconds
        self._store.put(_DURATIONS_KEY, self._cache)

    def all(self) -> dict[str, float]:
        return dict(self._cache)
