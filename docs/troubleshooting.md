# Troubleshooting Guide

## 1. JumpServer 401 Unauthorized
- Verify that NTP time on this host is synchronized with JumpServer (`timedatectl`).
- Check that `JMS_KEY_ID` and `JMS_SECRET_FILE` match active Access Key in JumpServer GUI.
- Ensure `X-JMS-ORG` UUID matches the target organization.

## 2. RDP Port Connection Refused
- Check container status: `docker ps --filter label=managed-by=jumpserver-kiosk-manager`
- Inspect XRDP logs inside container: `docker logs kiosk-<name>`
- Verify healthcheck: `docker inspect --format='{{.State.Health.Status}}' kiosk-<name>`

## 3. GHSA-6rp5-ff2m-qfrm
- Ensure Nginx proxy rejects `_rel` query parameter:
  `if ($arg__rel != "") { return 400; }`
