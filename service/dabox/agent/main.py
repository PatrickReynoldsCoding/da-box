"""Player agent. Runs as the kid user inside the kiosk session, next to the box UI.

The UI cannot talk to mpv's IPC socket (Godot has no UNIX sockets), so it calls
this agent over HTTP on localhost instead.
"""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from dabox.agent.mpv import (
    ControlAction,
    MediaKind,
    MpvPlayer,
    PathNotAllowed,
    PlayerKind,
    PlayerState,
    PlayerStatus,
    PlayItem,
    PlayMode,
    extra_arguments_from_env,
)
from dabox.agent.retroarch import RetroArchRunner


class PlayRequest(BaseModel):
    kind: MediaKind
    items: list[PlayItem] = Field(min_length=1)
    start_index: int = Field(default=0, ge=0)
    mode: PlayMode = PlayMode.FILM
    # Live channels start part-way through.
    start_seconds: float = Field(default=0.0, ge=0)


class ControlRequest(BaseModel):
    action: ControlAction


class GameRequest(BaseModel):
    path: str
    core: str
    # The game file's fingerprint: saves follow the game to any folder or stick.
    save_key: str
    title: str


class NotifyRequest(BaseModel):
    message: str = Field(max_length=200)


def game_status(games: RetroArchRunner) -> PlayerStatus:
    return PlayerStatus(
        state=PlayerState.PLAYING, kind=PlayerKind.GAME, title=games.title, artist=None, index=None, count=1,
        position_seconds=None, duration_seconds=None,
    )


def create_agent_app(player: MpvPlayer, games: RetroArchRunner | None = None) -> FastAPI:
    app = FastAPI(title="da-box agent")

    def current_status(consume_requests: bool = False) -> PlayerStatus:
        if games is not None and games.running():
            return game_status(games)
        return player.status(consume_requests)

    @app.post("/play")
    def play(request: PlayRequest) -> PlayerStatus:
        if request.start_index >= len(request.items):
            raise HTTPException(status_code=422, detail="start_index is past the end of the list")
        if games is not None:
            games.stop()
        try:
            player.play(request.kind, request.items, request.start_index, request.mode, request.start_seconds)
        except PathNotAllowed as rejection:
            raise HTTPException(status_code=403, detail=str(rejection)) from rejection
        return player.status()

    @app.post("/play-game")
    def play_game(request: GameRequest) -> PlayerStatus:
        if games is None:
            raise HTTPException(status_code=503, detail="Games are not set up on this box")
        player.stop()
        try:
            games.start(request.path, request.core, request.save_key, request.title)
        except PathNotAllowed as rejection:
            raise HTTPException(status_code=403, detail=str(rejection)) from rejection
        return current_status()

    @app.post("/control")
    def control(request: ControlRequest) -> PlayerStatus:
        if games is not None and games.running():
            if request.action is ControlAction.STOP:
                games.stop()
            return current_status()
        player.control(request.action)
        return player.status()

    @app.post("/notify")
    def notify(request: NotifyRequest) -> None:
        if games is not None and games.running():
            games.notify(request.message)
        else:
            player.notify(request.message)

    @app.get("/status")
    def status(consume_requests: bool = False) -> PlayerStatus:
        return current_status(consume_requests)

    return app


def run_agent() -> None:
    media_roots = [Path(root) for root in os.environ.get("DABOX_PLAY_ROOTS", "/srv/dabox/media").split(":") if root]
    player = MpvPlayer(
        mpv_binary=os.environ.get("DABOX_MPV", "mpv"),
        allowed_roots=media_roots,
        extra_arguments=extra_arguments_from_env(),
    )
    core_dirs = [Path(folder) for folder in os.environ.get("DABOX_CORE_DIRS", "").split(":") if folder]
    base_config = os.environ.get("DABOX_RETROARCH_CONFIG")
    games = RetroArchRunner(
        binary=os.environ.get("DABOX_RETROARCH", "retroarch"),
        base_config=Path(base_config) if base_config else None,
        core_dirs=core_dirs,
        saves_root=Path(os.environ.get("DABOX_SAVES_DIR", str(Path.home() / ".local/share/dabox/saves"))),
        allowed_roots=media_roots,
    )
    port = int(os.environ.get("DABOX_AGENT_PORT", "8091"))
    try:
        uvicorn.run(create_agent_app(player, games), host="127.0.0.1", port=port, log_level="warning")
    finally:
        games.stop()
        player.stop()


if __name__ == "__main__":
    run_agent()
