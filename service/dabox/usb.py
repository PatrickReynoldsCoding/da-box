"""USB sticks: find them, mount them read-only, and list the mounted ones.

On the box, udisks2 mounts each stick under /media/<label> (shared mounts, see
install/files/99-dabox-usb.rules). In dev mode, every folder inside
DABOX_FAKE_USB_DIR counts as a mounted stick.
"""

import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Read-only and no programs: a stick can only hold media for the box to play.
MOUNT_OPTIONS = "ro,noexec,nosuid,nodev"
# FAT and exFAT have no owners. Let every user (the kid user too) read the files.
_PERMISSION_OPTIONS_BY_FILESYSTEM = {"vfat": ",umask=0022", "exfat": ",umask=0022", "ntfs3": ",umask=0022", "ntfs": ",umask=0022"}
_MOUNTABLE_FILESYSTEMS = frozenset({"vfat", "exfat", "ntfs", "ntfs3", "ext4", "ext3", "ext2"})
_NOT_MEDIA_FILESYSTEMS = frozenset({"swap", "crypto_LUKS", "LVM2_member", "linux_raid_member"})


class UsbStick(BaseModel):
    id: str
    label: str
    path: Path


class UsbDrive(BaseModel):
    """A USB filesystem as the drive check shows it: mounted, not mounted (and why), or not readable."""

    id: str
    label: str
    device: str
    filesystem: str | None
    size_bytes: int | None
    mounted: bool
    supported: bool
    # Why it is not mounted: the error from udisks, or "not supported".
    problem: str | None


class UsbBackend(Protocol):
    def sticks(self) -> list[UsbStick]: ...
    def drives(self) -> list[UsbDrive]: ...


def stick_id(device_key: str) -> str:
    return hashlib.sha1(device_key.encode()).hexdigest()[:12]


class BlockDevice(BaseModel):
    path: str
    filesystem: str | None
    label: str | None
    uuid: str | None
    mountpoint: str | None
    on_usb: bool
    size_bytes: int | None = None


LSBLK_COLUMNS = "PATH,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN,PKNAME,SIZE"


def parse_lsblk(output: str) -> list[BlockDevice]:
    """Parses `lsblk -J -o LSBLK_COLUMNS`. Partitions inherit TRAN from their disk.

    lsblk prints a tree (partitions as "children") on some systems and a flat list on others
    (util-linux 2.39 on Linux Mint 22), so the parent is also found by PKNAME, its kernel name.
    """
    entries: list[tuple[dict, bool]] = []

    def walk(level: list[dict], parent_on_usb: bool) -> None:
        for entry in level:
            on_usb = parent_on_usb or entry.get("tran") == "usb"
            entries.append((entry, on_usb))
            walk(entry.get("children", []), on_usb)

    walk(json.loads(output).get("blockdevices", []), False)
    usb_names = {Path(entry["path"]).name for entry, on_usb in entries if on_usb}
    return [
        BlockDevice(
            path=entry["path"],
            filesystem=entry.get("fstype"),
            label=entry.get("label"),
            uuid=entry.get("uuid"),
            mountpoint=entry.get("mountpoint"),
            on_usb=on_usb or entry.get("pkname") in usb_names,
            size_bytes=_size(entry.get("size")),
        )
        for entry, on_usb in entries
    ]


def _size(raw: object) -> int | None:
    """lsblk -b gives the size in bytes, as a number or a string."""
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def usb_filesystems(devices: list[BlockDevice]) -> list[BlockDevice]:
    return [device for device in devices if device.on_usb and device.filesystem in _MOUNTABLE_FILESYSTEMS]


def unsupported_usb_filesystems(devices: list[BlockDevice]) -> list[BlockDevice]:
    """USB filesystems the box cannot read (HFS+ or APFS from a Mac, btrfs, ...). Swap and
    encrypted partitions are not media, so they are not listed."""
    return [
        device for device in devices
        if device.on_usb and device.filesystem and device.filesystem not in _MOUNTABLE_FILESYSTEMS
        and device.filesystem not in _NOT_MEDIA_FILESYSTEMS
    ]


def mount_options(filesystem: str) -> str:
    return MOUNT_OPTIONS + _PERMISSION_OPTIONS_BY_FILESYSTEM.get(filesystem, "")


# A drive that would not mount is tried again after this long, not on every poll.
MOUNT_RETRY_SECONDS = 60.0


def drive_label(device: BlockDevice) -> str:
    return device.label or (Path(device.mountpoint).name if device.mountpoint else Path(device.path).name)


def drive_views(devices: list[BlockDevice], mount_errors: dict[str, str]) -> list[UsbDrive]:
    views = [
        UsbDrive(
            id=stick_id(device.uuid or device.path), label=drive_label(device), device=device.path,
            filesystem=device.filesystem, size_bytes=device.size_bytes, mounted=device.mountpoint is not None,
            supported=True, problem=None if device.mountpoint else mount_errors.get(device.path),
        )
        for device in usb_filesystems(devices)
    ]
    views += [
        UsbDrive(
            id=stick_id(device.uuid or device.path), label=drive_label(device), device=device.path,
            filesystem=device.filesystem, size_bytes=device.size_bytes, mounted=False, supported=False,
            problem=f"The box cannot read {device.filesystem} drives. Use FAT32, exFAT, NTFS or ext4.",
        )
        for device in unsupported_usb_filesystems(devices)
    ]
    return views


class UdisksUsb:
    """Mounts new USB filesystems with udisksctl and reports the mounted ones."""

    def __init__(self) -> None:
        # Device path -> (the error, when it was tried).
        self._mount_errors: dict[str, tuple[str, float]] = {}

    def _devices(self) -> list[BlockDevice]:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return parse_lsblk(result.stdout)

    def _mount(self, device: BlockDevice) -> None:
        failed = self._mount_errors.get(device.path)
        if failed is not None and time.monotonic() - failed[1] < MOUNT_RETRY_SECONDS:
            return
        result = subprocess.run(
            ["udisksctl", "mount", "--no-user-interaction", "-b", device.path, "-o", mount_options(device.filesystem or "")],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout).strip() or f"udisksctl exited with {result.returncode}"
            log.warning("Could not mount USB %s: %s", device.path, error)
            self._mount_errors[device.path] = (error, time.monotonic())
        else:
            self._mount_errors.pop(device.path, None)

    def drives(self) -> list[UsbDrive]:
        try:
            devices = self._devices()
        except (OSError, subprocess.SubprocessError):
            return []
        return drive_views(devices, {path: error for path, (error, _) in self._mount_errors.items()})

    def sticks(self) -> list[UsbStick]:
        try:
            filesystems = usb_filesystems(self._devices())
        except (OSError, subprocess.SubprocessError):
            return []
        for device in filesystems:
            if device.mountpoint is None:
                self._mount(device)
        sticks: list[UsbStick] = []
        for device in usb_filesystems(self._devices()):
            if device.mountpoint:
                sticks.append(
                    UsbStick(
                        id=stick_id(device.uuid or device.path),
                        label=device.label or Path(device.mountpoint).name,
                        path=Path(device.mountpoint),
                    )
                )
        return sticks


class FakeUsb:
    """Dev mode: each folder in `root` is a mounted stick."""

    def __init__(self, root: Path | None) -> None:
        self._root = root

    def sticks(self) -> list[UsbStick]:
        if self._root is None or not self._root.is_dir():
            return []
        return [
            UsbStick(id=stick_id(str(folder)), label=folder.name, path=folder)
            for folder in sorted(self._root.iterdir())
            if folder.is_dir() and not folder.name.startswith(".")
        ]

    def drives(self) -> list[UsbDrive]:
        return [
            UsbDrive(id=stick.id, label=stick.label, device=str(stick.path), filesystem="vfat", size_bytes=None,
                     mounted=True, supported=True, problem=None)
            for stick in self.sticks()
        ]
