#!/usr/bin/env bash
# A Debian 13 arm64 VM that acts as the real box, on an Apple Silicon Mac (QEMU + HVF).
#
#   vm/box-vm.sh create    download Debian, make the disk and cloud-init seed (first time only)
#   vm/box-vm.sh start     start the VM in a window (the window is the "TV")
#   vm/box-vm.sh deploy    copy the repo into the VM and run install/install.sh --vm --keep-ssh
#   vm/box-vm.sh media     copy dev/media (test films and music) into the VM
#   vm/box-vm.sh ssh [cmd] open a shell in the VM, or run one command
#   vm/box-vm.sh keys K..  press keys on the VM keyboard (QEMU names: ret esc up down left right 2 a ...)
#   vm/box-vm.sh screenshot FILE.png   save what the VM screen shows
#   vm/box-vm.sh stop      shut the VM down
#   vm/box-vm.sh destroy   delete the VM disk (keeps the Debian download)
#
# From the Mac: admin app at http://localhost:8081, SSH on port 2222 (user dev).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
work="$here/work"
base_image="$work/debian-13-generic-arm64.qcow2"
base_url="https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-arm64.qcow2"
disk="$work/box.qcow2"
seed="$work/seed.iso"
ssh_key="$work/id_ed25519"
pid_file="$work/qemu.pid"
monitor="$work/monitor.sock"
firmware="$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd"
ssh_port=2222
admin_port=8081

ssh_options=(-i "$ssh_key" -p "$ssh_port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

is_running() { [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; }

vm_ssh() { ssh "${ssh_options[@]}" dev@127.0.0.1 "$@"; }

wait_for_ssh() {
  echo "Waiting for SSH…"
  for _ in $(seq 1 120); do
    vm_ssh true 2>/dev/null && return 0
    sleep 2
  done
  echo "SSH did not come up. See $work/serial.log" >&2
  return 1
}

create() {
  mkdir -p "$work"
  [[ -f "$base_image" ]] || curl -fL -o "$base_image" "$base_url"
  [[ -f "$ssh_key" ]] || ssh-keygen -q -t ed25519 -N "" -f "$ssh_key" -C "da-box-vm"
  if [[ ! -f "$disk" ]]; then
    qemu-img create -q -f qcow2 -F qcow2 -b "$base_image" "$disk" 24G
  fi

  local seed_dir="$work/seed"
  rm -rf "$seed_dir" "$seed"
  mkdir -p "$seed_dir"
  cat > "$seed_dir/meta-data" <<EOF
instance-id: da-box-vm
local-hostname: tvbox
EOF
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
  hdiutil makehybrid -quiet -iso -joliet -default-volume-name cidata -o "$seed" "$seed_dir"
  echo "VM created. Run: vm/box-vm.sh start"
}

start() {
  [[ -f "$disk" ]] || create
  if is_running; then echo "The VM is already running."; return; fi
  # No -daemonize: it crashes with the macOS (cocoa) window. nohup + & instead.
  nohup qemu-system-aarch64 \
    -name da-box \
    -machine virt -accel hvf -cpu host -smp 4 -m 4096 \
    -bios "$firmware" \
    -device virtio-gpu-pci,xres=1920,yres=1080 \
    -display cocoa \
    -device qemu-xhci -device usb-kbd -device usb-tablet \
    -audiodev coreaudio,id=sound -device intel-hda -device hda-duplex,audiodev=sound \
    -drive "file=$disk,if=virtio,format=qcow2" \
    -drive "file=$seed,if=virtio,format=raw,readonly=on" \
    -nic "user,model=virtio-net-pci,hostfwd=tcp::$ssh_port-:22,hostfwd=tcp::$admin_port-:80" \
    -serial "file:$work/serial.log" \
    -monitor "unix:$monitor,server,nowait" \
    -pidfile "$pid_file" \
    > "$work/qemu.log" 2>&1 &
  sleep 2
  is_running || { echo "QEMU did not start:" >&2; cat "$work/qemu.log" >&2; exit 1; }
  echo "VM started. Admin app: http://localhost:$admin_port   SSH: vm/box-vm.sh ssh"
}

deploy() {
  wait_for_ssh
  # First boot: cloud-init installs rsync. Wait until it is done.
  vm_ssh "cloud-init status --wait >/dev/null; command -v rsync >/dev/null || sudo apt-get install -y rsync"
  rsync -a --delete -e "ssh ${ssh_options[*]}" \
    --exclude .git --exclude 'vm/work' --exclude 'dev/media' --exclude 'dev/data' \
    --exclude .venv --exclude __pycache__ --exclude 'ui/.godot' \
    "$repo/" dev@127.0.0.1:da-box/
  vm_ssh "sudo da-box/install/install.sh --vm --keep-ssh"
}

media() {
  wait_for_ssh
  rsync -a -e "ssh ${ssh_options[*]}" --rsync-path="sudo -u tvbox rsync" "$repo/dev/media/" dev@127.0.0.1:/srv/dabox/media/
  echo "Copied. Open the admin app and press 'Rescan files', or restart the service."
}

monitor_command() { echo "$1" | nc -U "$monitor" >/dev/null; }

keys() {
  for key in "$@"; do
    monitor_command "sendkey $key"
    sleep "${KEY_DELAY:-0.4}"
  done
}

screenshot() {
  local target="$1" raw="$work/screen.ppm"
  rm -f "$raw"
  monitor_command "screendump $raw"
  for _ in 1 2 3 4 5 6 7 8 9 10; do [[ -s "$raw" ]] && break; sleep 0.3; done
  sips -s format png "$raw" --out "$target" >/dev/null
  echo "$target"
}

stop() {
  if ! is_running; then echo "The VM is not running."; return; fi
  vm_ssh "sudo poweroff" 2>/dev/null || echo "system_powerdown" | nc -U "$monitor" >/dev/null
  echo "Shutting down."
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
  stop) stop ;;
  destroy) destroy ;;
  *) sed -n '2,15p' "$0"; exit 2 ;;
esac
