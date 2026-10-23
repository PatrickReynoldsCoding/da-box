#!/usr/bin/env bash
# Installs da-box on a Debian-based machine, arm64 or x86_64: Raspberry Pi OS, Debian 12/13,
# Ubuntu 22.04+, Linux Mint 21+ / LMDE 6+ and other apt-based distros, with or without a desktop.
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
#
# On a machine with a desktop (Mint, Ubuntu, Raspberry Pi OS with desktop) the box replaces
# the desktop login screen: the installer turns it off and asks for a restart at the end.
# install/uninstall.sh brings the desktop back.
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
# Display managers the box replaces. display-manager.service is checked too.
DISPLAY_MANAGERS="gdm gdm3 lightdm sddm lxdm xdm slim nodm greetd ly cosmic-greeter"

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
python=""
desktop_was_running=false
nvidia=false

step() { echo; echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }
die() { echo "ERROR: $*" >&2; exit 1; }

godot_architecture() {
  case "$(dpkg --print-architecture)" in
    arm64) echo "arm64" ;;
    amd64) echo "x86_64" ;;
    *) die "Unsupported CPU architecture: $(dpkg --print-architecture). da-box needs arm64 or x86_64 (amd64)." ;;
  esac
}

check_system() {
  command -v apt-get >/dev/null && command -v dpkg >/dev/null ||
    die "da-box installs on Debian-based Linux (Debian, Raspberry Pi OS, Ubuntu, Linux Mint). This system has no apt-get."
  [[ -d /run/systemd/system ]] || die "da-box needs systemd as the init system."
  local name="Linux"
  [[ -r /etc/os-release ]] && name="$(. /etc/os-release && echo "${PRETTY_NAME:-$NAME}")"
  step "Installing da-box on $name ($(dpkg --print-architecture))"
  godot_architecture >/dev/null
}

open_firewall_for_install() {
  # A second run needs the internet for packages. The firewall is written again at the end.
  if nft list table inet dabox >/dev/null 2>&1; then
    step "Opening the firewall while installing"
    nft delete table inet dabox
  fi
}

# Wait for other package managers (Mint's update manager, unattended-upgrades) instead of failing.
apt_get() { apt-get -o DPkg::Lock::Timeout=600 "$@"; }

package_available() {
  local candidate
  candidate="$(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ { print $2 }')"
  [[ -n $candidate && $candidate != "(none)" ]]
}

python_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }

find_python() {
  local candidate
  for candidate in python3 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null && python_ok "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

install_packages() {
  step "Installing packages"
  export DEBIAN_FRONTEND=noninteractive
  apt_get update

  local required=(
    cage xwayland mpv
    python3 python3-venv python3-pip
    avahi-daemon libnss-mdns nftables network-manager systemd-timesyncd
    libgl1-mesa-dri libegl1 libgles2 libgl1 libwayland-client0 libwayland-cursor0
    libwayland-egl1 libxkbcommon0 fontconfig fonts-dejavu-core
    alsa-utils ca-certificates curl unzip rsync udisks2 tinyproxy ffmpeg retroarch
  )
  # Older releases (Ubuntu 22.04, Mint 21) call the polkit package policykit-1.
  if package_available polkitd; then required+=(polkitd); else required+=(policykit-1); fi
  local optional=(
    libdecor-0-0 libretro-core-info
    libretro-nestopia libretro-bsnes-mercury-performance libretro-gambatte libretro-mgba
  )

  local package missing=()
  for package in "${required[@]}"; do
    package_available "$package" || missing+=("$package")
  done
  if (( ${#missing[@]} )); then
    local hint=""
    grep -qi ubuntu /etc/os-release 2>/dev/null && hint=" On Ubuntu, turn on the universe repository: sudo add-apt-repository universe"
    die "These packages are not in this system's package sources: ${missing[*]}.$hint"
  fi
  local wanted=("${required[@]}")
  for package in "${optional[@]}"; do
    if package_available "$package"; then wanted+=("$package"); else warn "$package is not available here; skipping it."; fi
  done
  apt_get install -y --no-install-recommends "${wanted[@]}"

  # The service needs Python 3.11 or newer. Older releases (Ubuntu 22.04, Mint 21) have it as an extra package.
  if ! python="$(find_python)"; then
    for package in python3.13 python3.12 python3.11; do
      if package_available "$package" && package_available "$package-venv"; then
        apt_get install -y --no-install-recommends "$package" "$package-venv"
        break
      fi
    done
    python="$(find_python)" || die "da-box needs Python 3.11 or newer, and this system has $(python3 --version 2>&1)."
  fi
}

# Adds a user to the groups that exist here (render is missing on some systems).
add_to_groups() {
  local user="$1" group
  shift
  for group in "$@"; do
    if getent group "$group" >/dev/null; then usermod -aG "$group" "$user"; fi
  done
}

create_users() {
  step "Creating users and folders"
  getent group "$MEDIA_GROUP" >/dev/null || groupadd --system "$MEDIA_GROUP"
  id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --user-group --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  id "$KID_USER" >/dev/null 2>&1 || useradd --create-home --user-group --shell /usr/sbin/nologin "$KID_USER"
  # systemd-journal: the admin app shows the update log.
  add_to_groups "$SERVICE_USER" "$MEDIA_GROUP" systemd-journal
  # video/render: the screen; input: game controllers; audio: sound.
  add_to_groups "$KID_USER" "$MEDIA_GROUP" video render input audio
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
  install -m 0755 "$templates/dabox-update" "$INSTALL_DIR/bin/dabox-update"

  # A venv from an older Python (or a broken one after a distro upgrade) is made again.
  if [[ -e "$INSTALL_DIR/venv" ]] && ! python_ok "$INSTALL_DIR/venv/bin/python"; then
    rm -rf "$INSTALL_DIR/venv"
  fi
  [[ -x "$INSTALL_DIR/venv/bin/python" ]] || "$python" -m venv "$INSTALL_DIR/venv"
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
  # Godot stops without a message on CPUs older than it supports (on x86_64: no SSE4.2 or
  # POPCNT, also QEMU's default "qemu64" CPU). Stop here, before the desktop is turned off.
  "$binary" --headless --version >/dev/null 2>&1 ||
    die "Godot $GODOT_VERSION does not run on this machine. The CPU is probably too old (Godot needs SSE4.2 and POPCNT on x86_64). In a VM, give it the host CPU (QEMU: -cpu host or -cpu max)."
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
  local output
  output="$("$INSTALL_DIR/godot/godot" --headless --path "$INSTALL_DIR/ui" --import 2>&1)" || true
  # Godot's exit code is not reliable here; the imported files are.
  if ! compgen -G "$INSTALL_DIR/ui/.godot/imported/*" >/dev/null; then
    echo "$output" | tail -20 >&2
    die "Godot could not import the box UI (see above)."
  fi
  chown -R root:root "$INSTALL_DIR"
}

check_graphics() {
  # No GPU render node (a VM, or a GPU without a driver): draw with the CPU, like --vm.
  if ! $vm && ! compgen -G "/dev/dri/renderD*" >/dev/null; then
    warn "No GPU render device (/dev/dri/renderD*) found. Using software rendering, as with --vm."
    vm=true
  fi
  if [[ -d /sys/module/nvidia ]]; then
    # cage (wlroots) needs NVIDIA's kernel modesetting. It takes effect after the restart.
    warn "NVIDIA driver found. Turning on nvidia-drm modesetting for the kiosk. If the screen stays black after the restart, run the installer again with --vm."
    printf 'options nvidia-drm modeset=1\n' > /etc/modprobe.d/dabox-nvidia.conf
    command -v update-initramfs >/dev/null && update-initramfs -u >/dev/null 2>&1 || true
    nvidia=true
  fi
}

write_config() {
  step "Writing configuration"
  local mpv_arguments="" renderer_lines=""
  if $vm; then
    # No GPU in the VM: draw with the CPU.
    mpv_arguments="--vo=wlshm --hwdec=no"
    renderer_lines=$'WLR_RENDERER=pixman\nWLR_NO_HARDWARE_CURSORS=1\nLIBGL_ALWAYS_SOFTWARE=1'
  elif $nvidia; then
    renderer_lines="WLR_NO_HARDWARE_CURSORS=1"
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

polkit_has_js_rules() {
  # polkit 0.106+ reads JavaScript .rules files; 0.105 (Ubuntu 22.04, Mint 21) only .pkla files.
  local version
  version="$(pkaction --version 2>/dev/null | awk '{ print $NF }')"
  [[ -n $version ]] || return 0
  [[ "$(printf '%s\n0.106\n' "$version" | sort -V | head -1)" == "0.106" ]]
}

install_system_files() {
  step "Installing system services, PAM, polkit and firewall"
  install -m 0644 "$templates/dabox-service.service" /etc/systemd/system/dabox-service.service
  install -m 0644 "$templates/dabox-kiosk.service" /etc/systemd/system/dabox-kiosk.service
  install -m 0644 "$templates/dabox-update.service" /etc/systemd/system/dabox-update.service
  install -m 0644 "$templates/pam-dabox-kiosk" /etc/pam.d/dabox-kiosk
  install -d /etc/polkit-1/rules.d
  install -m 0644 "$templates/50-dabox.rules" /etc/polkit-1/rules.d/50-dabox.rules
  if ! polkit_has_js_rules; then
    warn "This polkit is older than 0.106. The admin app works, except 'System update'."
    install -d /etc/polkit-1/localauthority/50-local.d
    install -m 0644 "$templates/50-dabox.pkla" /etc/polkit-1/localauthority/50-local.d/50-dabox.pkla
  fi
  install -m 0644 "$templates/99-dabox-sysctl.conf" /etc/sysctl.d/99-dabox.conf
  install -m 0644 "$templates/99-dabox-usb.rules" /etc/udev/rules.d/99-dabox-usb.rules
  install -m 0644 "$templates/tinyproxy.conf" /etc/tinyproxy/tinyproxy.conf
  install -m 0644 "$templates/dabox-filter" /etc/tinyproxy/dabox-filter

  local ssh_rule=""
  $keep_ssh && ssh_rule="ip saddr @home4 tcp dport 22 accept; ip6 saddr @home6 tcp dport 22 accept"
  sed "s|#SSH_RULE#|$ssh_rule|" "$templates/nftables.conf" > /etc/nftables.conf
  nft -c -f /etc/nftables.conf
}

# Other firewalls would block the admin app (ufw on Mint and Ubuntu, firewalld). The box has its own.
turn_off_other_firewalls() {
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    step "Turning off ufw (the box has its own firewall)"
    ufw --force disable >/dev/null
    echo ufw >> "$CONFIG_DIR/turned-off"
  fi
  if systemctl is-enabled -q firewalld 2>/dev/null; then
    step "Turning off firewalld (the box has its own firewall)"
    systemctl disable --now firewalld >/dev/null 2>&1
    echo firewalld.service >> "$CONFIG_DIR/turned-off"
  fi
  if command -v docker >/dev/null || systemctl is-active -q libvirtd 2>/dev/null; then
    warn "Docker or libvirt is installed. The box firewall replaces all firewall rules, so their networking will not work."
  fi
}

display_manager_units() {
  local unit units=()
  if [[ "$(systemctl show -p LoadState --value display-manager.service 2>/dev/null)" == loaded ]]; then
    units+=("$(systemctl show -p Id --value display-manager.service)")
  fi
  for unit in $DISPLAY_MANAGERS; do
    if systemctl is-enabled -q "$unit.service" 2>/dev/null || systemctl is-active -q "$unit.service" 2>/dev/null; then
      units+=("$unit.service")
    fi
  done
  (( ${#units[@]} )) && printf '%s\n' "${units[@]}" | sort -u
  return 0
}

graphical_session_running() {
  local session
  for session in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{ print $1 }'); do
    [[ "$(loginctl show-session "$session" -p Name --value 2>/dev/null)" == "$KID_USER" ]] && continue
    case "$(loginctl show-session "$session" -p Type --value 2>/dev/null)" in
      x11|wayland|mir) return 0 ;;
    esac
  done
  return 1
}

# The kiosk owns the screen. A desktop login screen on the same machine would fight it for the
# GPU and the console (a frozen or black screen), so it is turned off. uninstall.sh turns it on again.
turn_off_desktop() {
  local units=() unit
  mapfile -t units < <(display_manager_units)
  if graphical_session_running; then desktop_was_running=true; fi
  (( ${#units[@]} )) || return 0
  step "Turning off the desktop login screen (${units[*]})"
  echo "The box starts straight into the kiosk. install/uninstall.sh brings the desktop back."
  for unit in "${units[@]}"; do
    systemctl is-active -q "$unit" && desktop_was_running=true
    grep -qx "$unit" "$CONFIG_DIR/turned-off" 2>/dev/null || echo "$unit" >> "$CONFIG_DIR/turned-off"
  done
  # Not stopped now: this installer may be running inside that desktop. Masked, so a package
  # upgrade cannot turn it on again.
  systemctl disable "${units[@]}" >/dev/null 2>&1 || true
  systemctl mask "${units[@]}" >/dev/null 2>&1 || true
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
    # The serial console and SSH stay only on development boxes. Ubuntu starts SSH from ssh.socket.
    systemctl mask serial-getty@ttyAMA0.service serial-getty@ttyS0.service >/dev/null 2>&1 || true
    systemctl disable --now ssh.socket ssh.service >/dev/null 2>&1 || true
  fi
}

set_hostname() {
  step "Naming the box $HOSTNAME_FOR_BOX (admin app: http://$HOSTNAME_FOR_BOX.local)"
  hostnamectl set-hostname "$HOSTNAME_FOR_BOX"
  if grep -q '^127\.0\.1\.1[[:space:]]' /etc/hosts; then
    sed -i "s/^127\.0\.1\.1[[:space:]].*/127.0.1.1 $HOSTNAME_FOR_BOX/" /etc/hosts
  else
    echo "127.0.1.1 $HOSTNAME_FOR_BOX" >> /etc/hosts
  fi
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
  systemctl restart avahi-daemon >/dev/null 2>&1 || true
  systemctl enable nftables dabox-service dabox-kiosk
  systemctl set-default graphical.target
  systemctl restart nftables
  systemctl restart dabox-service
}

start_kiosk() {
  if $desktop_was_running; then
    # Starting the kiosk now would take the screen away from the running desktop.
    step "Done. Restart the machine to start the box:  sudo reboot"
    echo "After the restart the TV shows the setup screens."
    return
  fi
  systemctl restart dabox-kiosk
  step "Done. The box shows the setup screens on the TV."
}

check_system
open_firewall_for_install
install_packages
create_users
install_code
install_godot
install_games
import_ui
check_graphics
write_config
install_system_files
turn_off_other_firewalls
turn_off_desktop
lock_down_consoles
set_hostname
enable_services
start_kiosk
