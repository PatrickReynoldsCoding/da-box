"""Access to the operating system: network, Wi-Fi and time zone.

The real versions call nmcli and timedatectl on the box. The fake versions are
for dev mode on a Mac and for tests.
"""

import socket
import subprocess
import zoneinfo
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class ConnectionType(StrEnum):
    ETHERNET = "ethernet"
    WIFI = "wifi"
    NONE = "none"


class NetworkStatus(BaseModel):
    connection_type: ConnectionType
    ip_address: str | None
    wifi_available: bool


class WifiNetwork(BaseModel):
    ssid: str
    signal: int
    secure: bool


class WifiConnectResult(BaseModel):
    connected: bool
    message: str


class NetworkBackend(Protocol):
    def status(self) -> NetworkStatus: ...
    def scan_wifi(self) -> list[WifiNetwork]: ...
    def connect_wifi(self, ssid: str, password: str) -> WifiConnectResult: ...


class TimezoneBackend(Protocol):
    def set_timezone(self, timezone: str) -> None: ...


def available_timezones() -> list[str]:
    zones: list[str] = []
    for zone in zoneinfo.available_timezones():
        # Region/City zones only. Skips aliases like "EST5EDT" and "posixrules".
        if "/" in zone and not zone.startswith(("Etc/", "posix/", "right/", "SystemV/")):
            zones.append(zone)
    return sorted(zones)


def lan_ip_address() -> str | None:
    """IP of the interface with the default route. Connecting a UDP socket sends no packets."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


_NMCLI_DEVICE_TYPE_TO_CONNECTION = {
    "ethernet": ConnectionType.ETHERNET,
    "wifi": ConnectionType.WIFI,
}


def parse_nmcli_devices(output: str) -> tuple[ConnectionType, bool]:
    """Parses `nmcli -t -f TYPE,STATE device`. Returns (active connection, Wi-Fi hardware present)."""
    active = ConnectionType.NONE
    wifi_available = False
    for line in output.splitlines():
        device_type, _, state = line.partition(":")
        if device_type == "wifi":
            wifi_available = True
        if state == "connected" and active is ConnectionType.NONE:
            active = _NMCLI_DEVICE_TYPE_TO_CONNECTION.get(device_type, ConnectionType.NONE)
    return active, wifi_available


def split_nmcli_fields(line: str) -> list[str]:
    """Splits a terse nmcli line on ':' while keeping escaped '\\:' inside fields."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    fields.append("".join(current))
    return fields


def parse_nmcli_wifi_list(output: str) -> list[WifiNetwork]:
    """Parses `nmcli -t -f SSID,SIGNAL,SECURITY device wifi list`. Keeps the strongest entry per SSID."""
    strongest: dict[str, WifiNetwork] = {}
    for line in output.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) < 3 or not fields[0]:
            continue
        ssid, signal_text, security = fields[0], fields[1], fields[2]
        network = WifiNetwork(ssid=ssid, signal=int(signal_text or 0), secure=bool(security.strip()))
        if ssid not in strongest or network.signal > strongest[ssid].signal:
            strongest[ssid] = network
    return sorted(strongest.values(), key=lambda network: -network.signal)


def resolve_connection(nmcli_connection: ConnectionType, ip_address: str | None) -> ConnectionType:
    """A wired network set up outside NetworkManager shows as "unmanaged". It still works."""
    if nmcli_connection is ConnectionType.NONE and ip_address:
        return ConnectionType.ETHERNET
    return nmcli_connection


class NmcliNetwork:
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["nmcli", *arguments], capture_output=True, text=True, timeout=45)

    def status(self) -> NetworkStatus:
        ip_address = lan_ip_address()
        try:
            result = self._run("-t", "-f", "TYPE,STATE", "device")
            nmcli_connection, wifi_available = parse_nmcli_devices(result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            nmcli_connection, wifi_available = ConnectionType.NONE, False
        return NetworkStatus(
            connection_type=resolve_connection(nmcli_connection, ip_address),
            ip_address=ip_address,
            wifi_available=wifi_available,
        )

    def scan_wifi(self) -> list[WifiNetwork]:
        result = self._run("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes")
        return parse_nmcli_wifi_list(result.stdout)

    def connect_wifi(self, ssid: str, password: str) -> WifiConnectResult:
        arguments = ["device", "wifi", "connect", ssid]
        if password:
            arguments += ["password", password]
        result = self._run(*arguments)
        message = (result.stdout or result.stderr).strip()
        return WifiConnectResult(connected=result.returncode == 0, message=message)


class TimedatectlTimezone:
    def set_timezone(self, timezone: str) -> None:
        subprocess.run(["timedatectl", "set-timezone", timezone], check=True, timeout=15)


class FakeNetwork:
    """Dev-mode network: wired, with two pretend Wi-Fi networks."""

    def __init__(self) -> None:
        self._connection = ConnectionType.ETHERNET

    def status(self) -> NetworkStatus:
        return NetworkStatus(connection_type=self._connection, ip_address=lan_ip_address(), wifi_available=True)

    def scan_wifi(self) -> list[WifiNetwork]:
        return [
            WifiNetwork(ssid="Home Wi-Fi", signal=82, secure=True),
            WifiNetwork(ssid="Neighbour", signal=31, secure=True),
        ]

    def connect_wifi(self, ssid: str, password: str) -> WifiConnectResult:
        if len(password) < 8:
            return WifiConnectResult(connected=False, message="Password is too short")
        self._connection = ConnectionType.WIFI
        return WifiConnectResult(connected=True, message=f"Connected to {ssid}")


class FakeTimezone:
    def __init__(self) -> None:
        self.timezone: str | None = None

    def set_timezone(self, timezone: str) -> None:
        self.timezone = timezone
