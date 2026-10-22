# da-box

A TV box for kids: films, music, a TV guide and retro games, with limits that a parent controls from a PIN-locked admin app on the home Wi-Fi. The box has no browser and no internet access for the kids' side.

See [DESIGN.md](DESIGN.md) for the full design.

## Parts

| Folder | What it is |
|---|---|
| `service/` | Python (FastAPI) package `dabox`: box API for the UI (localhost only), admin API + web app (PIN), library scan, settings, setup. Also `dabox.agent`, the player agent that controls mpv. |
| `ui/` | Godot 4 box UI (Home, Films, Music, first-run setup). Arrow keys + Enter + Esc, or a game controller. |
| `install/` | `install.sh` for a Debian-based box (Raspberry Pi OS Lite, Debian 12/13, arm64 or x86_64), plus systemd, PAM, polkit and firewall files. |
| `vm/` | `box-vm.sh`: a Debian arm64 VM on an Apple Silicon Mac (QEMU) that acts as the real box. |
| `dev/` | `run-dev.sh` (run everything on the Mac) and `make-test-media.sh` (test films and music with ffmpeg). |

## How it fits together

```
kid user (no network)          tvbox user (home network)
cage kiosk                     dabox-service :80
 └─ Godot UI ── HTTP ─────────▶ box API (/box/*, localhost only)
      │                         admin API + web app (/api/admin/*, PIN)  ◀── phone
      └─ HTTP ─▶ dabox-agent :8091 ─▶ mpv
```

## Run it on the Mac (dev mode)

Needs Homebrew `godot`, `mpv`, `ffmpeg` and Python 3.11+.

```sh
dev/run-dev.sh            # service + agent + UI in a window; admin app at http://localhost:8080
dev/run-dev.sh --reset    # start again from the first-run setup
```

Dev mode uses a fake network and does not change the Mac's time zone.

## Run it in the VM (the real box)

Needs Homebrew `qemu`.

```sh
vm/box-vm.sh start        # first time: downloads Debian and creates the VM
vm/box-vm.sh deploy       # copies the repo in and runs install/install.sh --vm --keep-ssh
vm/box-vm.sh media        # copies dev/media into the box
```

The QEMU window is the TV. Click it to give it the keyboard. The admin app is at http://localhost:8081, SSH is `vm/box-vm.sh ssh`. `vm/box-vm.sh keys ret` and `vm/box-vm.sh screenshot out.png` drive the VM from a script.

## Tests

```sh
cd service && .venv/bin/python -m pytest
```

UI smoke test (needs the dev service and agent running, see `dev/run-dev.sh`): it goes through the setup and the main screens and saves screenshots.

```sh
godot --path ui -- --service=http://127.0.0.1:8080 --agent=http://127.0.0.1:8091 --smoke-test=/tmp/shots
```

## Install on a real box

On a Raspberry Pi 5 with Raspberry Pi OS Lite (or any Debian-based machine), with internet access:

```sh
git clone <this repo> && cd da-box
sudo install/install.sh            # add --keep-ssh to keep SSH for maintenance
```

The box restarts into the first-run setup on the TV. After the setup, open http://tvbox.local on a phone on the same Wi-Fi.
