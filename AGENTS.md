# Project Rules - JumpServer Kiosk Manager

## Docker Rules
- **CRITICAL**: Never interact with `/var/run/docker.sock` (Docker rootful of JumpServer).
- Only use the rootless Docker daemon (user `kiosk-runtime`, socket `/run/user/<UID>/docker.sock`).
- Never use `--privileged` in containers.
- Never delete a Docker resource unless it contains label `managed-by=jumpserver-kiosk-manager`.
- Always bind RDP ports specifically to the designated host IP (e.g., `-p 172.30.20.62:3389X:3389` or lab IP), never `0.0.0.0`.

## Security Rules
- Never commit credentials, tokens or secrets to Git.
- Never place device credentials in source code.
- Never execute shell commands constructed from raw user input without validation.
- Passwords for kiosk system accounts must be passed securely via stdin (`echo "user:pass" | chpasswd`) or temporary 600 files, NEVER in argv.
- Always validate device names, IP addresses, ports and URLs strictly.
- Preserve existing kiosks during failed provisioning (strict non-destructive rollback).

## JumpServer API Rules
- Payloads must strictly adhere to the installed `/api/docs/` specification.
- Use the verified Authorization header format:
  `Authorization: Signature keyid="<KEY_ID>",algorithm="hmac-sha256",headers="(request-target) date x-jms-org",signature="<BASE64>"`
- Signed string order must be:
  `(request-target): <method> <path>\ndate: <RFC1123>\nx-jms-org: <org-id>`
- Every create operation must be idempotent or cleanly recoverable.

## Architecture Rules
- 1 device = 1 container = 1 RDP port = 1 JumpServer asset.
- Use image `pam-web-kiosk:v1` (Ubuntu 24.04 + modern Chromium + XRDP + Supervisor).
- Keep credentials partitioned into 3 isolated layers:
  1. JumpServer user identity (Vault JMS)
  2. Kiosk OS RDP user (random 32 char, Vault JMS only)
  3. Device admin user (Chromium isolated profile)
- Database: SQLite with WAL mode.
- Frontend: Vue 3 + Vite with clean, responsive dark/light UI.
