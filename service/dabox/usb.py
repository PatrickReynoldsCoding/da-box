"""USB sticks: find them, mount them read-only, and list the mounted ones.

On the box, udisks2 mounts each stick under /media/<label> (shared mounts, see
install/files/99-dabox-usb.rules). In dev mode, every folder inside
DABOX_FAKE_USB_DIR counts as a mounted stick.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

# Read-only and no programs: a stick can only hold media for the box to play.
MOUNT_OPTIONS = "ro,noexec,nosuid,nodev"
# FAT and exFAT have no owners. Let every user (the kid user too) read the files.
_PERMISSION_OPTIONS_BY_FILESYSTEM = {"vfat": ",umask=0022", "exfat": ",umask=0022", "ntfs3": ",umask=0022", "ntfs": ",umask=0022"}
_MOUNTABLE_FILESYSTEMS = frozenset({"vfat", "exfat", "ntfs", "ntfs3", "ext4", "ext3", "ext2"})


class UsbStick(BaseModel):
    id: str
    label: str
    path: Path


class UsbBackend(Protocol):
    def sticks(self) -> list[UsbStick]: ...


def stick_id(device_key: str) -> str:
    return hashlib.sha1(device_key.encode()).hexdigest()[:12]


class BlockDevice(BaseModel):
    path: str
    filesystem: str | None
    label: str | None
    uuid: str | None
    mountpoint: str | None
    on_usb: bool


def parse_lsblk(output: str) -> list[BlockDevice]:
    """Parses `lsblk -J -o PATH,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN`. Partitions inherit TRAN from their disk."""
    devices: list[BlockDevice] = []

    def walk(entries: list[dict], parent_on_usb: bool) -> None:
        for entry in entries:
            on_usb = parent_on_usb or entry.get("tran") == "usb"
            devices.append(
                BlockDevice(
                    path=entry["path"],
                    filesystem=entry.get("fstype"),
                    label=entry.get("label"),
                    uuid=entry.get("uuid"),
                    mountpoint=entry.get("mountpoint"),
                    on_usb=on_usb,
                )
            )
            walk(entry.get("children", []), on_usb)

    walk(json.loads(output).get("blockdevices", []), False)
    return devices


def usb_filesystems(devices: list[BlockDevice]) -> list[BlockDevice]:
    return [device for device in devices if device.on_usb and device.filesystem in _MOUNTABLE_FILESYSTEMS]


def mount_options(filesystem: str) -> str:
    return MOUNT_OPTIONS + _PERMISSION_OPTIONS_BY_FILESYSTEM.get(filesystem, "")


class UdisksUsb:
    """Mounts new USB filesystems with udisksctl and reports the mounted ones."""

    def _devices(self) -> list[BlockDevice]:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "PATH,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return parse_lsblk(result.stdout)

    def _mount(self, device: BlockDevice) -> None:
        subprocess.run(
            ["udisksctl", "mount", "--no-user-interaction", "-b", device.path, "-o", mount_options(device.filesystem or "")],
            capture_output=True, text=True, timeout=30,
        )

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
