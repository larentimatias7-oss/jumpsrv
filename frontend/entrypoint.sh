#!/bin/sh
set -e

SSL_DIR="/etc/nginx/ssl"
mkdir -p "$SSL_DIR"

if [ ! -f "$SSL_DIR/kiosk.crt" ] || [ ! -f "$SSL_DIR/kiosk.key" ]; then
    echo "[SSL Entrypoint] SSL certificate or key not found in $SSL_DIR. Generating self-signed certificate..."

    # 1. Detect target IP
    TARGET_IP="${KIOSK_HOST_IP:-${HOST_IP:-}}"
    if [ -z "$TARGET_IP" ]; then
        TARGET_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
    fi
    if [ -z "$TARGET_IP" ]; then
        TARGET_IP=$(hostname -i 2>/dev/null | awk '{print $1}')
    fi
    if [ -z "$TARGET_IP" ] || [ "$TARGET_IP" = "127.0.0.1" ]; then
        TARGET_IP="172.30.20.62"
    fi

    echo "[SSL Entrypoint] Target IP detected: $TARGET_IP"

    # 2. OpenSSL SAN configuration
    SAN="IP:127.0.0.1,IP:$TARGET_IP,DNS:localhost,DNS:kiosk-manager"

    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$SSL_DIR/kiosk.key" \
        -out "$SSL_DIR/kiosk.crt" \
        -subj "/C=AR/ST=Santa Fe/L=Rosario/O=Milicic/OU=IT/CN=$TARGET_IP" \
        -addext "subjectAltName=$SAN" 2>/dev/null

    chmod 600 "$SSL_DIR/kiosk.key"
    chmod 644 "$SSL_DIR/kiosk.crt"

    echo "[SSL Entrypoint] Self-signed certificate generated successfully with SAN: $SAN"
fi

# 3. Test certificate validity
if openssl x509 -in "$SSL_DIR/kiosk.crt" -noout -checkend 0 >/dev/null 2>&1; then
    CERT_CN=$(openssl x509 -in "$SSL_DIR/kiosk.crt" -noout -subject 2>/dev/null | sed 's/.*CN = //')
    CERT_EXP=$(openssl x509 -in "$SSL_DIR/kiosk.crt" -noout -enddate 2>/dev/null | sed 's/notAfter=//')
    echo "[SSL Entrypoint] Certificate verified: CN=$CERT_CN, Expires: $CERT_EXP"
else
    echo "[SSL Entrypoint] Warning: Certificate failed validation. Regenerating..."
    rm -f "$SSL_DIR/kiosk.crt" "$SSL_DIR/kiosk.key"
fi

exec "$@"
