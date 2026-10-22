from datetime import datetime, timedelta
from pathlib import Path

from dabox.auth import (
    FIRST_LOCKOUT,
    FREE_ATTEMPTS,
    MAX_LOCKOUT,
    AdminAuth,
    LockedOut,
    LoginSucceeded,
    NoPinSet,
    WrongPin,
    hash_pin,
    lockout_for,
    verify_pin,
)
from dabox.store import Store

NOW = datetime(2026, 10, 22, 12, 0)


def make_auth(tmp_path: Path) -> AdminAuth:
    auth = AdminAuth(Store(tmp_path / "test.db"))
    auth.set_pin("1234")
    return auth


def test_hash_and_verify_pin() -> None:
    stored = hash_pin("1234")
    assert verify_pin("1234", stored)
    assert not verify_pin("4321", stored)
    assert hash_pin("1234") != stored


def test_lockout_grows_and_caps() -> None:
    assert lockout_for(FREE_ATTEMPTS - 1) == timedelta(0)
    assert lockout_for(FREE_ATTEMPTS) == FIRST_LOCKOUT
    assert lockout_for(FREE_ATTEMPTS + 1) == FIRST_LOCKOUT * 2
    assert lockout_for(FREE_ATTEMPTS + 20) == MAX_LOCKOUT


def test_login_without_pin(tmp_path: Path) -> None:
    assert AdminAuth(Store(tmp_path / "test.db")).login("1234", NOW) == NoPinSet()


def test_wrong_pins_lead_to_lockout_and_lockout_survives_restart(tmp_path: Path) -> None:
    auth = make_auth(tmp_path)
    for attempt in range(1, FREE_ATTEMPTS):
        assert auth.login("0000", NOW) == WrongPin(attempts_before_lockout=FREE_ATTEMPTS - attempt)

    locked = auth.login("0000", NOW)
    assert locked == LockedOut(until=NOW + FIRST_LOCKOUT)

    restarted = AdminAuth(Store(tmp_path / "test.db"))
    assert isinstance(restarted.login("1234", NOW + timedelta(seconds=10)), LockedOut)
    assert isinstance(restarted.login("1234", NOW + FIRST_LOCKOUT), LoginSucceeded)


def test_success_resets_failures(tmp_path: Path) -> None:
    auth = make_auth(tmp_path)
    auth.login("0000", NOW)
    assert isinstance(auth.login("1234", NOW), LoginSucceeded)
    assert auth.login("0000", NOW) == WrongPin(attempts_before_lockout=FREE_ATTEMPTS - 1)


def test_sessions_expire_and_log_out(tmp_path: Path) -> None:
    auth = make_auth(tmp_path)
    result = auth.login("1234", NOW)
    assert isinstance(result, LoginSucceeded)

    assert auth.is_session_valid(result.token, NOW)
    assert not auth.is_session_valid(result.token, NOW + timedelta(days=1))
    assert not auth.is_session_valid("made-up", NOW)

    second = auth.login("1234", NOW)
    assert isinstance(second, LoginSucceeded)
    auth.logout(second.token)
    assert not auth.is_session_valid(second.token, NOW)
