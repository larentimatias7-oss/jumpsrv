#!/usr/bin/env bash
set -e

# ==============================================================================
# JumpServer Kiosk Manager - Automated Self-Signed SSL/TLS Provisioning
# ==============================================================================
# Generates and validates an enterprise-grade self-signed X.509 certificate with
# Subject Alternative Names (SAN IP & DNS) for Secure Context (W3C Clipboard API).
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SSL_DIR="${ROOT_DIR}/ssl"
ENV_FILE="${ROOT_DIR}/.env"

FORCE=false
CHECK_ONLY=false
SPECIFIED_IP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f)
      FORCE=true
      shift
      ;;
    --check|-c)
      CHECK_ONLY=true
      shift
      ;;
    --ip|-i)
      SPECIFIED_IP="$2"
      shift 2
      ;;
    *)
      echo "Uso: $0 [--force] [--check] [--ip <IP_ADDRESS>]"
      exit 1
      ;;
  esac
done

echo "===================================================================="
echo "  JumpServer Kiosk Manager - Configuración y Verificación SSL/TLS   "
echo "===================================================================="

# 1. Verificar herramienta openssl
if ! command -v openssl &>/dev/null; then
  echo "[-] ERROR: 'openssl' no está instalado en este sistema."
  echo "    Instale OpenSSL ejecutando: sudo apt-get install -y openssl"
  exit 1
fi
echo "[+] Herramienta OpenSSL detectada: $(openssl version)"

# 2. Detección Inteligente de Dirección IP
TARGET_IP="$SPECIFIED_IP"

if [ -z "$TARGET_IP" ] && [ -f "$ENV_FILE" ]; then
  TARGET_IP=$(grep -E '^(KIOSK_HOST_IP|HOST_IP)=' "$ENV_FILE" 2>/dev/null | cut -d '=' -f2 | tr -d '"'\'' ' || true)
fi

if [ -z "$TARGET_IP" ]; then
  # Probar IP de interfaz con ruta por defecto
  TARGET_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || true)
fi

if [ -z "$TARGET_IP" ]; then
  TARGET_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
fi

if [ -z "$TARGET_IP" ] || [ "$TARGET_IP" = "127.0.0.1" ]; then
  TARGET_IP="172.30.20.62"
fi

echo "[+] Dirección IP del Host detectada: ${TARGET_IP}"

mkdir -p "$SSL_DIR"
CERT_FILE="${SSL_DIR}/kiosk.crt"
KEY_FILE="${SSL_DIR}/kiosk.key"

if [ "$CHECK_ONLY" = true ]; then
  if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "[-] Certificado no encontrado en ${SSL_DIR}."
    exit 1
  fi
else
  if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ] && [ "$FORCE" = false ]; then
    echo "[i] El certificado SSL ya existe en ${SSL_DIR}."
    echo "    (Use --force para regenerar un nuevo certificado)"
  else
    echo "[*] Generando nuevo certificado autofirmado para IP: ${TARGET_IP}..."
    
    SAN="IP:127.0.0.1,IP:${TARGET_IP},DNS:localhost,DNS:kiosk-manager"

    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
      -keyout "$KEY_FILE" \
      -out "$CERT_FILE" \
      -subj "/C=AR/ST=Santa Fe/L=Rosario/O=Milicic/OU=IT/CN=${TARGET_IP}" \
      -addext "subjectAltName=${SAN}" 2>/dev/null

    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"

    echo "[+] Certificado generado con éxito en ${CERT_FILE}"
  fi
fi

# 3. Comprobación y Validación del Certificado
echo ""
echo "--- Resumen del Certificado SSL ---"
CERT_SUBJECT=$(openssl x509 -in "$CERT_FILE" -noout -subject 2>/dev/null)
CERT_DATES=$(openssl x509 -in "$CERT_FILE" -noout -dates 2>/dev/null)
CERT_SAN=$(openssl x509 -in "$CERT_FILE" -noout -text 2>/dev/null | grep -A1 "Subject Alternative Name" | tail -n1 | tr -d ' ' || true)

echo "  Archivo Certificado: ${CERT_FILE}"
echo "  Archivo Clave:       ${KEY_FILE}"
echo "  Subject:             ${CERT_SUBJECT}"
echo "  SAN (Alt Names):     ${CERT_SAN}"
echo "  Validez:             $(echo "$CERT_DATES" | tr '\n' ' ')"

# 4. Validar concordancia de clave y certificado (Modulus match)
KEY_MD5=$(openssl rsa -noout -modulus -in "$KEY_FILE" 2>/dev/null | openssl md5)
CRT_MD5=$(openssl x509 -noout -modulus -in "$CERT_FILE" 2>/dev/null | openssl md5)

if [ "$KEY_MD5" = "$CRT_MD5" ]; then
  echo "[+] Validación de integridad: Clave privada y certificado coinciden (MD5 Modulus OK)"
else
  echo "[-] ERROR: La clave privada y el certificado no coinciden."
  exit 1
fi

# 5. Prueba de conexión local HTTPS si el contenedor o puerto está activo
echo ""
echo "[*] Verificando puertos locales..."
if nc -z 127.0.0.1 8443 2>/dev/null || timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/8443" 2>/dev/null; then
  echo "[+] Puerto HTTPS 8443 activo en 127.0.0.1:8443"
  if curl -k -s -I "https://127.0.0.1:8443/" | grep -q "HTTP/"; then
    echo "[+] Conexión HTTPS exitosa contra https://127.0.0.1:8443/"
  fi
else
  echo "[i] Puerto 8443 no está activo aún (normal si el contenedor no ha reiniciado)."
fi

echo ""
echo "===================================================================="
echo "  Configuración SSL completada con éxito.                           "
echo "  Para aplicar cambios en producción:                               "
echo "    docker compose -f docker-compose.prod.yml up -d --force-recreate"
echo "  URL Segura de acceso:                                             "
echo "    https://${TARGET_IP}:8443/luna/                                "
echo "===================================================================="
