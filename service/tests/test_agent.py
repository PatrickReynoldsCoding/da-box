import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dabox.agent.main import create_agent_app
from dabox.agent.mpv import MediaKind, MpvPlayer, PathNotAllowed, PlayMode, check_playable, mpv_arguments


def test_check_playable_allows_files_in_media_roots(tmp_path: Path) -> None:
    media = tmp_path / "media"
    song = media / "song.mp3"
    song.parent.mkdir()
    song.write_bytes(b"x")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"x")

    assert check_playable(str(song), [media]) == song.resolve()
    for bad in (str(outside), str(media / ".." / "outside.mp3"), "https://example.com/video.mp4", str(media)):
        with pytest.raises(PathNotAllowed):
            check_playable(bad, [media])


def test_mpv_arguments_put_paths_after_double_dash() -> None:
    arguments = mpv_arguments(MediaKind.VIDEO, [Path("/m/--evil.mkv")], 0, Path("/tmp/s.sock"), ["--vo=null"])

    assert arguments[-2:] == ["--", "/m/--evil.mkv"]
    assert "--fs" in arguments and "--ytdl=no" in arguments and "--vo=null" in arguments


def test_agent_rejects_paths_outside_media(tmp_path: Path) -> None:
    client = TestClient(create_agent_app(MpvPlayer("mpv", [tmp_path / "media"], [])))
    response = client.post("/play", json={"kind": "audio", "items": [{"path": "/etc/hosts", "title": "x"}]})
    assert response.status_code == 403
    assert client.get("/status").json()["state"] == "idle"


@pytest.mark.skipif(shutil.which("mpv") is None or shutil.which("ffmpeg") is None, reason="needs mpv and ffmpeg")
def test_agent_plays_controls_and_stops_real_mpv(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    tracks = []
    for number in (1, 2):
        path = media / f"tone{number}.ogg"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={number * 300}:duration=20", str(path)],
            check=True,
        )
        tracks.append({"path": str(path), "title": f"Tone {number}", "artist": "Test"})

    player = MpvPlayer("mpv", [media], ["--ao=null"])
    client = TestClient(create_agent_app(player))
    try:
        assert client.post("/play", json={"kind": "audio", "items": tracks}).status_code == 200
        status = _wait_for(client, lambda body: body["position_seconds"] is not None)
        assert (status["state"], status["title"], status["count"]) == ("playing", "Tone 1", 2)

        assert client.post("/control", json={"action": "pause"}).json()["state"] == "paused"
        client.post("/control", json={"action": "next"})
        assert _wait_for(client, lambda body: body["title"] == "Tone 2")["index"] == 1

        client.post("/control", json={"action": "stop"})
        assert _wait_for(client, lambda body: body["state"] == "idle")["state"] == "idle"
    finally:
        player.stop()


def _wait_for(client: TestClient, condition, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    body = client.get("/status").json()
    while not condition(body) and time.monotonic() < deadline:
        time.sleep(0.1)
        body = client.get("/status").json()
    return body


def test_channel_mode_uses_channel_keys_and_start_offset() -> None:
    arguments = mpv_arguments(MediaKind.VIDEO, [Path("/m/a.mkv")], 0, Path("/tmp/s.sock"), [], PlayMode.CHANNEL, 125.0)
    assert "--start=+125.0" in arguments
    assert any(argument.endswith("mpv-channel-input.conf") for argument in arguments)


def test_script_messages_become_requests(tmp_path: Path) -> None:
    player = MpvPlayer("mpv", [tmp_path], [])
    player._handle_event({"event": "client-message", "args": ["dabox", "channel-up"]})
    player._handle_event({"event": "client-message", "args": ["other", "x"]})
    assert player.status().requests == ["channel-up"]
    assert player.status().requests == []


@pytest.mark.skipif(shutil.which("mpv") is None or shutil.which("ffmpeg") is None, reason="needs mpv and ffmpeg")
def test_real_mpv_starts_part_way_through(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    path = media / "long.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=60", str(path)], check=True)
    player = MpvPlayer("mpv", [media], ["--ao=null"])
    client = TestClient(create_agent_app(player))
    try:
        client.post("/play", json={"kind": "audio", "mode": "channel", "start_seconds": 40,
                                   "items": [{"path": str(path), "title": "Long"}]})
        status = _wait_for(client, lambda body: body["position_seconds"] is not None)
        assert status["position_seconds"] >= 39
        assert status["mode"] == "channel"
    finally:
        player.stop()
