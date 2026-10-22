from dabox.system import (
    ConnectionType,
    WifiNetwork,
    available_timezones,
    parse_nmcli_devices,
    parse_nmcli_wifi_list,
    resolve_connection,
    split_nmcli_fields,
)


def test_parse_nmcli_devices() -> None:
    output = "ethernet:connected\nwifi:disconnected\nloopback:connected (externally)\n"
    assert parse_nmcli_devices(output) == (ConnectionType.ETHERNET, True)
    assert parse_nmcli_devices("wifi:connected\n") == (ConnectionType.WIFI, True)
    assert parse_nmcli_devices("ethernet:unavailable\n") == (ConnectionType.NONE, False)


def test_split_nmcli_fields_keeps_escaped_colons() -> None:
    assert split_nmcli_fields(r"My\:Net:70:WPA2") == ["My:Net", "70", "WPA2"]


def test_parse_nmcli_wifi_list_dedupes_and_sorts() -> None:
    output = "Home:40:WPA2\nHome:80:WPA2\nCafe:60:\n:90:WPA2\n"
    assert parse_nmcli_wifi_list(output) == [
        WifiNetwork(ssid="Home", signal=80, secure=True),
        WifiNetwork(ssid="Cafe", signal=60, secure=False),
    ]


def test_available_timezones_are_region_city() -> None:
    zones = available_timezones()
    assert "Europe/London" in zones
    assert "EST5EDT" not in zones
    assert zones == sorted(zones)


def test_resolve_connection_counts_unmanaged_wired_network() -> None:
    assert resolve_connection(ConnectionType.NONE, "10.0.2.15") is ConnectionType.ETHERNET
    assert resolve_connection(ConnectionType.NONE, None) is ConnectionType.NONE
    assert resolve_connection(ConnectionType.WIFI, "192.168.1.5") is ConnectionType.WIFI
