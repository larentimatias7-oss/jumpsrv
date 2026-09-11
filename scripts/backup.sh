#!/bin/bash
set -euo pipefail

BACKUP_DIR="/backup/kiosk-$(date +%F_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up Kiosk database..."
if [ -f /root/jumpserver-kiosk-manager/kiosk.db ]; then
    sqlite3 /root/jumpserver-kiosk-manager/kiosk.db ".backup '$BACKUP_DIR/kiosk.db'"
fi

echo "Backing up RDP volumes..."
for vol in $(docker volume ls -q --filter label=managed-by=jumpserver-kiosk-manager 2>/dev/null || true); do
    echo "Archiving volume $vol..."
    docker run --rm -v "${vol}:/source:ro" -v "${BACKUP_DIR}:/backup" \
        alpine tar czf "/backup/${vol}.tgz" -C /source .
done

echo "Backup complete at $BACKUP_DIR"
