import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from dabox.store import Store

_PIN_HASH_KEY = "admin_pin_hash"
_FAILED_ATTEMPTS_KEY = "admin_failed_attempts"
_LOCKED_UNTIL_KEY = "admin_locked_until"

FREE_ATTEMPTS = 5
FIRST_LOCKOUT = timedelta(minutes=1)
MAX_LOCKOUT = timedelta(minutes=30)
SESSION_LIFETIME = timedelta(hours=12)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    _, salt_hex, digest_hex = stored_hash.split("$")
    digest = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex), n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return hmac.compare_digest(digest.hex(), digest_hex)


def lockout_for(failed_attempts: int) -> timedelta:
    """No lockout for the first few tries, then the lockout doubles each time."""
    if failed_attempts < FREE_ATTEMPTS:
        return timedelta(0)
    doublings = failed_attempts - FREE_ATTEMPTS
    return min(FIRST_LOCKOUT * (2**doublings), MAX_LOCKOUT)


@dataclass(frozen=True)
class LoginSucceeded:
    token: str


@dataclass(frozen=True)
class WrongPin:
    attempts_before_lockout: int


@dataclass(frozen=True)
class LockedOut:
    until: datetime


@dataclass(frozen=True)
class NoPinSet:
    pass


LoginResult = LoginSucceeded | WrongPin | LockedOut | NoPinSet


class AdminAuth:
    """PIN check with a lockout that is saved, so a restart does not reset it."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._sessions: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def has_pin(self) -> bool:
        return self._store.get(_PIN_HASH_KEY) is not None

    def set_pin(self, pin: str) -> None:
        self._store.put(_PIN_HASH_KEY, hash_pin(pin))

    def check_pin(self, pin: str) -> bool:
        stored_hash = self._store.get(_PIN_HASH_KEY)
        return stored_hash is not None and verify_pin(pin, stored_hash)

    def login(self, pin: str, now: datetime) -> LoginResult:
        with self._lock:
            if not self.has_pin():
                return NoPinSet()

            locked_until_raw = self._store.get(_LOCKED_UNTIL_KEY)
            if locked_until_raw is not None:
                locked_until = datetime.fromisoformat(locked_until_raw)
                if now < locked_until:
                    return LockedOut(until=locked_until)

            if self.check_pin(pin):
                self._store.put(_FAILED_ATTEMPTS_KEY, 0)
                self._store.delete(_LOCKED_UNTIL_KEY)
                return LoginSucceeded(token=self._new_session(now))

            failed_attempts = (self._store.get(_FAILED_ATTEMPTS_KEY) or 0) + 1
            self._store.put(_FAILED_ATTEMPTS_KEY, failed_attempts)
            lockout = lockout_for(failed_attempts)
            if lockout:
                until = now + lockout
                self._store.put(_LOCKED_UNTIL_KEY, until.isoformat())
                return LockedOut(until=until)
            return WrongPin(attempts_before_lockout=FREE_ATTEMPTS - failed_attempts)

    def _new_session(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + SESSION_LIFETIME
        return token

    def is_session_valid(self, token: str | None, now: datetime) -> bool:
        if token is None:
            return False
        expires = self._sessions.get(token)
        if expires is None or now >= expires:
            self._sessions.pop(token, None)
            return False
        return True

    def logout(self, token: str | None) -> None:
        if token is not None:
            self._sessions.pop(token, None)
