#!/usr/bin/env bash
# Installs da-box on a Debian-based machine (Raspberry Pi OS Lite, Debian 12/13, arm64 or x86_64).
# Run as root from a checkout of the repo:  sudo install/install.sh [options]
#
# Options:
#   --keep-ssh     keep the SSH server running and allow SSH from the home network
#   --vm           settings for a virtual machine without a GPU (software rendering)
#   --extra-cores  also download Mega Drive and PlayStation emulators from the
#                  libretro build server (Debian does not package them)
#
# The machine needs internet access while this runs. At the end the firewall
# closes the internet for everything except time sync and DNS.
set -euo pipefail

GODOT_VERSION="4.7.2"
INSTALL_DIR="/opt/dabox"
MEDIA_DIR="/srv/dabox/media"
DATA_DIR="/var/lib/dabox"
CONFIG_DIR="/etc/dabox"
SERVICE_USER="tvbox"
KID_USER="kid"
MEDIA_GROUP="dabox-media"
HOSTNAME_FOR_BOX="tvbox"

keep_ssh=false
vm=false
extra_cores=false
for argument in "$@"; do
  case "$argument" in
    --keep-ssh) keep_ssh=true ;;
    --vm) vm=true ;;
    --extra-cores) extra_cores=true ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Run this as root (sudo)." >&2; exit 1; }
repo="$(cd "$(dirname "$0")/.." && pwd)"
templates="$repo/install/files"

step() { echo; echo "==> $*"; }

godot_architecture() {
  case "$(dpkg --print-architecture)" in
    arm64) echo "arm64" ;;
    amd64) echo "x86_64" ;;
    *) echo "Unsupported CPU architecture: $(dpkg --print-architecture)" >&2; exit 1 ;;
  esac
}

open_firewall_for_install() {
  # A second run needs the internet for packages. The firewall is written again at the end.
  if nft list table inet dabox >/dev/null 2>&1; then
    step "Opening the firewall while installing"
    nft delete table inet dabox
  fi
}

install_packages() {
  step "Installing packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    cage xwayland mpv \
    python3 python3-venv python3-pip \
    avahi-daemon libnss-mdns nftables network-manager polkitd systemd-timesyncd \
    libgl1-mesa-dri libegl1 libgles2 libgl1 libwayland-client0 libwayland-cursor0 \
    libwayland-egl1 libxkbcommon0 libdecor-0-0 fontconfig fonts-dejavu-core \
    alsa-utils ca-certificates curl unzip rsync udisks2 tinyproxy ffmpeg \
    retroarch libretro-core-info libretro-nestopia libretro-bsnes-mercury-performance \
    libretro-gambatte libretro-mgba
}

create_users() {
  step "Creating users and folders"
  getent group "$MEDIA_GROUP" >/dev/null || groupadd --system "$MEDIA_GROUP"
  id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  id "$KID_USER" >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin "$KID_USER"
  usermod -aG "$MEDIA_GROUP" "$SERVICE_USER"
  # video/render: the screen; input: game controllers; audio: sound.
  usermod -aG "$MEDIA_GROUP,video,render,input,audio" "$KID_USER"
  passwd --lock "$KID_USER" >/dev/null

  install -d -o "$SERVICE_USER" -g "$MEDIA_GROUP" -m 2775 "$MEDIA_DIR" "$MEDIA_DIR/Films" "$MEDIA_DIR/Music" "$MEDIA_DIR/TV" "$MEDIA_DIR/Games"
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
  install -d -m 0755 "$CONFIG_DIR"
}

install_code() {
  step "Installing the da-box code"
  install -d "$INSTALL_DIR"
  rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.egg-info' "$repo/service/" "$INSTALL_DIR/service/"
  rsync -a --delete --exclude .godot --exclude tests "$repo/ui/" "$INSTALL_DIR/ui/"
  install -d "$INSTALL_DIR/bin"
  install -m 0755 "$templates/dabox-session" "$INSTALL_DIR/bin/dabox-session"

  [[ -x "$INSTALL_DIR/venv/bin/python" ]] || python3 -m venv "$INSTALL_DIR/venv"
  "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
  "$INSTALL_DIR/venv/bin/pip" install --quiet "$INSTALL_DIR/service"
}

install_godot() {
  local architecture zip_name binary
  architecture="$(godot_architecture)"
  binary="$INSTALL_DIR/godot/godot"
  if [[ -x "$binary" ]] && "$binary" --headless --version 2>/dev/null | grep -q "^$GODOT_VERSION"; then
    return
  fi
  step "Installing Godot $GODOT_VERSION ($architecture)"
  zip_name="Godot_v${GODOT_VERSION}-stable_linux.${architecture}.zip"
  install -d "$INSTALL_DIR/godot"
  curl -sSfL -o "/tmp/$zip_name" "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}-stable/$zip_name"
  unzip -o -q "/tmp/$zip_name" -d "$INSTALL_DIR/godot"
  mv "$INSTALL_DIR/godot/Godot_v${GODOT_VERSION}-stable_linux.${architecture}" "$binary"
  rm -f "/tmp/$zip_name"
}

install_games() {
  step "Setting up RetroArch"
  install -d "$INSTALL_DIR/retroarch" "$INSTALL_DIR/cores"
  local password_file="$CONFIG_DIR/retroarch-kiosk-password"
  [[ -f "$password_file" ]] || (umask 077; head -c 18 /dev/urandom | base64 > "$password_file")
  sed -e "s|@KIOSK_PASSWORD@|$(cat "$password_file")|" -e "s|@CORE_DIR@|$INSTALL_DIR/cores|" \
    "$templates/retroarch.cfg" > "$INSTALL_DIR/retroarch/retroarch.cfg"
  chmod 0644 "$INSTALL_DIR/retroarch/retroarch.cfg"

  if $extra_cores; then
    local architecture core
    architecture="$(godot_architecture | sed 's/arm64/aarch64/')"
    for core in genesis_plus_gx pcsx_rearmed; do
      step "Downloading the $core core"
      curl -sSfL -o "/tmp/$core.zip" "https://buildbot.libretro.com/nightly/linux/$architecture/latest/${core}_libretro.so.zip"
      unzip -o -q "/tmp/$core.zip" -d "$INSTALL_DIR/cores"
      rm -f "/tmp/$core.zip"
    done
  fi

  # One core folder: links to Debian's cores, next to any downloaded ones.
  local debian_core
  for debian_core in "$(debian_core_dir)"/*_libretro.so; do
    [[ -e "$debian_core" ]] && ln -sf "$debian_core" "$INSTALL_DIR/cores/"
  done
}

debian_core_dir() {
  case "$(dpkg --print-architecture)" in
    arm64) echo "/usr/lib/aarch64-linux-gnu/libretro" ;;
    amd64) echo "/usr/lib/x86_64-linux-gnu/libretro" ;;
  esac
}

core_dirs() {
  echo "$INSTALL_DIR/cores"
}

import_ui() {
  step "Preparing the box UI"
  # Import once here, so the kid user never needs write access to the UI folder.
  "$INSTALL_DIR/godot/godot" --headless --path "$INSTALL_DIR/ui" --import >/dev/null 2>&1 || true
  chown -R root:root "$INSTALL_DIR"
}

write_config() {
  step "Writing configuration"
  local mpv_arguments="" renderer_lines=""
  if $vm; then
    # No GPU in the VM: draw with the CPU.
    mpv_arguments="--vo=wlshm --hwdec=no"
    renderer_lines=$'WLR_RENDERER=pixman\nWLR_NO_HARDWARE_CURSORS=1\nLIBGL_ALWAYS_SOFTWARE=1'
  fi
  cat > "$CONFIG_DIR/kiosk.env" <<EOF
DABOX_PLAY_ROOTS=$MEDIA_DIR:/media
DABOX_CORE_DIRS=$(core_dirs)
DABOX_RETROARCH=/usr/bin/retroarch
DABOX_RETROARCH_CONFIG=$INSTALL_DIR/retroarch/retroarch.cfg
DABOX_MPV_ARGS=$mpv_arguments
$renderer_lines
EOF
  cat > "$CONFIG_DIR/service.env" <<EOF
DABOX_MEDIA_DIR=$MEDIA_DIR
DABOX_DATA_DIR=$DATA_DIR
DABOX_PORT=80
DABOX_CORE_DIRS=$(core_dirs)
HTTPS_PROXY=http://127.0.0.1:8888
NO_PROXY=127.0.0.1,localhost
EOF
}

install_system_files() {
  step "Installing system services, PAM, polkit and firewall"
  install -m 0644 "$templates/dabox-service.service" /etc/systemd/system/dabox-service.service
  install -m 0644 "$templates/dabox-kiosk.service" /etc/systemd/system/dabox-kiosk.service
  install -m 0644 "$templates/pam-dabox-kiosk" /etc/pam.d/dabox-kiosk
  install -d /etc/polkit-1/rules.d
  install -m 0644 "$templates/50-dabox.rules" /etc/polkit-1/rules.d/50-dabox.rules
  install -m 0644 "$templates/99-dabox-sysctl.conf" /etc/sysctl.d/99-dabox.conf
  install -m 0644 "$templates/99-dabox-usb.rules" /etc/udev/rules.d/99-dabox-usb.rules
  install -m 0644 "$templates/tinyproxy.conf" /etc/tinyproxy/tinyproxy.conf
  install -m 0644 "$templates/dabox-filter" /etc/tinyproxy/dabox-filter

  local ssh_rule=""
  $keep_ssh && ssh_rule="ip saddr @home4 tcp dport 22 accept; ip6 saddr @home6 tcp dport 22 accept"
  sed "s|#SSH_RULE#|$ssh_rule|" "$templates/nftables.conf" > /etc/nftables.conf
  nft -c -f /etc/nftables.conf
}

lock_down_consoles() {
  step "Locking down consoles"
  install -d /etc/systemd/logind.conf.d
  printf '[Login]\nNAutoVTs=0\nReserveVT=0\n' > /etc/systemd/logind.conf.d/dabox.conf
  for tty in tty1 tty2 tty3 tty4 tty5 tty6; do
    systemctl mask "getty@$tty.service" >/dev/null 2>&1 || true
  done
  systemctl mask autovt@.service >/dev/null 2>&1 || true
  if ! $keep_ssh; then
    # The serial console and SSH stay only on development boxes.
    systemctl mask serial-getty@ttyAMA0.service serial-getty@ttyS0.service >/dev/null 2>&1 || true
    systemctl disable --now ssh.service >/dev/null 2>&1 || true
  fi
}

set_hostname() {
  step "Naming the box $HOSTNAME_FOR_BOX (admin app: http://$HOSTNAME_FOR_BOX.local)"
  hostnamectl set-hostname "$HOSTNAME_FOR_BOX"
  grep -q "127.0.1.1.*$HOSTNAME_FOR_BOX" /etc/hosts || echo "127.0.1.1 $HOSTNAME_FOR_BOX" >> /etc/hosts
}

enable_services() {
  step "Starting da-box"
  systemctl daemon-reload
  sysctl --system >/dev/null
  udevadm control --reload
  systemctl enable --now udisks2 >/dev/null 2>&1 || true
  systemctl enable tinyproxy >/dev/null 2>&1
  systemctl restart tinyproxy
  systemctl enable --now avahi-daemon systemd-timesyncd >/dev/null 2>&1 || true
  systemctl enable nftables dabox-service dabox-kiosk
  systemctl set-default graphical.target
  systemctl restart nftables
  systemctl restart dabox-service
  systemctl restart dabox-kiosk
}

open_firewall_for_install
install_packages
create_users
install_code
install_godot
install_games
import_ui
write_config
install_system_files
lock_down_consoles
set_hostname
enable_services
step "Done. The box shows the setup screens on the TV."
