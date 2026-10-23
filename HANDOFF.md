# Handoff: installer fails on desktop distros (Linux Mint)

Status as of 2026-10-23. Work in progress on branch `fix/desktop-installs` (not merged into `main`).

## The problem

`sudo install/install.sh` on a Linux Mint machine froze the screen at the end of the install, and after a restart the screen stayed black.

## Cause (reproduced in a VM)

The installer never turned off the desktop login screen (LightDM on Mint), and at the end it started the kiosk (`dabox-kiosk.service`: cage on tty1) over the running desktop. logind switched the seat to the kiosk's tty1 session, but the root Xorg server kept the display, so cage could not start:

```
cage: [ERROR] [backend/backend.c:107] Timeout waiting session to become active
cage: [ERROR] [backend/backend.c:359] Failed to start a DRM session
cage: [ERROR] [../cage.c:298] Unable to create the wlroots backend
```

The screen froze on the last desktop frame, and keyboard input went to the dead kiosk. The installer had also masked all gettys and set `kernel.sysrq=0`, so there was no way out. After a restart, LightDM and the kiosk both start and fight over the display. The kiosk crash-loops (`Restart=always`); with the old `RestartSec=1` and systemd's default start limit it can also give up for good and leave a black tty1.

## What changed (on branch `fix/desktop-installs`)

- `install/install.sh`
  - `check_system`: stops with a message, before changing anything, if there is no apt/dpkg or no systemd; prints the distro.
  - `turn_off_desktop`: disables and masks the display manager (`display-manager.service` and known ones: gdm, gdm3, lightdm, sddm, ...), and records each one in `/etc/dabox/turned-off`.
  - `start_kiosk`: if a desktop or graphical session was running, it does not start the kiosk; it prints "Restart the machine: sudo reboot".
  - Packages: checks every package with `apt-cache policy` first. It picks `polkitd` or `policykit-1` (Ubuntu 22.04 / Mint 21), skips optional packages that are missing (libretro cores, libdecor) with a warning, and gives an Ubuntu "universe" hint. `DPkg::Lock::Timeout=600` makes it wait for Mint's update manager or unattended-upgrades instead of failing.
  - Python 3.11+: uses python3 or python3.11-3.13 (installing `python3.X` + `python3.X-venv` if needed), and makes the venv again if it was built with an old Python.
  - Groups: `add_to_groups` adds only groups that exist (`render` can be missing).
  - `install_godot`: checks that Godot actually runs. Godot 4.7 aborts silently on CPUs without SSE4.2/POPCNT, including QEMU's default `qemu64` CPU.
  - `import_ui`: fails if `.godot/imported` is empty. Before, `|| true` hid the error and the UI could not load its assets.
  - `check_graphics`: uses software rendering if there is no `/dev/dri/renderD*`. With NVIDIA it writes `nvidia-drm modeset=1` and sets `WLR_NO_HARDWARE_CURSORS=1`.
  - Turns off ufw and firewalld (they would block the admin app), records them in `turned-off`, and warns about Docker/libvirt.
  - polkit < 0.106: also installs `install/files/50-dabox.pkla`. The admin app's "System update" cannot work there.
  - Disables `ssh.socket` as well as `ssh.service` (Ubuntu socket-activates SSH).
  - Replaces the existing `127.0.1.1` line in `/etc/hosts` instead of adding a second one.
- `install/files/dabox-kiosk.service`: `StartLimitIntervalSec=0` and `RestartSec=2` (never gives up). An `ExecStartPre` waits up to 30 s for `loginctl show-seat seat0 -p CanGraphical` to be yes (the GPU driver can load late). It is also ordered after `plymouth-quit.service` and `systemd-logind.service`.
- `install/files/50-dabox.pkla` (new): the polkit rules for old polkit.
- `install/uninstall.sh` (new): stops da-box and removes the firewall, console lock-down, PAM/polkit/udev/sysctl files and units. It turns back on everything listed in `/etc/dabox/turned-off`. `--purge` also deletes the code, data and users.
- `vm/box-vm.sh`: now works on Windows (Git Bash, QEMU + WHPX), Linux (KVM) and the Mac (unchanged behaviour). `DABOX_VM=desktop` gives a second VM: Ubuntu 24.04 + XFCE + LightDM/slick-greeter + plymouth + ufw, like Mint 22. Also new: `save`/`restore`/`snapshots`, `kill`, the monitor over TCP (via python), and the repo copied with tar over SSH (no rsync on Windows).
- `.gitattributes` (new): forces LF. The Windows checkout had `core.autocrlf=true`, which turns the scripts into CRLF and breaks them on Linux.
- `.gitignore`: `vm/work-*/`. `README.md`: VM hosts table, desktop VM, desktop installs, uninstall, recovery steps.

## Verified

- Debian 13 VM (`vm/box-vm.sh deploy`): install OK, kiosk shows "Welcome to da-box" setup step 1, admin app returns HTTP 200, a second install run is OK.
- Desktop VM with the **original** installer: freeze and boot fight reproduced (see Cause).
- Desktop VM with the **fixed** installer: got as far as installing Godot. The package step passed with no warnings on Ubuntu 24.04, so all package names resolve there. Then the run was stopped on purpose (pause).
- Service tests on Windows: 156 pass, 3 fail on Windows-only path issues (`test_agent.py` x2, `test_maintenance.py::test_restore_rejects_bad_files`). They needed `pip install tzdata` (Windows has no IANA time zone data).

## What is left

1. **Main test: the fixed installer on the desktop VM.** The VM's last install was stopped halfway, so start from the snapshot:
   ```sh
   export DABOX_VM=desktop
   vm/box-vm.sh stop            # or: vm/box-vm.sh kill
   vm/box-vm.sh restore desktop-ready
   vm/box-vm.sh start           # wait for the LightDM greeter, then:
   vm/box-vm.sh keys d e v ret  # log in as dev/dev, like a user at the desktop
   vm/box-vm.sh deploy
   ```
   Expect: "Turning off the desktop login screen (lightdm.service)", "Turning off ufw", and at the end "Restart the machine". The desktop must keep working (no freeze). Then `vm/box-vm.sh stop` + `start` (not a warm reboot) and check the kiosk shows the setup screen: `vm/box-vm.sh screenshot out.png`, plus `journalctl -u dabox-kiosk` and `loginctl list-sessions` over `vm/box-vm.sh ssh`.
2. **Test `install/uninstall.sh`** on the desktop VM: after it and a restart, the LightDM greeter comes back, ufw is active again and the gettys work.
3. **Run the service tests on Linux**, in the VM or on any Linux machine: `cd service && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest`. If the 3 Windows failures matter, either skip them on Windows or add `tzdata; sys_platform == "win32"` to the dev extras.
4. **Not tested yet:**
   - Ubuntu 22.04 / Mint 21: `policykit-1` + `.pkla`, python3.11 from jammy-updates, cage 0.1.4. A jammy VM could be added as a third `DABOX_VM` flavour.
   - Debian 12, Raspberry Pi OS (Lite and desktop), GDM (Ubuntu desktop uses tty1 for its greeter), NVIDIA hardware.
   - The tinyproxy unit on older releases: check it starts with our `tinyproxy.conf`. Debian's unit may expect `PidFile /run/tinyproxy/tinyproxy.pid`.
5. **The user's real Mint machine:** recover it with the README's "If the screen is black" steps, or by SSH if it was installed with `--keep-ssh`. Then pull and run the fixed installer, or `install/uninstall.sh` to get the desktop back.
6. **Merge** `fix/desktop-installs` into `main` once 1–3 pass. Before that, re-check `vm/box-vm.sh` on the Mac: the monitor moved from a Unix socket to TCP, and repo copies use tar instead of rsync. The Mac VM's `vm/work` disk still works.
7. **Maybe later:** the installer supports apt-based distros only. Fedora, Arch or openSUSE would need their own package lists (libretro cores and cage differ), so it stops with a message there.

## VM gotchas (Windows host)

- QEMU: `scoop install qemu`. WHPX worked on this machine. WSL2 has no nested KVM here, so the VM runs from Git Bash, not WSL.
- The VM needs `-cpu max` (already in the script). With the default `qemu64` CPU, Godot aborts.
- Do not warm-reboot the VMs from inside: it hangs in the firmware. Use `stop` + `start`.
- QEMU can take up to about a minute to open its monitor port; `start` waits up to 120 s.
- The QEMU monitor takes one client at a time; `monitor_python` retries.
- Snapshots work only with the VM stopped. The desktop VM has `desktop-ready` (clean desktop, before any da-box install).
- Base images are in `vm/work/` and `vm/work-desktop/` (git-ignored). Check downloads with `qemu-img check`: the first Debian download came down truncated.
