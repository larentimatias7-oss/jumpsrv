#!/bin/bash
set -e

TARGET_URL="${TARGET_URL:-about:blank}"
USER_DATA_DIR="${HOME:-/home/kiosk}/.config/chromium"
mkdir -p "$USER_DATA_DIR"
# Clean stale Chromium locks from previous sessions/crashes
rm -f "$USER_DATA_DIR"/Singleton*

# Iniciar bus de sesión D-Bus si no existe
if command -v dbus-launch >/dev/null 2>&1 && [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax)
fi

# Iniciar gestor de ventanas Openbox en segundo plano
openbox &

# Ejecutar Chromium directamente en la sesión gráfica del usuario
exec chromium \
  --kiosk \
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
  --disable-software-rasterizer \
  --disable-dev-shm-usage \
  --user-data-dir="$USER_DATA_DIR" \
  --app="$TARGET_URL"
