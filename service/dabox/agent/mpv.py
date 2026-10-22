import json
import os
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_INPUT_CONFS = {
    "film": Path(__file__).parent / "mpv-input.conf",
    "channel": Path(__file__).parent / "mpv-channel-input.conf",
}
_SOCKET_WAIT_SECONDS = 5.0


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class PlayerKind(StrEnum):
    """What the agent is playing, as the UI and the service see it."""

    VIDEO = "video"
    AUDIO = "audio"
    GAME = "game"


class PlayerState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"


class PlayMode(StrEnum):
    FILM = "film"
    CHANNEL = "channel"


class ControlAction(StrEnum):
    PAUSE = "pause"
    NEXT = "next"
    PREVIOUS = "previous"
    STOP = "stop"
    SEEK_FORWARD = "seek_forward"
    SEEK_BACK = "seek_back"


class PlayItem(BaseModel):
    path: str
    title: str
    artist: str | None = None


class PlayerStatus(BaseModel):
    state: PlayerState
    kind: PlayerKind | None
    title: str | None
    artist: str | None
    index: int | None
    count: int
    position_seconds: float | None
    duration_seconds: float | None
    mode: PlayMode | None = None
    # Keys pressed in the mpv window that the UI must handle ("channel-up", "channel-down").
    requests: list[str] = []


_CONTROL_ACTION_TO_COMMAND: dict[ControlAction, list[Any]] = {
    ControlAction.PAUSE: ["cycle", "pause"],
    ControlAction.NEXT: ["playlist-next"],
    ControlAction.PREVIOUS: ["playlist-prev"],
    ControlAction.STOP: ["quit"],
    ControlAction.SEEK_FORWARD: ["seek", 10],
    ControlAction.SEEK_BACK: ["seek", -10],
}

_KIND_TO_ARGUMENTS: dict[MediaKind, list[str]] = {
    MediaKind.VIDEO: ["--fs", "--force-window=yes", "--osd-level=1", "--osd-bar=yes"],
    MediaKind.AUDIO: ["--no-video", "--force-window=no", "--audio-display=no"],
}


class PathNotAllowed(Exception):
    pass


def check_playable(path: str, allowed_roots: list[Path]) -> Path:
    """Only local files inside the media folders may play. This blocks URLs too."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise PathNotAllowed(f"{path} is not a file on the box")
    for root in allowed_roots:
        if resolved.is_relative_to(root.resolve()):
            return resolved
    raise PathNotAllowed(f"{path} is outside the media folders")


def mpv_arguments(
    kind: MediaKind,
    paths: list[Path],
    start_index: int,
    socket_path: Path,
    extra: list[str],
    mode: PlayMode = PlayMode.FILM,
    start_seconds: float = 0.0,
) -> list[str]:
    start = [f"--start=+{start_seconds:.1f}"] if start_seconds > 0 else []
    return [
        "--config=no",
        "--no-terminal",
        "--idle=no",
        "--ytdl=no",
        "--load-scripts=no",
        "--osc=no",
        "--no-input-default-bindings",
        f"--input-conf={_INPUT_CONFS[mode]}",
        f"--input-ipc-server={socket_path}",
        f"--playlist-start={start_index}",
        *start,
        *_KIND_TO_ARGUMENTS[kind],
        *extra,
        "--",
        *[str(path) for path in paths],
    ]


class MpvPlayer:
    """Runs one mpv at a time and talks to it over its JSON IPC socket."""

    def __init__(self, mpv_binary: str, allowed_roots: list[Path], extra_arguments: list[str]) -> None:
        self._mpv_binary = mpv_binary
        self._allowed_roots = allowed_roots
        self._extra_arguments = extra_arguments
        self._socket_path = Path(tempfile.gettempdir()) / f"dabox-mpv-{os.getpid()}.sock"
        self._process: subprocess.Popen[bytes] | None = None
        self._kind: MediaKind | None = None
        self._items: list[PlayItem] = []
        self._mode: PlayMode | None = None
        self._requests: list[str] = []
        self._lock = threading.Lock()
        self._request_id = 0

    def play(
        self,
        kind: MediaKind,
        items: list[PlayItem],
        start_index: int,
        mode: PlayMode = PlayMode.FILM,
        start_seconds: float = 0.0,
    ) -> None:
        paths = [check_playable(item.path, self._allowed_roots) for item in items]
        with self._lock:
            self._stop_locked()
            self._socket_path.unlink(missing_ok=True)
            arguments = mpv_arguments(kind, paths, start_index, self._socket_path, self._extra_arguments, mode, start_seconds)
            self._process = subprocess.Popen([self._mpv_binary, *arguments])
            self._kind = kind
            self._items = items
            self._mode = mode
            self._requests = []
        self._wait_for_socket()
        threading.Thread(target=self._listen_for_messages, args=(self._process,), daemon=True).start()

    def control(self, action: ControlAction) -> None:
        if not self._is_running():
            return
        self._command(_CONTROL_ACTION_TO_COMMAND[action])

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def take_requests(self) -> list[str]:
        with self._lock:
            requests, self._requests = self._requests, []
        return requests

    def notify(self, message: str) -> None:
        if self._is_running():
            self._command(["show-text", message, 6000])

    def status(self, consume_requests: bool = False) -> PlayerStatus:
        """Only the box UI should consume the key presses. The service only looks."""
        if consume_requests:
            requests = self.take_requests()
        else:
            with self._lock:
                requests = list(self._requests)
        if not self._is_running():
            return PlayerStatus(
                state=PlayerState.IDLE, kind=None, title=None, artist=None, index=None, count=0,
                position_seconds=None, duration_seconds=None, requests=requests,
            )
        index = self._property("playlist-pos")
        item = self._items[index] if isinstance(index, int) and 0 <= index < len(self._items) else None
        return PlayerStatus(
            state=PlayerState.PAUSED if self._property("pause") else PlayerState.PLAYING,
            kind=PlayerKind(self._kind.value) if self._kind else None,
            title=item.title if item else None,
            artist=item.artist if item else None,
            index=index if isinstance(index, int) else None,
            count=len(self._items),
            position_seconds=self._property("time-pos"),
            duration_seconds=self._property("duration"),
            mode=self._mode,
            requests=requests,
        )

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _stop_locked(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._kind = None
        self._items = []
        self._mode = None

    def _wait_for_socket(self) -> None:
        deadline = time.monotonic() + _SOCKET_WAIT_SECONDS
        while time.monotonic() < deadline and self._is_running():
            if self._socket_path.exists():
                return
            time.sleep(0.05)

    def _listen_for_messages(self, process: subprocess.Popen[bytes]) -> None:
        """Keeps one IPC connection open and collects `script-message dabox ...` events."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self._socket_path))
                buffer = b""
                while process.poll() is None:
                    chunk = connection.recv(65536)
                    if not chunk:
                        return
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self._handle_event(json.loads(line))
        except (OSError, ValueError):
            return

    def _handle_event(self, event: dict) -> None:
        arguments = event.get("args") or []
        if event.get("event") == "client-message" and len(arguments) == 2 and arguments[0] == "dabox":
            with self._lock:
                self._requests.append(arguments[1])

    def _property(self, name: str) -> Any:
        return self._command(["get_property", name])

    def _command(self, command: list[Any]) -> Any:
        self._request_id += 1
        request_id = self._request_id
        message = json.dumps({"command": command, "request_id": request_id}) + "\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(str(self._socket_path))
                connection.sendall(message.encode())
                return _read_reply(connection, request_id)
        except OSError:
            # mpv quit between the running check and the command. Treat as no value.
            return None


def _read_reply(connection: socket.socket, request_id: int) -> Any:
    buffer = b""
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            return None
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            reply = json.loads(line)
            # mpv also sends event lines on the socket. Skip them.
            if reply.get("request_id") == request_id:
                return reply.get("data") if reply.get("error") == "success" else None


def extra_arguments_from_env() -> list[str]:
    return shlex.split(os.environ.get("DABOX_MPV_ARGS", ""))
