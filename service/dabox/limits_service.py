"""Applies the limits: approves videos and games, counts usage, warns, stops and shuts down.

It runs in the service (user tvbox), so the limits hold even if the box UI crashes.
"""

import json
import logging
import subprocess
import threading
import time as monotonic_time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from dabox.activity import ActivityLog
from dabox.box_state import BoxState
from dabox.limits import (
    SHUTDOWN_DELAY,
    Decision,
    LimitsStatus,
    Notify,
    PlayerSnapshot,
    ScheduleShutdown,
    StopPlayback,
    UsageStore,
    compute_status,
    decide,
    may_start_game,
    may_start_video,
    usage_day,
)

log = logging.getLogger(__name__)

# Longer gaps between ticks (for example after a pause in the VM) do not count as play time.
_MAX_TICK_SECONDS = 10.0


class AgentClient(Protocol):
    def status(self) -> PlayerSnapshot | None: ...
    def stop(self) -> None: ...
    def notify(self, message: str) -> None: ...


class PowerBackend(Protocol):
    def power_off(self) -> None: ...


class HttpAgentClient:
    """Talks to the player agent on localhost, never through the proxy."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(self, path: str, body: dict | None = None) -> dict | None:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=5) as response:
                return json.loads(response.read())
        except (OSError, ValueError):
            return None

    def status(self) -> PlayerSnapshot | None:
        raw = self._call("/status")
        return PlayerSnapshot(state=raw["state"], kind=raw.get("kind"), title=raw.get("title")) if raw else None

    def stop(self) -> None:
        self._call("/control", {"action": "stop"})

    def notify(self, message: str) -> None:
        self._call("/notify", {"message": message})


class SystemdPower:
    def power_off(self) -> None:
        subprocess.run(["systemctl", "poweroff"], check=False, timeout=30)


class FakePower:
    def __init__(self) -> None:
        self.powered_off = False

    def power_off(self) -> None:
        log.warning("Dev mode: the box would power off now")
        self.powered_off = True


class LimitsService:
    def __init__(
        self,
        usage: UsageStore,
        box_state: BoxState,
        clock: Callable[[], datetime],
        agent: AgentClient,
        power: PowerBackend,
        activity: ActivityLog,
    ) -> None:
        self.activity = activity
        self._usage = usage
        self._box_state = box_state
        self._clock = clock
        self._agent = agent
        self._power = power
        self._lock = threading.Lock()
        self._approved_video_until: datetime | None = None
        self._shutdown_at: datetime | None = None
        self._shutdown_reason: str | None = None
        self._notified: set[str] = set()
        self._last_tick: float | None = None
        # Replaceable in tests.
        self.monotonic: Callable[[], float] = monotonic_time.monotonic

    # ---- Reading ----

    def status(self) -> LimitsStatus:
        now = self._clock()
        status = compute_status(self._box_state.limits(), self._usage.get(usage_day(now)), now, self._box_state.parent_mode)
        status.shutdown_at = self._shutdown_at
        if self._shutdown_at is not None and self._shutdown_reason:
            status.video_locked = True
            status.video_locked_reason = self._shutdown_reason
        return status

    # ---- Approvals (the UI asks before it plays) ----

    def approve_video(self, seconds: float) -> Decision:
        with self._lock:
            status = self.status()
            decision = may_start_video(status, seconds)
            if decision.allowed:
                self._approved_video_until = status.now + timedelta(seconds=seconds)
            return decision

    def approve_game(self) -> Decision:
        with self._lock:
            decision = may_start_game(self.status())
            if decision.allowed:
                self._notified = {key for key in self._notified if not key.startswith("game-")}
            return decision

    # ---- Parent ----

    def add_extra_time(self, quota_minutes: int, game_minutes: int) -> LimitsStatus:
        with self._lock:
            day = usage_day(self._clock())
            usage = self._usage.get(day)
            usage.extra_quota_minutes += quota_minutes
            usage.extra_game_minutes += game_minutes
            self._usage.put(day, usage)
            # Extra time cancels a shut-down that has not happened yet.
            self._shutdown_at = None
            self._shutdown_reason = None
        return self.status()

    # ---- The enforcer tick (every couple of seconds) ----

    def power_off_now(self) -> None:
        """The TV's power menu: stop what plays (a game saves first), then turn the box off."""
        with self._lock:
            self._agent.stop()
            self._shutdown_at = None
            self._power.power_off()

    def tick(self) -> None:
        with self._lock:
            now = self._clock()
            player = self._agent.status() or PlayerSnapshot(state="idle", kind=None)
            self._count_usage(now, player)
            self.activity.observe(player.kind, player.title, player.active, now)
            if self._box_state.parent_mode:
                self._shutdown_at = None
                return
            if self._shutdown_at is not None:
                if now >= self._shutdown_at:
                    self._agent.stop()
                    self._shutdown_at = None
                    self._power.power_off()
                return
            usage = self._usage.get(usage_day(now))
            status = compute_status(self._box_state.limits(), usage, now, False)
            for action in decide(status, usage, player, self._approved_video_until, False):
                self._apply(action, now)

    def _count_usage(self, now: datetime, player: PlayerSnapshot) -> None:
        current = self.monotonic()
        elapsed = 0.0 if self._last_tick is None else min(current - self._last_tick, _MAX_TICK_SECONDS)
        self._last_tick = current
        if player.state != "playing" or player.kind not in ("video", "game") or elapsed <= 0:
            return
        day = usage_day(now)
        usage = self._usage.get(day)
        if player.kind == "video":
            usage.video_seconds += elapsed
        else:
            usage.game_seconds += elapsed
        self._usage.put(day, usage)

    def _apply(self, action: StopPlayback | Notify | ScheduleShutdown, now: datetime) -> None:
        if isinstance(action, Notify) and action.key in self._notified:
            return
        # One line per action, so a parent can see later why something stopped.
        log.info("Limits at %s: %s", now.isoformat(timespec="seconds"), action)
        match action:
            case StopPlayback(message=message):
                self._agent.notify(message)
                self._agent.stop()
                self._approved_video_until = None
            case Notify(key=key, message=message):
                self._notified.add(key)
                self._agent.notify(message)
            case ScheduleShutdown(reason=reason, quota=quota):
                self._shutdown_at = now + SHUTDOWN_DELAY
                self._shutdown_reason = reason
                if quota:
                    day = usage_day(now)
                    usage = self._usage.get(day)
                    usage.quota_shutdown_done = True
                    self._usage.put(day, usage)
