#!/bin/sh
# startwm.sh - Window manager and Chromium launcher

TARGET_URL="${TARGET_URL:-http://localhost}"
SCREEN_WIDTH="${SCREEN_WIDTH:-1920}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-1080}"
USER_HOME=$(eval echo "~$USER")
CHROME_PROFILE="${USER_HOME}/.config/chromium-kiosk"

mkdir -p "${CHROME_PROFILE}"

# Avoid duplicate loops if startwm is invoked again in same session
PIDFILE="${USER_HOME}/.chromium_kiosk.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi
echo "$$" > "$PIDFILE"

# Start XFCE4 desktop in background if not running
if ! pgrep -u "$USER" xfce4-session >/dev/null 2>&1; then
    startxfce4 &
    sleep 2
fi

# Launch chromium directly once, let it manage itself
exec /usr/lib/chromium/chromium \
    --no-sandbox \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-dev-shm-usage \
    --disable-infobars \
    --disable-translate \
    --no-first-run \
    --no-default-browser-check \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --password-store=basic \
    --user-data-dir="${CHROME_PROFILE}" \
    --kiosk \
    --window-size=${SCREEN_WIDTH},${SCREEN_HEIGHT} \
    --window-position=0,0 \
    "${TARGET_URL}"
