# da-box

A TV box for kids: films, music, a TV guide and retro games, with limits that a parent controls from a PIN-locked admin app on the home Wi-Fi. The box has no browser and no internet access for the kids' side.

See [DESIGN.md](DESIGN.md) for the full design.

## Parts

| Folder | What it is |
|---|---|
| `service/` | Python (FastAPI) package `dabox`: box API for the UI (localhost only), admin API + web app (PIN), library scan, settings, setup. Also `dabox.agent`, the player agent that controls mpv. |
| `ui/` | Godot 4 box UI (Home, TV guide, channels, Films, Music with artists, songs, search and playlists, Games, Copy from USB, first-run setup, sleeping screen). Arrow keys + Enter + Esc, or a game controller (stick or d-pad to move, A = OK, B or Back/Select = back). |
| `install/` | `install.sh` for an apt-based box (Raspberry Pi OS, Debian 12+, Ubuntu 22.04+, Linux Mint 21+; arm64 or x86_64), `uninstall.sh`, plus systemd, PAM, polkit and firewall files. |
| `vm/` | `box-vm.sh`: a QEMU VM (Mac, Windows or Linux host) that acts as the real box, and a desktop VM like Linux Mint. |
| `dev/` | `run-dev.sh` (run everything on the Mac) and `make-test-media.sh` (test films and music with ffmpeg). |

## How it fits together

```
kid user (no network)          tvbox user (home network)
cage kiosk                     dabox-service :80
 └─ Godot UI ── HTTP ─────────▶ box API (/box/*, localhost only)
      │                         admin API + web app (/api/admin/*, PIN)  ◀── phone
      └─ HTTP ─▶ dabox-agent :8091 ─▶ mpv
```

## Media

**USB drives can have any folders.** The box reads every folder (not `$RECYCLE.BIN`, `System Volume Information` and the like) and finds:

- **Videos.** A folder with one video is one video, named after the folder; a loose video is named after its file. A folder with several videos is a **group**, played in order (by `S01E02` markers, else by name with numbers as numbers); sub-folders such as `Season 1` or `Extras` are sections of it. Release tags (`1080p`, `x265`, `WEB-DL`, …) are taken out of names. There are no "films" and "TV": the Home tile is **Videos**.
- **Music**, by its tags, like iTunes. Without tags: the artist from "Artist - Title" in the file name, else *Unknown Artist*; the album *Unknown Album*.
- **Games**, by extension (`.nes .sfc .smc .gb .gbc .gba .md .gen .smd .cue .chd .pbp`; `.zip` with one game inside; `.bin` in a Mega Drive folder). Mega Drive and PlayStation need `install.sh --extra-cores`.

The admin app (Home → USB drives) and the TV (USB tile, parent mode) show what the box found on each drive, what it skipped, and why a drive is not read (for example a Mac drive).

**Copy from USB:** turn on parent mode, plug the drive in, and pick the USB tile on Home. Tick kinds (Videos, Albums, Games) or single items, or press **Copy everything**. The box checks the space, copies in the background (the box can be used meanwhile), skips what it already has (by the files' content, not their names), and puts each item in its own layout:

```
Videos/<Name>/<file>.mp4        (+ its pictures, .nfo and subtitles)
Videos/<Group>/...              (a group, with its sections)
Music/<Artist>/<Album>/07 <Song>.mp3   (+ cover.jpg)
Games/<system>/<Game>.nes       systems: nes snes gb gbc gba megadrive psx
```

The box's older `Films/` and `TV/` folders are still read, and their items keep their ids (channels, hidden items and art stay).

## Limits

The service enforces the limits, not the UI. It checks what the player agent is doing every 2 seconds, counts video and game time, warns at 5 and 1 minutes, saves and stops games at the end of the game window, and shuts the box down after the quota is used up (once a day) and at bedtime. A video starts only if it can end before the quota (plus the overrun allowance) and bedtime. The night lasts from bedtime until 06:00. Parent mode switches all limits off. Every action is logged: `journalctl -u dabox-service | grep "Limits at"`.

## Admin app

Open http://tvbox.local on a phone on the home Wi-Fi and enter the PIN. Tabs: Home (today's time, extra time, parent mode, USB sticks), Content (hide/show, art and details, copy from USB, playlists), Channels, Guide, Upload, Activity (last 7 days), Settings (limits, colour theme and sounds, posters and info: TMDB key and optional ScreenScraper account, PIN, backup and restore, system update, da-box version and update, run setup again, remove da-box). On the TV, Settings (the gear on Home) has Update da-box and Posters and info too; keys can be typed there or pasted on a phone through a QR code.

## Run it on the Mac (dev mode)

Needs Homebrew `godot`, `mpv`, `ffmpeg` and Python 3.11+.

```sh
dev/run-dev.sh            # service + agent + UI in a window; admin app at http://localhost:8080
dev/run-dev.sh --reset    # start again from the first-run setup
```

Dev mode uses a fake network and does not change the Mac's time zone. The first start makes test media with real lengths (a few minutes; `SECONDS_PER_FILM=90` for short films). Every folder in `dev/usb` acts as a USB stick.

## Run it in the VM (the real box)

Needs QEMU:

| Host | Install | VM |
|---|---|---|
| Apple Silicon Mac | `brew install qemu` | Debian 13 arm64 (HVF) |
| Windows | `scoop install qemu`, and turn on **Windows Hypervisor Platform** in "Turn Windows features on or off". Run the script from Git Bash. | Debian 13 x86_64 (WHPX) |
| Linux | `apt install qemu-system-x86` | Debian 13 x86_64 (KVM) |

```sh
vm/box-vm.sh start        # first time: downloads Debian and creates the VM
vm/box-vm.sh deploy       # copies the repo in and runs install/install.sh --vm --keep-ssh
vm/box-vm.sh media        # copies dev/media into the box
```

The QEMU window is the TV. Click it to give it the keyboard. The admin app is at http://localhost:8081, SSH is `vm/box-vm.sh ssh`. `vm/box-vm.sh keys ret` and `vm/box-vm.sh screenshot out.png` drive the VM from a script, and `vm/box-vm.sh usb-in stick.img` / `usb-out` plug a disk image in and out as a USB stick. `vm/box-vm.sh save clean` / `restore clean` keep and go back to a disk snapshot (with the VM stopped).

**Desktop VM.** `DABOX_VM=desktop vm/box-vm.sh start` (and `deploy`, `ssh`, ...) works on a second VM: Ubuntu 24.04 with a LightDM desktop, a boot splash and ufw, like Linux Mint 22. Use it to test installing over a desktop distro. Admin app on http://localhost:8082.

Do not reboot the Mac VM from inside: QEMU's firmware can fail on a warm reboot. Use `vm/box-vm.sh stop`, then `start`.

## Tests

```sh
cd service && .venv/bin/python -m pytest
```

UI key tests (no service needed): arrow keys and focus on the setup, Copy from USB and Music screens.

```sh
godot --headless --path ui res://tests/key_tests.tscn
```

UI smoke test (needs the dev service and agent running, see `dev/run-dev.sh`): it goes through the setup and the main screens and saves screenshots.

```sh
godot --path ui -- --service=http://127.0.0.1:8080 --agent=http://127.0.0.1:8091 --smoke-test=/tmp/shots
```

## Install on a real box

On a Raspberry Pi 5 with Raspberry Pi OS Lite, or any apt-based Linux (Debian 12+, Ubuntu 22.04+, Linux Mint 21+, LMDE 6+), arm64 or x86_64, with internet access:

```sh
git clone <this repo> && cd da-box
sudo install/install.sh            # add --keep-ssh to keep SSH for maintenance
```

The box shows the first-run setup on the TV. After the setup, open http://tvbox.local on a phone on the same Wi-Fi.

**On a machine with a desktop** (Mint, Ubuntu, Raspberry Pi OS with desktop) the box takes the place of the desktop: the installer turns off the login screen (LightDM, GDM, ...) and ufw/firewalld, and asks you to restart at the end instead of starting the kiosk over the running desktop. Without a working GPU driver it uses software rendering. With an NVIDIA driver, if the screen stays black after the restart, run the installer again with `--vm`.

To get the desktop back: in the admin app, Settings → **Remove da-box** (asks for the PIN and the word REMOVE, then restarts into Linux). Or by hand: `sudo install/uninstall.sh` (add `--purge` to also delete the code, media, settings and users), then restart. Both give the machine its old name and start-up target back (saved by `install.sh` from this version on).

**If the screen is black and there is no SSH** (tried on a real Linux Mint laptop):

1. Hold Shift (or press Esc **once** on UEFI machines) while the machine starts. If you land at a `grub>` prompt, type `normal` and press an arrow key at once so the menu stays.
2. On the first entry press `e`, add ` init=/bin/bash` at the end of the line that starts with `linux`, and press Ctrl+X.
3. At the `#` prompt run each line on its own (Enter after each). `systemctl` does not work at this prompt, so the files are removed directly:
   ```sh
   mount -o remount,rw /
   rm -f /etc/systemd/system/dabox-kiosk.service /etc/systemd/system/*.wants/dabox-kiosk.service
   rm -f /etc/systemd/system/*.wants/nftables.service
   echo 'flush ruleset' > /etc/nftables.conf
   sync
   ```
4. Hold the power button to turn off, start again and choose the normal entry. Back in the desktop, run `sudo install/uninstall.sh`.

Other Linux families (Fedora, Arch, openSUSE) are not supported: the installer stops with a message before changing anything.

## Update da-box

On the TV, the small **Settings** button at the bottom right of Home has **Update da-box** (no parent mode needed; it asks "Are you sure?" first). The admin app has the same under Settings → *da-box version*. Both show the installed version and the newest [GitHub release](https://github.com/PatrickReynoldsCoding/da-box/releases), and install it on request: `dabox-upgrade.service` (root) opens the firewall, downloads the release's source, and runs its `install/install.sh` with the options saved at install time (`/etc/dabox/update.env`). Settings, media and users stay. The TV restarts at the end. The log: `journalctl -u dabox-upgrade`.

The box only sees **releases**, not branches. To publish one from `main`:

```sh
gh release create v0.2.0 --target main --generate-notes
```

Use `vMAJOR.MINOR.PATCH` tags: the box compares the numbers. A box installed from a git checkout shows `git describe` as its version (for example `v0.2.0-3-gabc1234`) and is offered only newer releases. `DABOX_UPDATE_REPO=owner/name sudo install/install.sh` takes updates from a fork.
