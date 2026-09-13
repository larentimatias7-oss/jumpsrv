# Project Rules - JumpServer Kiosk Manager

## Docker & Container Runtime Rules
- **Docker Socket Access**: `/var/run/docker.sock` is explicitly permitted and required for:
  1. Auto-discovering JumpServer credentials from the local `jms_core` container (`autodiscover_from_core`).
  2. Orchestrating the ephemeral Just-In-Time (JIT) lifecycle of `pam-web-kiosk` containers and credential volumes.
- **Resource Protection**: NEVER stop, modify, or delete any Docker container, volume, or network unless it carries the label `managed-by=jumpserver-kiosk-manager`.
- **Privilege Restrictions**: NEVER run containers in `--privileged` mode.
- **RDP & Dispatcher Architecture**:
  - The Kiosk Dispatcher runs as an asyncio TCP relay in the backend (`network_mode: "host"`), listening on host ports (`33891 - 33920`).
  - Containers do NOT expose raw host ports directly; they run isolated on the bridge network and accept relayed traffic from the Dispatcher to container internal port 3389.
  - The JumpServer host asset is registered with the designated host IP (`KIOSK_HOST_IP` or auto-detected LAN IP).

## JumpServer v4 RBAC Compatibility
- **Strict Prohibition**: NEVER query `User.objects.filter(is_superuser=True)` in JumpServer ORM or shell snippets. In JumpServer v4 (v4.10.x+ CE), superuser status was replaced by Role-Based Access Control (RBAC); referencing `is_superuser` throws a fatal `FieldError: Cannot resolve keyword 'is_superuser' into field`.
- **Role Resolution Protocol**: Always query administrative users via role name:
  `User.objects.filter(role__name__icontains="Admin").first()`
  Follow with safe fallbacks: `User.objects.filter(username="admin").first()` and active accounts, catching `FieldError` and generic exceptions safely.
- **API Specification**: All payloads must strictly comply with JumpServer v4 API endpoints (`/api/v1/assets/hosts/`, `/api/v1/accounts/accounts/`, `/api/v1/perms/asset-permissions/`).
- **Signature & Header Format**:
  `Authorization: Signature keyid="<KEY_ID>",algorithm="hmac-sha256",headers="(request-target) date x-jms-org",signature="<BASE64>"`
  Order of signed string:
  `(request-target): <method> <path>\ndate: <RFC1123>\nx-jms-org: <org-id>`
- Default organization UUID in JumpServer 4.x is `00000000-0000-0000-0000-000000000002` (System Org).

## Development Environment (Windows / WSL)
- **POSIX Parity**: On Windows hosts, all local Python execution, virtual environment operations (`/tmp/venv`), CLI utilities, and test runners MUST be executed inside WSL (`wsl bash -c "..."`).
- Never run Python unit tests directly in Windows PowerShell when path formatting, UNIX sockets, or POSIX filesystem semantics are involved.

## Security, Secrets & Idempotency
- **Zero Secrets in Git**: NEVER commit tokens (`ghp_*`), SSH private keys (`id_ed25519`), passwords, or API secrets to version control.
- **Input Validation**: Never execute shell commands constructed from raw user input without strict sanitization and validation.
- **Password Handling**: Kiosk OS RDP passwords (cryptographically random 32 characters) and system credentials must be transmitted via stdin or temporary 0600 files, NEVER via command-line arguments (`argv`).
- **Rollback Guarantee**: Every provisioning workflow must be idempotent and support strict non-destructive rollback. In case of failure, clean up only newly created resources in reverse order without modifying pre-existing assets.
- **Credential Partitioning (3 Layers)**:
  1. JumpServer user identity (Vault JMS).
  2. Kiosk OS RDP user (random 32 char, Vault JMS only).
  3. Device admin user (Chromium isolated profile in encrypted/persistent volume).

## Git & Quality Assurance Workflow
- **Conventional Commits**: All commit messages must follow Conventional Commits format (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).
- **Mandatory Pre-Push Validation**: Before pushing to `main`, always execute and verify the test suite in WSL:
  `wsl bash -c "/tmp/venv/bin/pytest backend/tests"`
