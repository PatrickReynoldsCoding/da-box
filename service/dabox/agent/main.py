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
    PlayMode,
    PlayerStatus,
    PlayItem,
    extra_arguments_from_env,
)


class PlayRequest(BaseModel):
    kind: MediaKind
    items: list[PlayItem] = Field(min_length=1)
    start_index: int = Field(default=0, ge=0)
    mode: PlayMode = PlayMode.FILM
    # Live channels start part-way through.
    start_seconds: float = Field(default=0.0, ge=0)


class ControlRequest(BaseModel):
    action: ControlAction


def create_agent_app(player: MpvPlayer) -> FastAPI:
    app = FastAPI(title="da-box agent")

    @app.post("/play")
    def play(request: PlayRequest) -> PlayerStatus:
        if request.start_index >= len(request.items):
            raise HTTPException(status_code=422, detail="start_index is past the end of the list")
        try:
            player.play(request.kind, request.items, request.start_index, request.mode, request.start_seconds)
        except PathNotAllowed as rejection:
            raise HTTPException(status_code=403, detail=str(rejection)) from rejection
        return player.status()

    @app.post("/control")
    def control(request: ControlRequest) -> PlayerStatus:
        player.control(request.action)
        return player.status()

    @app.get("/status")
    def status() -> PlayerStatus:
        return player.status()

    return app


def run_agent() -> None:
    media_roots = [Path(root) for root in os.environ.get("DABOX_PLAY_ROOTS", "/srv/dabox/media").split(":") if root]
    player = MpvPlayer(
        mpv_binary=os.environ.get("DABOX_MPV", "mpv"),
        allowed_roots=media_roots,
        extra_arguments=extra_arguments_from_env(),
    )
    port = int(os.environ.get("DABOX_AGENT_PORT", "8091"))
    try:
        uvicorn.run(create_agent_app(player), host="127.0.0.1", port=port, log_level="warning")
    finally:
        player.stop()


if __name__ == "__main__":
    run_agent()
