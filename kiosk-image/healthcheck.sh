#!/bin/bash
# healthcheck.sh - Checks XRDP port and processes

# Check XRDP listening on 3389
if ! nc -z 127.0.0.1 3389 2>/dev/null; then
    echo "ERROR: XRDP is not listening on port 3389"
    exit 1
fi

# Check supervisord is running
if ! pgrep -x supervisord > /dev/null; then
    echo "ERROR: supervisord is not running"
    exit 1
fi

# Check xrdp process
if ! pgrep -x xrdp > /dev/null; then
    echo "ERROR: xrdp process is not running"
    exit 1
fi

echo "OK: Kiosk container services are healthy"
exit 0
