#!/usr/bin/env python3
import json
import socket
import subprocess
import sys
import time
import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "http://172.31.233.5:8080"
AUTH = HTTPBasicAuth("admin", "admin")
KIOSK_NAME = "E2ETEST"
TARGET_URL = "http://172.31.233.5:80"
TARGET_IP = "172.31.233.5"

results = {
    "phases": [],
    "success": True,
    "errors": []
}

def record_phase(name, passed, details=None):
    results["phases"].append({
        "phase": name,
        "passed": passed,
        "details": details or {}
    })
    status_str = "[PASS]" if passed else "[FAIL]"
    print(f"{status_str} {name}")
    if details:
        print(f"       Details: {json.dumps(details, indent=2)}")
    if not passed:
        results["success"] = False
        results["errors"].append(f"{name}: {details}")

print("==================================================")
print("  STARTING E2E VALIDATION: KIOSK MANAGER & JUMPSERVER v4")
print("==================================================")

# --- PHASE 1: Healthcheck & Auth ---
try:
    r_backend_health = requests.get("http://172.31.233.5:8000/health", timeout=5)
    r_frontend = requests.get(f"{BASE_URL}/", timeout=5)
    r_auth = requests.get(f"{BASE_URL}/api/kiosks", auth=AUTH, timeout=5)
    r_unauth = requests.get(f"{BASE_URL}/api/kiosks", timeout=5)
    passed = (r_backend_health.status_code == 200 and 
              r_backend_health.json().get("status") == "ok" and
              r_frontend.status_code == 200 and
              r_auth.status_code == 200 and 
              r_unauth.status_code == 401)
    record_phase("1. API Health & Auth Verification", passed, {
        "backend_health_code": r_backend_health.status_code,
        "backend_health_body": r_backend_health.json(),
        "frontend_spa_code": r_frontend.status_code,
        "auth_api_code": r_auth.status_code,
        "unauth_api_code": r_unauth.status_code,
    })
except Exception as e:
    record_phase("1. API Health & Auth Verification", False, {"error": str(e)})

# --- PHASE 2: JumpServer Autodiscovery Fix Verification ---
try:
    autodisc_code = """
from app.jumpserver.autodiscovery import autodiscover_from_core
import json
creds = autodiscover_from_core()
if creds:
    print('AUTODISC_RES:' + json.dumps({'key_id': creds[0], 'secret_len': len(creds[1])}))
else:
    print('AUTODISC_RES:' + json.dumps({'error': 'None returned'}))
"""
    cmd = [
        "docker", "exec", "-e", "PYTHONPATH=/app", "kiosk-manager-backend",
        "python3", "-c", autodisc_code
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    autodisc_data = {}
    for line in proc.stdout.splitlines():
        if line.startswith("AUTODISC_RES:"):
            autodisc_data = json.loads(line[len("AUTODISC_RES:"):])
            break
    passed = bool(autodisc_data.get("key_id")) and autodisc_data.get("secret_len", 0) > 0
    record_phase("2. JumpServer v4 RBAC Autodiscovery", passed, autodisc_data)
except Exception as e:
    record_phase("2. JumpServer v4 RBAC Autodiscovery", False, {"error": str(e)})

# --- Clean up any pre-existing test kiosk ---
try:
    kiosks = requests.get(f"{BASE_URL}/api/kiosks", auth=AUTH, timeout=5).json()
    for k in kiosks:
        if k.get("name") == KIOSK_NAME:
            print(f"Cleaning up pre-existing test kiosk {k['id']}...")
            requests.delete(f"{BASE_URL}/api/kiosks/{k['id']}", auth=AUTH, timeout=10)
            time.sleep(1)
except Exception as e:
    print(f"Warning during pre-cleanup: {e}")

# --- PHASE 3: Provisioning (POST /api/kiosks) ---
kiosk_data = None
try:
    payload = {
        "name": KIOSK_NAME,
        "device_type": "generic",
        "target_ip": TARGET_IP,
        "target_protocol": "http",
        "target_port": 80,
        "target_url": TARGET_URL
    }
    t0 = time.time()
    r_prov = requests.post(f"{BASE_URL}/api/kiosks", auth=AUTH, json=payload, timeout=20)
    prov_time = round((time.time() - t0) * 1000, 1)
    if r_prov.status_code == 201:
        kiosk_data = r_prov.json()
        passed = (kiosk_data.get("status") == "RUNNING" and 
                  bool(kiosk_data.get("id")) and 
                  bool(kiosk_data.get("rdp_port")) and 
                  bool(kiosk_data.get("jms_asset_id")))
        record_phase("3. Kiosk Provisioning Lifecycle", passed, {
            "http_code": r_prov.status_code,
            "latency_ms": prov_time,
            "kiosk_id": kiosk_data.get("id"),
            "name": kiosk_data.get("name"),
            "rdp_port": kiosk_data.get("rdp_port"),
            "status": kiosk_data.get("status"),
            "jms_asset_id": kiosk_data.get("jms_asset_id"),
        })
    else:
        record_phase("3. Kiosk Provisioning Lifecycle", False, {
            "http_code": r_prov.status_code,
            "response": r_prov.text
        })
except Exception as e:
    record_phase("3. Kiosk Provisioning Lifecycle", False, {"error": str(e)})

if not kiosk_data:
    print("FATAL: Provisioning failed. Aborting remaining phases.")
    sys.exit(1)

kiosk_id = kiosk_data["id"]
rdp_port = kiosk_data["rdp_port"]
jms_asset_id = kiosk_data["jms_asset_id"]

# --- PHASE 4: JumpServer Integration Verification ---
try:
    check_script = f"""
from app.jumpserver.client import JumpServerClient
from app.jumpserver.config import get_jms_settings
import json

client = JumpServerClient(get_jms_settings())
asset = client.get('/api/v1/assets/hosts/{jms_asset_id}/')
accounts = client.get('/api/v1/accounts/accounts/?asset_id={jms_asset_id}')
perms = client.get('/api/v1/perms/asset-permissions/?name=AUT-KIOSK-{KIOSK_NAME}')

print("JMS_VERIFY:" + json.dumps({{
    "asset_name": asset.get("name") if isinstance(asset, dict) else None,
    "asset_address": asset.get("address") if isinstance(asset, dict) else None,
    "asset_id": asset.get("id") if isinstance(asset, dict) else None,
    "accounts_count": len(accounts) if isinstance(accounts, list) else 0,
    "account_username": accounts[0].get("username") if isinstance(accounts, list) and accounts else None,
    "perms_count": len(perms) if isinstance(perms, list) else 0
}}))
"""
    cmd = [
        "docker", "exec", "-e", "PYTHONPATH=/app", "kiosk-manager-backend",
        "python3", "-c", check_script
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    jms_info = {}
    for line in proc.stdout.splitlines():
        if line.startswith("JMS_VERIFY:"):
            jms_info = json.loads(line[len("JMS_VERIFY:"):])
            break

    passed = (jms_info.get("asset_name") == KIOSK_NAME and 
              jms_info.get("accounts_count", 0) >= 1 and 
              jms_info.get("perms_count", 0) >= 1)
    record_phase("4. JumpServer Asset/Account/Permission Creation", passed, jms_info)
except Exception as e:
    record_phase("4. JumpServer Asset/Account/Permission Creation", False, {"error": str(e)})

# --- PHASE 5: Dispatcher Port Listening ---
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    res = sock.connect_ex(("127.0.0.1", rdp_port))
    sock.close()
    passed = (res == 0)
    record_phase("5. Dispatcher RDP Port Listening", passed, {
        "host_ip": "127.0.0.1",
        "rdp_port": rdp_port,
        "socket_connect_code": res
    })
except Exception as e:
    record_phase("5. Dispatcher RDP Port Listening", False, {"error": str(e)})

# --- PHASE 6: Just-In-Time Ephemeral Container Trigger ---
c_name = f"kiosk-{KIOSK_NAME.lower()}"
try:
    p_before = subprocess.run(["docker", "ps", "-a", "--filter", f"name={c_name}", "--format", "{{.Status}}"], capture_output=True, text=True)
    status_before = p_before.stdout.strip()

    print(f"Connecting to dispatcher port {rdp_port} to trigger JIT container start...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    sock.connect(("127.0.0.1", rdp_port))
    # Send RDP connection request PDU
    sock.sendall(b"\x03\x00\x00\x13\x0e\xe0\x00\x00\x00\x00\x00\x01\x00\x08\x00\x03\x00\x00\x00")

    # Poll until container is running
    container_running = False
    for attempt in range(25):
        time.sleep(1)
        p_check = subprocess.run(["docker", "inspect", c_name, "--format", "{{.State.Running}}"], capture_output=True, text=True)
        if p_check.stdout.strip() == "true":
            container_running = True
            break

    sock.close()

    p_labels = subprocess.run(["docker", "inspect", c_name, "--format", "{{json .Config.Labels}}"], capture_output=True, text=True)
    labels = json.loads(p_labels.stdout.strip()) if p_labels.returncode == 0 else {}

    passed = (container_running and labels.get("managed-by") == "jumpserver-kiosk-manager")
    record_phase("6. On-Demand Container Activation (JIT)", passed, {
        "container_name": c_name,
        "status_before": status_before or "none",
        "container_running": container_running,
        "managed_by_label": labels.get("managed-by"),
        "kiosk_id_label": labels.get("kiosk-id"),
    })
except Exception as e:
    record_phase("6. On-Demand Container Activation (JIT)", False, {"error": str(e)})

# --- PHASE 7: Target URL Connectivity Probe ---
try:
    r_probe = requests.get(f"{BASE_URL}/api/kiosks/{kiosk_id}/test-url", auth=AUTH, timeout=10)
    probe_data = r_probe.json() if r_probe.status_code == 200 else {"raw": r_probe.text}
    passed = (r_probe.status_code == 200 and probe_data.get("ok") is True)
    record_phase("7. Kiosk Target Connectivity Probe", passed, {
        "http_code": r_probe.status_code,
        "probe_result": probe_data
    })
except Exception as e:
    record_phase("7. Kiosk Target Connectivity Probe", False, {"error": str(e)})

# --- PHASE 8: Deprovisioning & Safe Resource Cleanup (DELETE /api/kiosks/{id}) ---
try:
    r_del = requests.delete(f"{BASE_URL}/api/kiosks/{kiosk_id}", auth=AUTH, timeout=20)
    del_ok = (r_del.status_code == 200 and r_del.json().get("status") == "deleted")

    # Verify container removed
    p_c = subprocess.run(["docker", "ps", "-a", "--filter", f"name={c_name}", "--format", "{{.ID}}"], capture_output=True, text=True)
    container_removed = (p_c.stdout.strip() == "")

    # Verify volume removed
    v_name = f"rdp_{KIOSK_NAME.lower()}"
    p_v = subprocess.run(["docker", "volume", "ls", "--filter", f"name={v_name}", "--format", "{{.Name}}"], capture_output=True, text=True)
    volume_removed = (p_v.stdout.strip() == "")

    # Verify JumpServer asset deleted
    check_del_script = f"""
from app.jumpserver.client import JumpServerClient
from app.jumpserver.config import get_jms_settings
import json

client = JumpServerClient(get_jms_settings())
try:
    res = client.get('/api/v1/assets/hosts/{jms_asset_id}/')
    print('ASSET_EXISTS:' + json.dumps(isinstance(res, dict) and bool(res.get('id'))))
except Exception:
    print('ASSET_EXISTS:false')
"""
    cmd = [
        "docker", "exec", "-e", "PYTHONPATH=/app", "kiosk-manager-backend",
        "python3", "-c", check_del_script
    ]
    proc_del = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    asset_still_exists = False
    for line in proc_del.stdout.splitlines():
        if "ASSET_EXISTS:true" in line:
            asset_still_exists = True

    # Verify dispatcher port closed
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    res_port = sock.connect_ex(("127.0.0.1", rdp_port))
    sock.close()
    port_closed = (res_port != 0)

    # Verify DB record removed
    r_list = requests.get(f"{BASE_URL}/api/kiosks", auth=AUTH, timeout=5).json()
    kiosk_in_db = any(k.get("id") == kiosk_id for k in r_list)

    passed = (del_ok and container_removed and volume_removed and not asset_still_exists and port_closed and not kiosk_in_db)
    record_phase("8. Deprovisioning & Safe Resource Cleanup", passed, {
        "delete_api_code": r_del.status_code,
        "container_removed": container_removed,
        "volume_removed": volume_removed,
        "jumpserver_asset_deleted": not asset_still_exists,
        "dispatcher_port_closed": port_closed,
        "db_record_removed": not kiosk_in_db
    })
except Exception as e:
    record_phase("8. Deprovisioning & Safe Resource Cleanup", False, {"error": str(e)})

# --- SUMMARY REPORT ---
print("\n==================================================")
print(f"  E2E TEST RUN COMPLETE. OVERALL: {'PASS' if results['success'] else 'FAIL'}")
print("==================================================")
for p in results["phases"]:
    mark = "✓" if p["passed"] else "✗"
    print(f" {mark} {p['phase']}")

if not results["success"]:
    print("\nFAILURES:")
    for err in results["errors"]:
        print(f" - {err}")
    sys.exit(1)
