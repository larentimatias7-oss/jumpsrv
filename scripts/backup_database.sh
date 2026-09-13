#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# JumpServer Kiosk Manager - Automated SQLite WAL Online Backup
# ==============================================================================
# Safely generates consistent SQLite backups using online '.backup' command
# without locking active transactions or corrupting WAL journals.
# Retains daily/hourly snapshots for 7 days.
# Works with either sqlite3 CLI or python3 built-in sqlite3.backup API.
# ==============================================================================

DB_PATH="${1:-${KIOSK_DB_PATH:-/data/kiosk.db}}"
BACKUP_DIR="${2:-${KIOSK_BACKUP_DIR:-/backup}}"
RETENTION_DAYS="${3:-${KIOSK_BACKUP_RETENTION_DAYS:-7}}"

# Fallbacks for local / non-docker execution
if [ ! -f "$DB_PATH" ]; then
    if [ -f "./data/kiosk.db" ]; then
        DB_PATH="./data/kiosk.db"
    elif [ -f "/app/data/kiosk.db" ]; then
        DB_PATH="/app/data/kiosk.db"
    elif [ -f "/root/jumpserver-kiosk-manager/data/kiosk.db" ]; then
        DB_PATH="/root/jumpserver-kiosk-manager/data/kiosk.db"
    fi
fi

if [ ! -f "$DB_PATH" ]; then
    echo "[$(date -Iseconds)] [ERROR] SQLite database not found at: $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/kiosk_${TIMESTAMP}.db"

echo "[$(date -Iseconds)] [INFO] Starting online SQLite backup for: $DB_PATH"
echo "[$(date -Iseconds)] [INFO] Destination: $BACKUP_FILE"

# Execute SQLite online backup
if command -v sqlite3 >/dev/null 2>&1; then
    if ! sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"; then
        echo "[$(date -Iseconds)] [ERROR] sqlite3 .backup command failed" >&2
        exit 1
    fi
    INTEGRITY_CHECK=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>&1 || true)
elif command -v python3 >/dev/null 2>&1; then
    python3 -c "
import sqlite3, sys
try:
    src = sqlite3.connect('$DB_PATH')
    dst = sqlite3.connect('$BACKUP_FILE')
    src.backup(dst)
    dst.close()
    src.close()
except Exception as e:
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)
"
    INTEGRITY_CHECK=$(python3 -c "import sqlite3; c=sqlite3.connect('$BACKUP_FILE'); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" 2>&1 || true)
else
    echo "[$(date -Iseconds)] [ERROR] Neither sqlite3 nor python3 found in PATH" >&2
    exit 1
fi

# Verify backup integrity
if [ "$INTEGRITY_CHECK" != "ok" ]; then
    echo "[$(date -Iseconds)] [ERROR] Backup integrity check failed: $INTEGRITY_CHECK" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE" 2>/dev/null || wc -c < "$BACKUP_FILE")
echo "[$(date -Iseconds)] [SUCCESS] Backup created and verified successfully (${BACKUP_SIZE} bytes)"

# Retention: Delete backups older than RETENTION_DAYS
echo "[$(date -Iseconds)] [INFO] Pruning backups older than ${RETENTION_DAYS} days in ${BACKUP_DIR}..."
PURGED_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "kiosk_*.db" -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
echo "[$(date -Iseconds)] [INFO] Pruned ${PURGED_COUNT} expired backup file(s)"
