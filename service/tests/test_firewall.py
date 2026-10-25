"""The firewall the installer writes (install/files/nftables.conf)."""

import re
from pathlib import Path

FIREWALL = Path(__file__).parents[2] / "install" / "files" / "nftables.conf"


def _chain(name: str) -> list[str]:
    text = FIREWALL.read_text()
    match = re.search(rf"chain {name} \{{(.*?)\n  \}}", text, re.S)
    assert match, f"no {name} chain"
    return [line.strip() for line in match.group(1).splitlines() if line.strip() and not line.strip().startswith("#")]


def test_admin_app_is_open_to_the_home_network_on_http():
    rules = _chain("input")
    assert "ip saddr @home4 tcp dport 80 accept" in rules
    assert "ip6 saddr @home6 tcp dport 80 accept" in rules


def test_https_is_refused_at_once_so_browsers_fall_back_to_http():
    # Chrome tries https first; a dropped packet makes it wait instead of falling back.
    rules = _chain("input")
    assert "ip saddr @home4 tcp dport 443 reject with tcp reset" in rules
    assert "ip6 saddr @home6 tcp dport 443 reject with tcp reset" in rules
    assert not any("dport 443 accept" in rule for rule in rules)


def test_the_refusal_can_leave_the_box():
    # The tcp reset goes out through the output chain, which only lets home addresses through.
    rules = _chain("output")
    assert "ip daddr @home4 accept" in rules
    assert "ip6 daddr @home6 accept" in rules


def test_everything_else_coming_in_is_dropped():
    assert "policy drop;" in _chain("input")[0]
