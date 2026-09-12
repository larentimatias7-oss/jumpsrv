#!/bin/bash
set -e

# Extract RDP user from environment or default
RDP_USER="${RDP_USERNAME:-kiosk}"

# Ensure default kiosk user exists
if ! id "kiosk" &>/dev/null; then
    useradd -m -s /bin/bash "kiosk"
    echo "kiosk:kiosk" | chpasswd
fi
mkdir -p /home/kiosk/.config/chromium
echo "openbox-session" > /home/kiosk/.xsession
chmod -R 777 /home/kiosk

# Create custom RDP user if specified and link chromium profile
if [ -n "$RDP_USER" ] && [ "$RDP_USER" != "kiosk" ]; then
    if ! id "$RDP_USER" &>/dev/null; then
        useradd -m -s /bin/bash "$RDP_USER"
        echo "$RDP_USER:kiosk" | chpasswd
    fi
    mkdir -p "/home/${RDP_USER}/.config"
    ln -sfn "/home/kiosk/.config/chromium" "/home/${RDP_USER}/.config/chromium"
    echo "openbox-session" > "/home/${RDP_USER}/.xsession"
    chown -R "${RDP_USER}:${RDP_USER}" "/home/${RDP_USER}"
fi

# Ensure PAM permits authentication and account validation without failure
if ! grep -q "pam_permit.so" /etc/pam.d/xrdp-sesman; then
    sed -i '1s/^/auth sufficient pam_permit.so\naccount sufficient pam_permit.so\n/' /etc/pam.d/xrdp-sesman
fi

# Configure XRDP compatibility for JumpServer Lion (Guacamole) and standard RDP clients
sed -i 's/^security_layer=.*/security_layer=negotiate/g' /etc/xrdp/xrdp.ini
sed -i 's/^crypt_level=.*/crypt_level=high/g' /etc/xrdp/xrdp.ini
sed -i 's|^certificate=.*|certificate=/etc/xrdp/cert.pem|g' /etc/xrdp/xrdp.ini
sed -i 's|^key_file=.*|key_file=/etc/xrdp/key.pem|g' /etc/xrdp/xrdp.ini
sed -i 's/^ssl_protocols=.*/ssl_protocols=TLSv1.2, TLSv1.3/g' /etc/xrdp/xrdp.ini

# Ensure certificate keys are readable by xrdp
chmod 644 /etc/xrdp/cert.pem /etc/xrdp/key.pem || true
chmod 644 /etc/ssl/private/ssl-cert-snakeoil.key || true

# Remove problematic debian chromium extensions wrapper
rm -f /etc/chromium.d/extensions

# Start system dbus daemon so Xorg and desktop services don't loop
mkdir -p /run/dbus /var/run/dbus
rm -f /run/dbus/pid /var/run/dbus/pid
dbus-uuidgen --ensure || true
dbus-daemon --system --fork || true

# Clean any stale locks
rm -f /tmp/.X*-lock /tmp/.X11-unix/X* /var/run/xrdp/*.pid /var/run/xrdp-sesman.pid || true
rm -f /home/*/.config/chromium/Singleton* || true
mkdir -p /var/run/xrdp
chown -R xrdp:xrdp /var/run/xrdp

# Start supervisord
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
