#!/bin/sh
# startwm.sh - Window manager and Chromium launcher

TARGET_URL="${TARGET_URL:-http://localhost}"
SCREEN_WIDTH="${SCREEN_WIDTH:-1920}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-1080}"
CHROME_PROFILE="/home/kiosk/.config/chromium-kiosk"

mkdir -p "${CHROME_PROFILE}"

# Start XFCE4 desktop in background
startxfce4 &

# Wait for XFCE display to stabilize
sleep 3

# Chromium respawn loop
while true; do
    chromium-browser \
        --no-sandbox \
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
    
    sleep 2
done
