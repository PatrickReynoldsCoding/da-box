from dabox.auth import AdminAuth
from dabox.models import LimitSettings, SetupRequest
from dabox.store import Store
from dabox.system import TimezoneBackend

_SETUP_COMPLETE_KEY = "setup_complete"
_PARENT_MODE_KEY = "parent_mode"
_LIMITS_KEY = "limits"
_TIMEZONE_KEY = "timezone"


class BoxState:
    """Setup status, parent mode and the parent's settings."""

    def __init__(self, store: Store, auth: AdminAuth, timezone_backend: TimezoneBackend) -> None:
        self._store = store
        self._auth = auth
        self._timezone_backend = timezone_backend

    def setup_required(self) -> bool:
        return self._store.get(_SETUP_COMPLETE_KEY) is not True or not self._auth.has_pin()

    def complete_setup(self, request: SetupRequest) -> None:
        self._timezone_backend.set_timezone(request.timezone)
        self._store.put(_TIMEZONE_KEY, request.timezone)
        self._auth.set_pin(request.pin)
        self.save_limits(request.limits)
        self._store.put(_SETUP_COMPLETE_KEY, True)

    def request_setup_again(self) -> None:
        self._store.put(_SETUP_COMPLETE_KEY, False)

    @property
    def parent_mode(self) -> bool:
        return self._store.get(_PARENT_MODE_KEY) is True

    def set_parent_mode(self, enabled: bool) -> None:
        self._store.put(_PARENT_MODE_KEY, enabled)

    @property
    def timezone(self) -> str | None:
        return self._store.get(_TIMEZONE_KEY)

    def limits(self) -> LimitSettings | None:
        raw = self._store.get(_LIMITS_KEY)
        return LimitSettings.model_validate(raw) if raw is not None else None

    def save_limits(self, limits: LimitSettings) -> None:
        self._store.put(_LIMITS_KEY, limits.model_dump(mode="json"))
