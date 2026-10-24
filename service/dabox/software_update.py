"""Updates da-box itself to the newest GitHub release.

The service only checks GitHub for the newest release (through the allow-list proxy) and
starts dabox-upgrade.service. That unit runs as root: it downloads the release's source and
runs its install/install.sh with the options the box was installed with
(install/files/dabox-upgrade).
"""

import re
import time
from pathlib import Path

from pydantic import BaseModel

from dabox.maintenance import Updater
from dabox.metadata import HttpClient, HttpError

SOFTWARE_UNIT = "dabox-upgrade.service"
# Check GitHub again only after this long, unless the parent asks.
CHECK_SECONDS = 6 * 3600

_VERSION_NUMBERS = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


class SoftwareStatus(BaseModel):
    installed: str
    latest: str | None
    # A newer release than the installed version is on GitHub.
    available: bool
    release_url: str | None
    check_error: str | None
    running: bool
    last_result: str | None
    log: list[str]


def version_numbers(version: str) -> tuple[int, int, int] | None:
    """v1.2.3, 1.2 and git describe output (v1.2.3-4-gabcdef) give their numbers; anything else None."""
    match = _VERSION_NUMBERS.match(version.strip())
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3] or 0)


def is_newer(latest: str, installed: str) -> bool:
    latest_numbers, installed_numbers = version_numbers(latest), version_numbers(installed)
    if latest_numbers is None:
        return False
    # An install from a checkout without tags ("unknown", a bare commit) can always take a release.
    return installed_numbers is None or latest_numbers > installed_numbers


class SoftwareUpdates:
    def __init__(self, http: HttpClient, version_file: Path, repo: str, runner: Updater) -> None:
        self._http = http
        self._version_file = version_file
        self._repo = repo
        self._runner = runner
        self._latest: str | None = None
        self._release_url: str | None = None
        self._check_error: str | None = None
        self._checked_at: float | None = None

    def installed(self) -> str:
        try:
            return self._version_file.read_text().strip() or "unknown"
        except OSError:
            return "unknown"

    def check(self) -> None:
        self._checked_at = time.monotonic()
        try:
            release = self._http.get_json(f"https://api.github.com/repos/{self._repo}/releases/latest")
        except HttpError as error:
            self._latest = self._release_url = None
            self._check_error = "There is no release on GitHub yet." if error.status == 404 else f"GitHub answered {error.status}."
            return
        except (OSError, ValueError) as error:
            self._check_error = f"Could not reach GitHub: {error}"
            return
        self._latest = str(release.get("tag_name") or "") or None
        self._release_url = release.get("html_url")
        self._check_error = None

    def status(self, check: bool = False) -> SoftwareStatus:
        if check or self._checked_at is None or time.monotonic() - self._checked_at > CHECK_SECONDS:
            self.check()
        runner = self._runner.status()
        installed = self.installed()
        return SoftwareStatus(
            installed=installed,
            latest=self._latest,
            available=self._latest is not None and is_newer(self._latest, installed),
            release_url=self._release_url,
            check_error=self._check_error,
            running=runner.running,
            last_result=runner.last_result,
            log=runner.log,
        )

    def start(self) -> SoftwareStatus:
        self._runner.start()
        return self.status()
