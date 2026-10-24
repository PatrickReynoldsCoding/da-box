"""Every kind of USB drive in tests/drives/ (real samples and typical ones): which partitions
the box finds and mounts, which it names as not supported, and which the udev rule shares
under /media/<label> so the kid user can read them (DESIGN_CORRECTIONS_2.md, part 6)."""

import fnmatch
import json
import re
from pathlib import Path

import pytest

from dabox.usb import parse_lsblk, stick_id, unsupported_usb_filesystems, usb_filesystems

DRIVES = Path(__file__).parent / "drives"
UDEV_RULES = Path(__file__).parents[2] / "install" / "files" / "99-dabox-usb.rules"
CASES = sorted(DRIVES.glob("*.json"))


def load(case: Path) -> dict:
    return json.loads(case.read_text())


def test_there_are_real_samples() -> None:
    real = [case.name for case in CASES if load(case)["source"].startswith("real")]
    assert len(real) >= 2, real


@pytest.mark.parametrize("case", CASES, ids=[case.stem for case in CASES])
def test_finds_the_usb_filesystems(case: Path) -> None:
    sample = load(case)
    devices = parse_lsblk(json.dumps(sample["lsblk"]))
    assert [device.path for device in usb_filesystems(devices)] == sample["expect"]["usb_filesystems"]
    assert [device.path for device in unsupported_usb_filesystems(devices)] == sample["expect"]["unsupported"]


@pytest.mark.parametrize("case", CASES, ids=[case.stem for case in CASES])
def test_every_drive_gets_its_own_id(case: Path) -> None:
    devices = usb_filesystems(parse_lsblk(json.dumps(load(case)["lsblk"])))
    ids = [stick_id(device.uuid or device.path) for device in devices]
    assert len(set(ids)) == len(ids)


# ---- The udev rule ----

_MATCH = re.compile(r'^ENV\{(?P<key>\w+)\}==\"(?P<pattern>[^\"]*)\"$')
_ASSIGN = re.compile(r'^ENV\{(?P<key>\w+)\}=\"(?P<value>[^\"]*)\"$')


def apply_udev_rules(rules: str, properties: dict[str, str]) -> dict[str, str]:
    """A small udev: rules with ENV{KEY}=="glob" matches and ENV{KEY}="value" assignments,
    which is all 99-dabox-usb.rules uses. Any other kind of key fails the test."""
    result = dict(properties)
    for line in rules.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        matches, assignments = [], []
        for part in (part.strip() for part in line.split(",")):
            if found := _MATCH.match(part):
                matches.append((found["key"], found["pattern"]))
            elif found := _ASSIGN.match(part):
                assignments.append((found["key"], found["value"]))
            else:
                raise AssertionError(f"The test's udev does not know this rule part: {part}")
        if all(fnmatch.fnmatchcase(result.get(key, ""), pattern) for key, pattern in matches):
            result.update(assignments)
    return result


@pytest.mark.parametrize("case", CASES, ids=[case.stem for case in CASES])
def test_udev_rule_shares_usb_filesystems_only(case: Path) -> None:
    sample = load(case)
    rules = UDEV_RULES.read_text()
    shared = sorted(
        device for device, properties in sample["udev"].items()
        if apply_udev_rules(rules, properties).get("UDISKS_FILESYSTEM_SHARED") == "1"
    )
    assert shared == sorted(sample["expect"]["shared"])


def test_udev_rule_matches_the_toshiba_disk_that_reports_ata() -> None:
    """The bug found on the Mint laptop: ID_BUS=ata, but connected through USB."""
    properties = load(DRIVES / "mint-laptop-toshiba-ata-bridge.json")["udev"]["/dev/sda1"]
    assert properties["ID_BUS"] == "ata"
    assert apply_udev_rules(UDEV_RULES.read_text(), properties)["UDISKS_FILESYSTEM_SHARED"] == "1"
