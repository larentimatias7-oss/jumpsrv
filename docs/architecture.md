# Architecture Guide - JumpServer Kiosk Manager

## High-Level Workflow
1. Operator requests device connection via JumpServer Web Terminal (Luna).
2. JumpServer routes connection through `jms_lion` over RDP to host IP:3389X.
3. Kiosk container listening on 3389 serves XFCE4 + Chromium in locked Kiosk mode.
4. Chromium accesses the target device directly, retaining isolated cookies/session state in a dedicated Docker volume.

## Security Controls
- Docker Rootless isolation protects host root and JumpServer system containers.
- Strict HMAC-SHA256 signature algorithm matching JumpServer 4.x core.
- Port binding bound to single interface.
