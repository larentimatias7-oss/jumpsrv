# Provisioning Lifecycle

## States
- `PENDING`: Port allocated, container starting.
- `RUNNING`: Container healthy, JumpServer asset & account registered, permissions granted.
- `DEGRADED`: JumpServer or Docker state mismatch detected during reconciliation.
- `FAILED`: Failure encountered during creation; automatic rollback executed.

## Rollback Protocol
On any error, resources are inspected and deleted in reverse order:
1. JumpServer Permission (`AUT-KIOSK-<NAME>`)
2. JumpServer Account (`kiosk_<name>`)
3. JumpServer Asset
4. Docker Container (checked for `managed-by=jumpserver-kiosk-manager`)
5. Docker Volume (checked for `managed-by=jumpserver-kiosk-manager`)
