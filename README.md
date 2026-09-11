# JumpServer Kiosk Manager

Automated kiosk RDP asset provisioning system for JumpServer Community Edition.

## Features
- **1:1 Device to Kiosk Container**: Isolates web sessions and credentials.
- **Rootless Docker Runtime**: Isolated daemon running under `kiosk-runtime`, ensuring JumpServer rootful engine is never touched.
- **Hardened Image**: `pam-web-kiosk:v1` built on Ubuntu 24.04, XRDP, XFCE4, and Chromium in locked-down kiosk mode.
- **Native JumpServer v1 Integration**: Automatic asset, account, and permission creation using HMAC-SHA256 HTTP signatures.
- **Web UI & CLI**: Fast administration with FastAPI + Vue 3, plus standalone `kioskctl` command line tool.
- **Safe Rollback**: Non-destructive provisioning ensuring unmanaged resources are never deleted on failure.
