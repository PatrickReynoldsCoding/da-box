#!/usr/bin/env bash
# Turns a da-box machine back into a normal one: stops the kiosk and the service, removes the
# firewall and the console lock-down, turns the desktop login screen (and ufw/firewalld) back on
# if install.sh turned them off, and gives the machine its old name and start-up target back.
# Media, settings and users stay, unless --purge.
#
#   sudo install/uninstall.sh [--purge] [--reboot]
#
#   --purge   also delete the da-box code, media, settings and the tvbox and kid users
#   --reboot  restart the machine at the end (the admin app's "Remove da-box" uses this)
#
# install.sh also installs this file as /opt/dabox/bin/dabox-uninstall, for dabox-remove@.service.
set -euo pipefail

INSTALL_DIR="/opt/dabox"
CONFIG_DIR="/etc/dabox"

step() { echo; echo "==> $*"; }

# Everything is in functions: --purge deletes this file (as /opt/dabox/bin/dabox-uninstall) while it runs.
main() {
  local purge=false reboot=false argument
  for argument in "$@"; do
    case "$argument" in
      --purge) purge=true ;;
      --reboot) reboot=true ;;
      *) echo "Unknown option: $argument" >&2; exit 2 ;;
    esac
  done
  [[ $EUID -eq 0 ]] || { echo "Run this as root (sudo)." >&2; exit 1; }

  step "Stopping da-box"
  systemctl disable --now dabox-kiosk dabox-service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/dabox-kiosk.service /etc/systemd/system/dabox-service.service \
    /etc/systemd/system/dabox-update.service /etc/systemd/system/dabox-upgrade.service \
    /etc/systemd/system/dabox-remove@.service
  rm -rf /var/cache/dabox

  step "Removing the firewall"
  nft delete table inet dabox 2>/dev/null || true
  systemctl disable nftables >/dev/null 2>&1 || true
  printf '#!/usr/sbin/nft -f\n# The da-box firewall was removed by install/uninstall.sh.\n' > /etc/nftables.conf
  systemctl disable --now tinyproxy >/dev/null 2>&1 || true

  step "Turning the consoles back on"
  rm -f /etc/systemd/logind.conf.d/dabox.conf /etc/sysctl.d/99-dabox.conf
  local tty
  for tty in tty1 tty2 tty3 tty4 tty5 tty6; do
    systemctl unmask "getty@$tty.service" >/dev/null 2>&1 || true
  done
  systemctl unmask autovt@.service serial-getty@ttyAMA0.service serial-getty@ttyS0.service >/dev/null 2>&1 || true
  sysctl --system >/dev/null

  rm -f /etc/pam.d/dabox-kiosk /etc/polkit-1/rules.d/50-dabox.rules \
    /etc/polkit-1/localauthority/50-local.d/50-dabox.pkla /etc/udev/rules.d/99-dabox-usb.rules
  udevadm control --reload

  turn_back_on
  restore_name_and_target
  systemctl daemon-reload

  if $purge; then
    step "Deleting the da-box code, media, settings and users"
    rm -rf "$INSTALL_DIR" /srv/dabox /var/lib/dabox "$CONFIG_DIR"
    userdel --remove kid 2>/dev/null || true
    userdel tvbox 2>/dev/null || true
    groupdel dabox-media 2>/dev/null || true
  fi

  if $reboot; then
    step "Done. Restarting into Linux."
    systemctl reboot
  else
    step "Done. Restart the machine:  sudo reboot"
    echo "SSH is left as it is."
  fi
}

# What install.sh turned off: display managers and other firewalls.
turn_back_on() {
  [[ -f "$CONFIG_DIR/turned-off" ]] || return 0
  local unit
  while read -r unit; do
    [[ -n $unit ]] || continue
    if [[ $unit == ufw ]]; then
      step "Turning ufw back on"
      ufw --force enable >/dev/null
    else
      step "Turning $unit back on"
      systemctl unmask "$unit" >/dev/null 2>&1 || true
      systemctl enable "$unit" >/dev/null 2>&1 || true
    fi
  done < "$CONFIG_DIR/turned-off"
  rm -f "$CONFIG_DIR/turned-off"
}

# install.sh saves the machine's name and default target before it changes them.
restore_name_and_target() {
  local name target
  if [[ -s "$CONFIG_DIR/hostname-before" ]]; then
    name="$(cat "$CONFIG_DIR/hostname-before")"
    step "Naming the machine $name again"
    hostnamectl set-hostname "$name"
    sed -i "s/^127\.0\.1\.1[[:space:]].*/127.0.1.1 $name/" /etc/hosts
  fi
  if [[ -s "$CONFIG_DIR/target-before" ]]; then
    target="$(cat "$CONFIG_DIR/target-before")"
    systemctl set-default "$target" >/dev/null 2>&1 || true
  fi
}

main "$@"; exit
