"""Runs RetroArch for one game at a time.

To stop a game, the agent sends SAVE_STATE (to the "auto" slot, see
install/files/retroarch.cfg) and then QUIT. RetroArch loads the auto slot when
the game opens again. RetroArch 1.20 does not save by itself when it quits
through the command port.
"""

import os
import re
import socket
import subprocess
import time
from pathlib import Path

from dabox.agent.mpv import PathNotAllowed, check_playable

COMMAND_PORT = 55355
_QUIT_WAIT_SECONDS = 8.0
_CONFIRM_SECONDS = 1.0
_SAVE_SECONDS = 2.0
_SAVE_KEY_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")


def save_override(saves_dir: Path) -> str:
    """Extra RetroArch settings for one game: where its saves and save states go."""
    return (
        f'savefile_directory = "{saves_dir}"\n'
        f'savestate_directory = "{saves_dir}"\n'
    )


def check_core(core: str, core_dirs: list[Path]) -> Path:
    """The core must sit directly in a core folder. Cores there can be links (to
    Debian's cores); the folder is owned by root, so its links are trusted."""
    candidate = Path(os.path.normpath(core))
    if not candidate.is_file() or not any(candidate.parent == Path(os.path.normpath(folder)) for folder in core_dirs):
        raise PathNotAllowed(f"{core} is not an installed core")
    return candidate


def send_command(command: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(command.encode(), ("127.0.0.1", COMMAND_PORT))


class RetroArchRunner:
    def __init__(self, binary: str, base_config: Path | None, core_dirs: list[Path], saves_root: Path, allowed_roots: list[Path]) -> None:
        self._binary = binary
        self._base_config = base_config
        self._core_dirs = core_dirs
        self._saves_root = saves_root
        self._allowed_roots = allowed_roots
        self._process: subprocess.Popen[bytes] | None = None
        self.title: str | None = None

    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, path: str, core: str, save_key: str, title: str) -> None:
        if not _SAVE_KEY_PATTERN.match(save_key):
            raise PathNotAllowed("Bad save key")
        game = check_playable(path, self._allowed_roots)
        core_path = check_core(core, self._core_dirs)
        saves_dir = self._saves_root / save_key
        saves_dir.mkdir(parents=True, exist_ok=True)
        override = saves_dir / "dabox.cfg"
        override.write_text(save_override(saves_dir))

        self.stop()
        arguments = [self._binary]
        if self._base_config is not None:
            arguments += ["--config", str(self._base_config)]
        arguments += ["--appendconfig", str(override), "-L", str(core_path), str(game)]
        self._process = subprocess.Popen(arguments)
        self.title = title

    def notify(self, message: str) -> None:
        if self.running():
            send_command(f"SHOW_MSG {message}")

    def stop(self) -> None:
        """Saves the game, then asks RetroArch to quit. Kills it only if it does not quit."""
        if self._process is None:
            return
        if self._process.poll() is None:
            send_command("SAVE_STATE")
            time.sleep(_SAVE_SECONDS)
            # RetroArch 1.20 asks to confirm the first QUIT, so send it again.
            send_command("QUIT")
            time.sleep(_CONFIRM_SECONDS)
            if self._process.poll() is None:
                send_command("QUIT")
            deadline = time.monotonic() + _QUIT_WAIT_SECONDS
            while self._process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        self._process = None
        self.title = None
