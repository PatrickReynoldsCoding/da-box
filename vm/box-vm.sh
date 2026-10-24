#!/usr/bin/env bash
# A QEMU VM that acts as the real box.
#   Apple Silicon Mac:  Debian 13 arm64 (HVF)        brew install qemu
#   Windows (Git Bash): Debian 13 x86_64 (WHPX)      scoop install qemu, and turn on the
#                       "Windows Hypervisor Platform" feature (without it QEMU is very slow)
#   Linux:              Debian 13 x86_64 (KVM)       apt install qemu-system-x86
#
#   vm/box-vm.sh create    download the OS, make the disk and cloud-init seed (first time only)
#   vm/box-vm.sh start     start the VM in a window (the window is the "TV")
#   vm/box-vm.sh deploy    copy the repo into the VM and run install/install.sh --vm --keep-ssh
#   vm/box-vm.sh media     copy dev/media (test films and music) into the VM
#   vm/box-vm.sh ssh [cmd] open a shell in the VM, or run one command
#   vm/box-vm.sh keys K..  press keys on the VM keyboard (QEMU names: ret esc up down left right 2 a ...)
#   vm/box-vm.sh screenshot FILE.png   save what the VM screen shows
#   vm/box-vm.sh usb-in IMAGE   plug a disk image in as a USB stick;  usb-out pulls it out
#   vm/box-vm.sh save NAME / restore NAME / snapshots   disk snapshots (VM stopped)
#   vm/box-vm.sh stop      shut the VM down
#   vm/box-vm.sh destroy   delete the VM disk (keeps the OS download)
#
# DABOX_VM=desktop vm/box-vm.sh ... works on a second VM: Ubuntu 24.04 with a LightDM desktop,
# like Linux Mint 22. Use it to test installing over a desktop distro.
#
# From the host: admin app at http://localhost:8081, SSH on port 2222 (user dev, password dev).
# The desktop VM uses 8082 and 2223.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
flavour="${DABOX_VM:-box}"

case "$(uname -s)" in
  Darwin) host=mac ;;
  Linux) host=linux ;;
  MINGW*|MSYS*|CYGWIN*) host=windows ;;
  *) echo "Unsupported host: $(uname -s)" >&2; exit 1 ;;
esac
if [[ $host == mac ]]; then arch=aarch64; debian_arch=arm64; else arch=x86_64; debian_arch=amd64; fi

case "$flavour" in
  box)
    work="$here/work"
    base_name="debian-13-generic-$debian_arch.qcow2"
    base_url="https://cloud.debian.org/images/cloud/trixie/latest/$base_name"
    ssh_port=2222 admin_port=8081 monitor_port=4441
    ;;
  desktop)
    work="$here/work-desktop"
    base_name="noble-server-cloudimg-$debian_arch.img"
    base_url="https://cloud-images.ubuntu.com/noble/current/$base_name"
    ssh_port=2223 admin_port=8082 monitor_port=4442
    ;;
  *) echo "DABOX_VM must be box or desktop." >&2; exit 2 ;;
esac
base_image="$work/$base_name"
disk="$work/box.qcow2"
seed="$work/seed.iso"
seed_dir="$work/seed"
ssh_key="$work/id_ed25519"

ssh_options=(-i "$ssh_key" -p "$ssh_port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

# QEMU on Windows is a Windows program: give it C:/... paths.
native_path() { if [[ $host == windows ]]; then cygpath -m "$1"; else echo "$1"; fi; }

qemu_tool() {
  local name="$1"
  if command -v "$name" >/dev/null; then echo "$name"; return; fi
  if [[ $host == windows && -x "$HOME/scoop/apps/qemu/current/$name.exe" ]]; then
    echo "$HOME/scoop/apps/qemu/current/$name.exe"; return
  fi
  echo "$name not found. Install QEMU first (see the top of $0)." >&2
  exit 1
}

python_bin() { command -v python3 || command -v python; }

# The QEMU monitor listens on a local TCP port (a Unix socket does not work on Windows).
# It takes one client at a time and needs a moment before the next, so connecting retries.
monitor_python() {
  "$(python_bin)" - "$monitor_port" "$@" <<'EOF'
import socket, sys, time
port, commands = int(sys.argv[1]), sys.argv[2:]
for attempt in range(10):
    try:
        connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        break
    except OSError:
        if attempt == (9 if commands else 2):
            sys.exit(1)
        time.sleep(0.5)
with connection:
    connection.recv(4096)
    for command in commands:
        connection.sendall(command.encode() + b"\n")
        time.sleep(0.3)
EOF
}

monitor_command() { monitor_python "$1"; }

is_running() { monitor_python 2>/dev/null; }

vm_ssh() { ssh "${ssh_options[@]}" dev@127.0.0.1 "$@"; }

wait_for_ssh() {
  echo "Waiting for SSH…"
  for _ in $(seq 1 180); do
    vm_ssh true </dev/null 2>/dev/null && return 0
    sleep 2
  done
  echo "SSH did not come up. See $work/serial.log" >&2
  return 1
}

write_user_data() {
  cat > "$seed_dir/user-data" <<EOF
#cloud-config
users:
  - name: dev
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: dev
    ssh_authorized_keys:
      - $(cat "$ssh_key.pub")
ssh_pwauth: false
package_update: true
packages: [rsync]
EOF
  if [[ $flavour == desktop ]]; then
    # Like Linux Mint 22: Ubuntu 24.04, LightDM with the slick greeter, a boot splash and ufw.
    cat >> "$seed_dir/user-data" <<'EOF'
runcmd:
  - DEBIAN_FRONTEND=noninteractive apt-get install -y linux-generic xfce4 lightdm slick-greeter plymouth-theme-spinner ufw
  - printf 'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT quiet splash"\nGRUB_TIMEOUT=1\n' > /etc/default/grub.d/99-desktop.cfg
  - update-grub
  - ufw allow 22/tcp
  - ufw --force enable
  - systemctl set-default graphical.target
EOF
  fi
}

create() {
  mkdir -p "$work"
  [[ -f "$base_image" ]] || curl -fL -o "$base_image" "$base_url"
  [[ -f "$ssh_key" ]] || ssh-keygen -q -t ed25519 -N "" -f "$ssh_key" -C "da-box-vm"
  if [[ ! -f "$disk" ]]; then
    "$(qemu_tool qemu-img)" create -q -f qcow2 -F qcow2 -b "$(native_path "$base_image")" "$(native_path "$disk")" 32G
  fi

  rm -rf "$seed_dir" "$seed"
  mkdir -p "$seed_dir"
  cat > "$seed_dir/meta-data" <<EOF
instance-id: da-box-$flavour
local-hostname: $flavour-vm
EOF
  write_user_data
  # Mac: an ISO. Elsewhere QEMU serves the folder as a FAT disk labelled CIDATA (see start).
  [[ $host == mac ]] && hdiutil makehybrid -quiet -iso -joliet -default-volume-name cidata -o "$seed" "$seed_dir"
  echo "VM created. Run: vm/box-vm.sh start"
}

# Sets qemu_args: the parts that differ between Mac, Linux and Windows.
set_qemu_arguments() {
  local display_device="virtio-vga"
  case "$host" in
    mac)
      display_device="virtio-gpu-pci"
      qemu_args=(-machine virt -accel hvf -cpu host
        -bios "$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd"
        -display cocoa -audiodev coreaudio,id=sound)
      ;;
    linux)
      if [[ -w /dev/kvm ]]; then qemu_args=(-machine q35 -accel kvm -cpu host); else qemu_args=(-machine q35 -accel tcg -cpu max); fi
      qemu_args+=(-display gtk -audiodev "${DABOX_VM_AUDIO:-pa},id=sound")
      ;;
    windows)
      # WHPX if the Windows Hypervisor Platform is on, otherwise (slow) TCG.
      qemu_args=(-machine q35 -accel whpx,kernel-irqchip=off -accel tcg -cpu max -display sdl -audiodev dsound,id=sound)
      ;;
  esac
  qemu_args+=(-device "$display_device,xres=1920,yres=1080")
  if [[ $host == mac ]]; then
    qemu_args+=(-drive "file=$seed,if=virtio,format=raw,readonly=on")
  else
    qemu_args+=(-drive "if=virtio,format=raw,readonly=on,file.driver=vvfat,file.dir=$(native_path "$seed_dir"),file.label=CIDATA")
  fi
}

start() {
  [[ -f "$disk" ]] || create
  if is_running; then echo "The VM is already running."; return; fi
  local qemu_args
  set_qemu_arguments
  # No -daemonize: it crashes with the macOS (cocoa) window. nohup + & instead.
  nohup "$(qemu_tool "qemu-system-$arch")" \
    -name "da-box-$flavour" \
    -smp 4 -m 4096 \
    "${qemu_args[@]}" \
    -drive "file=$(native_path "$disk"),if=none,id=system,format=qcow2" -device virtio-blk-pci,drive=system,bootindex=0 \
    -device qemu-xhci -device usb-kbd -device usb-tablet \
    -device intel-hda -device hda-duplex,audiodev=sound \
    -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$ssh_port-:22,hostfwd=tcp::$admin_port-:80" \
    -serial "file:$(native_path "$work/serial.log")" \
    -monitor "tcp:127.0.0.1:$monitor_port,server,nowait" \
    > "$work/qemu.log" 2>&1 &
  echo "Starting QEMU…"
  local started=false
  for _ in $(seq 1 120); do
    if is_running; then started=true; break; fi
    sleep 1
  done
  $started || { echo "QEMU did not start:" >&2; cat "$work/qemu.log" >&2; exit 1; }
  echo "VM started. Admin app: http://localhost:$admin_port   SSH: vm/box-vm.sh ssh"
}

# Copies the repo with tar over SSH (rsync is not in Git Bash on Windows).
copy_repo() {
  COPYFILE_DISABLE=1 tar -C "$repo" -cf - \
    --exclude=.git --exclude='vm/work*' --exclude=dev/media --exclude=dev/data --exclude=dev/usb \
    --exclude=.venv --exclude=__pycache__ --exclude=ui/.godot . \
    | vm_ssh "rm -rf da-box && mkdir da-box && tar -C da-box -xf - --no-same-owner 2>/dev/null"
}

deploy() {
  wait_for_ssh
  # First boot: cloud-init installs packages. Wait until it is done.
  vm_ssh "cloud-init status --wait >/dev/null 2>&1 || true"
  if [[ $flavour == desktop ]] && ! vm_ssh "systemctl is-active -q display-manager"; then
    # Off and on again: a warm reboot can hang in QEMU's firmware.
    echo "Restarting into the desktop…"
    stop
    start
    wait_for_ssh
  fi
  copy_repo
  vm_ssh "sudo bash da-box/install/install.sh --vm --keep-ssh"
}

media() {
  wait_for_ssh
  [[ -d "$repo/dev/media" ]] || "$repo/dev/make-test-media.sh" "$repo/dev/media"
  COPYFILE_DISABLE=1 tar -C "$repo/dev/media" -cf - . | vm_ssh "sudo -u tvbox tar -C /srv/dabox/media -xf - --no-same-owner"
  echo "Copied. Open the admin app and press 'Rescan files', or restart the service."
}

keys() {
  for key in "$@"; do
    monitor_command "sendkey $key"
    sleep "${KEY_DELAY:-0.4}"
  done
}

screenshot() {
  local target="$1" raw="$work/screen.ppm"
  rm -f "$raw"
  monitor_command "screendump $(native_path "$raw")"
  for _ in 1 2 3 4 5 6 7 8 9 10; do [[ -s "$raw" ]] && break; sleep 0.3; done
  if [[ $host == mac ]]; then
    sips -s format png "$raw" --out "$target" >/dev/null
  else
    ffmpeg -hide_banner -loglevel error -y -i "$raw" "$target"
  fi
  echo "$target"
}

usb_in() {
  local image
  image="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
  monitor_command "drive_add 0 if=none,id=usbstick,format=raw,file=$(native_path "$image")"
  monitor_command "device_add usb-storage,id=usbstickdev,drive=usbstick,removable=on"
  echo "USB stick in: $image"
}

usb_out() {
  monitor_command "device_del usbstickdev"
  echo "USB stick out."
}

snapshot() {
  is_running && { echo "Stop the VM first." >&2; exit 1; }
  "$(qemu_tool qemu-img)" snapshot "$@" "$(native_path "$disk")"
}

stop() {
  if ! is_running; then echo "The VM is not running."; return; fi
  vm_ssh "sudo poweroff" 2>/dev/null || monitor_command "system_powerdown"
  echo "Shutting down."
  for _ in $(seq 1 60); do is_running || return 0; sleep 1; done
  echo "Still running after a minute. 'vm/box-vm.sh kill' pulls the plug." >&2
}

destroy() {
  is_running && { echo "Stop the VM first." >&2; exit 1; }
  rm -f "$disk" "$seed" "$work/serial.log"
  echo "VM disk deleted."
}

command="${1:-}"
shift || true
case "$command" in
  create) create ;;
  start) start ;;
  deploy) deploy ;;
  media) media ;;
  ssh) wait_for_ssh >/dev/null; vm_ssh "$@" ;;
  keys) keys "$@" ;;
  screenshot) screenshot "$1" ;;
  usb-in) usb_in "$1" ;;
  usb-out) usb_out ;;
  save) snapshot -c "$1" ;;
  restore) snapshot -a "$1" ;;
  snapshots) snapshot -l ;;
  stop) stop ;;
  kill) monitor_command "quit" ;;
  destroy) destroy ;;
  *) sed -n '2,26p' "$0"; exit 2 ;;
esac
