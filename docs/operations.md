# Operations & Maintenance Guide

## 1. Routine Backups
Execute scheduled backups using the provided script:
```bash
/root/jumpserver-kiosk-manager/scripts/backup.sh
```

## 2. Reconcile Process
To verify consistency between SQLite, Docker containers, and JumpServer assets:
```bash
python3 -m app.cli reconcile
```

## 3. Safe Shutdown & Maintenance
Before system maintenance:
1. Stop frontend and backend containers:
   ```bash
   docker compose down
   ```
2. Running kiosk containers will stay persisted and restart automatically via `unless-stopped`.
