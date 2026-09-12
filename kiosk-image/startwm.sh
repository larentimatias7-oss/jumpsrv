#!/bin/bash
set -e

# Read TARGET_URL from environment or /etc/environment
if [ -z "$TARGET_URL" ] && [ -f /etc/environment ]; then
    # shellcheck disable=SC1091
    source /etc/environment 2>/dev/null || true
fi
TARGET_URL="${TARGET_URL:-about:blank}"
USER_DATA_DIR="${HOME:-/home/kiosk}/.config/chromium"
mkdir -p "$USER_DATA_DIR"
# Clean stale Chromium locks from previous sessions/crashes
rm -f "$USER_DATA_DIR"/Singleton*

# Iniciar bus de sesión D-Bus si no existe
if command -v dbus-launch >/dev/null 2>&1 && [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax)
fi

# Configure Openbox for borderless auto-maximized kiosk windows
OPENBOX_DIR="${HOME:-/home/kiosk}/.config/openbox"
mkdir -p "$OPENBOX_DIR"
cat << 'EOF' > "$OPENBOX_DIR/rc.xml"
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <applications>
    <application class="*">
      <decor>no</decor>
      <maximized>yes</maximized>
      <fullscreen>no</fullscreen>
    </application>
  </applications>
</openbox_config>
EOF

# Iniciar gestor de ventanas Openbox en segundo plano
openbox &
sleep 0.5

# Ejecutar Chromium directamente en la sesión gráfica del usuario
exec chromium \
  --kiosk \
  --start-maximized \
  --window-position=0,0 \
  --no-first-run \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --disable-features=TranslateUI \
  --disable-sync \
  --no-default-browser-check \
  --password-store=basic \
  --enable-features=PasswordManager \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --ignore-certificate-errors \
  --test-type \
  --ozone-platform=x11 \
  --user-data-dir="$USER_DATA_DIR" \
  --app="$TARGET_URL"
