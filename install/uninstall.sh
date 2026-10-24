#!/usr/bin/env bash
# Turns a da-box machine back into a normal one: stops the kiosk and the service, removes the
# firewall and the console lock-down, and turns the desktop login screen (and ufw/firewalld)
# back on if install.sh turned them off. Media, settings and users stay, unless --purge.
#
#   sudo install/uninstall.sh [--purge]
#
#   --purge   also delete the da-box code, media, settings and the tvbox and kid users
set -euo pipefail

INSTALL_DIR="/opt/dabox"
CONFIG_DIR="/etc/dabox"

purge=false
for argument in "$@"; do
  case "$argument" in
    --purge) purge=true ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "Run this as root (sudo)." >&2; exit 1; }

step() { echo; echo "==> $*"; }

step "Stopping da-box"
systemctl disable --now dabox-kiosk dabox-service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/dabox-kiosk.service /etc/systemd/system/dabox-service.service \
  /etc/systemd/system/dabox-update.service /etc/systemd/system/dabox-upgrade.service
rm -rf /var/cache/dabox

step "Removing the firewall"
nft delete table inet dabox 2>/dev/null || true
systemctl disable nftables >/dev/null 2>&1 || true
printf '#!/usr/sbin/nft -f\n# The da-box firewall was removed by install/uninstall.sh.\n' > /etc/nftables.conf
systemctl disable --now tinyproxy >/dev/null 2>&1 || true

step "Turning the consoles back on"
rm -f /etc/systemd/logind.conf.d/dabox.conf /etc/sysctl.d/99-dabox.conf
for tty in tty1 tty2 tty3 tty4 tty5 tty6; do
  systemctl unmask "getty@$tty.service" >/dev/null 2>&1 || true
done
systemctl unmask autovt@.service serial-getty@ttyAMA0.service serial-getty@ttyS0.service >/dev/null 2>&1 || true
sysctl --system >/dev/null

rm -f /etc/pam.d/dabox-kiosk /etc/polkit-1/rules.d/50-dabox.rules \
  /etc/polkit-1/localauthority/50-local.d/50-dabox.pkla /etc/udev/rules.d/99-dabox-usb.rules
udevadm control --reload

# What install.sh turned off: display managers and other firewalls.
if [[ -f "$CONFIG_DIR/turned-off" ]]; then
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
fi
systemctl daemon-reload

if $purge; then
  step "Deleting the da-box code, media, settings and users"
  rm -rf "$INSTALL_DIR" /srv/dabox /var/lib/dabox "$CONFIG_DIR"
  userdel --remove kid 2>/dev/null || true
  userdel tvbox 2>/dev/null || true
  groupdel dabox-media 2>/dev/null || true
fi

step "Done. Restart the machine:  sudo reboot"
echo "SSH and the hostname (tvbox) are left as they are."
