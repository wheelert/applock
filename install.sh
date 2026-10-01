#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root (for example: pkexec $0)"
    exit 1
fi

if ! command -v apparmor_parser >/dev/null; then
    echo "apparmor is required"
    exit 1
fi

if ! grep -q apparmor /sys/kernel/security/lsm 2>/dev/null; then
    echo "AppArmor is not active. Enable it and reboot first."
    exit 1
fi

if [ -n "${PKEXEC_UID:-}" ]; then
    TARGET_UID="$PKEXEC_UID"
elif [ -n "${SUDO_UID:-}" ]; then
    TARGET_UID="$SUDO_UID"
else
    TARGET_UID="1000"
fi
TARGET_USER="$(getent passwd "$TARGET_UID" | cut -d: -f1)"
if [ -z "$TARGET_USER" ]; then
    echo "Could not identify the invoking user."
    exit 1
fi

if ! getent group applock >/dev/null; then
    groupadd applock
fi
if ! id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx applock; then
    usermod -aG applock "$TARGET_USER"
fi

mkdir -p /etc/applock /etc/apparmor.d/local /usr/local/bin /usr/local/lib/applock /usr/local/share/applications /etc/systemd/system

install -m 0755 bin/applockd /usr/local/bin/applockd
install -m 0755 bin/applock-launch /usr/local/bin/applock-launch
install -m 0755 bin/applock-admin /usr/local/bin/applock-admin
install -m 0755 bin/applock-admin-gui /usr/local/bin/applock-admin-gui
install -m 0644 lib/applock_common.py /usr/local/lib/applock/applock_common.py
install -m 0644 service/applockd.service /etc/systemd/system/applockd.service
install -m 0644 service/applock-admin.desktop /usr/local/share/applications/applock-admin.desktop
update-desktop-database /usr/local/share/applications || true
install -m 0644 profiles/local-applock-session /etc/apparmor.d/local/applock-session
install -m 0644 profiles/local-applock-daemon /etc/apparmor.d/local/applock-daemon

if [ ! -e /etc/applock/apps.json ]; then
    install -m 0644 config/apps.json /etc/applock/apps.json
fi

if [ ! -e /etc/applock/code ]; then
    install -m 0600 config/code /etc/applock/code
fi

/usr/local/bin/applock-admin sync
systemctl daemon-reload
systemctl enable applockd.service
systemctl restart applockd.service

echo "Installed AppArmor App Lock with website blocking."
echo "Set a code with:    pkexec /usr/local/bin/applock-admin set-code YOUR_CODE"
echo "Add apps with:      pkexec /usr/local/bin/applock-admin add NAME /path/to/app"
echo "Add websites with:  pkexec /usr/local/bin/applock-admin add-website example.com"
echo "Apply changes:      applock-admin-gui"
echo "Log out and back in so GNOME Shell starts under the AppArmor profile."
