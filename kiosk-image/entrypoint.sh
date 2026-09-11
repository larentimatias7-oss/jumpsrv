#!/bin/bash
set -e

# Extract RDP user from environment or default
RDP_USER="${RDP_USERNAME:-kiosk}"

# Create the user if it doesn't exist
if ! id "$RDP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$RDP_USER"
    echo "$RDP_USER:kiosk" | chpasswd
fi

# Ensure user home directory exists
mkdir -p "/home/${RDP_USER}"
echo "xfce4-session" > "/home/${RDP_USER}/.xsession"
chown -R "${RDP_USER}:${RDP_USER}" "/home/${RDP_USER}"

# Ensure PAM permits authentication without failure
if ! grep -q "pam_permit.so" /etc/pam.d/xrdp-sesman; then
    sed -i '1s/^/auth sufficient pam_permit.so\n/' /etc/pam.d/xrdp-sesman
fi

# Remove problematic debian chromium extensions wrapper
rm -f /etc/chromium.d/extensions

# Start system dbus daemon so Xorg and desktop services don't loop
mkdir -p /run/dbus /var/run/dbus
rm -f /run/dbus/pid /var/run/dbus/pid
dbus-uuidgen --ensure || true
dbus-daemon --system --fork || true

# Clean any stale locks
rm -f /tmp/.X*-lock /tmp/.X11-unix/X* /var/run/xrdp/*.pid /var/run/xrdp-sesman.pid || true
mkdir -p /var/run/xrdp
chown -R xrdp:xrdp /var/run/xrdp

# Start supervisord
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
