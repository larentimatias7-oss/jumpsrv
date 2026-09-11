<script setup>
import { ref, onMounted } from 'vue'

const kiosks = ref([])
const loading = ref(false)
const showCreateModal = ref(false)
const notification = ref(null)

const authCredentials = ref({
  user: localStorage.getItem('kiosk_user') || 'admin',
  pass: localStorage.getItem('kiosk_pass') || 'admin'
})

const form = ref({
  name: '',
  device_type: 'dell_nseries',
  target_ip: '',
  target_protocol: 'http',
  target_port: 80,
  node_id: ''
})

const showToast = (msg, type = 'success') => {
  notification.value = { msg, type }
  setTimeout(() => { notification.value = null }, 4000)
}

const getHeaders = () => {
  const token = btoa(`${authCredentials.value.user}:${authCredentials.value.pass}`)
  return {
    'Authorization': `Basic ${token}`,
    'Content-Type': 'application/json'
  }
}

const fetchKiosks = async () => {
  loading.value = true
  try {
    const res = await fetch('/api/kiosks', { headers: getHeaders() })
    if (res.ok) {
      kiosks.value = await res.json()
    } else if (res.status === 401) {
      showToast('Authentication required or invalid credentials', 'error')
    }
  } catch (err) {
    showToast('Failed to connect to backend API', 'error')
  } finally {
    loading.value = false
  }
}

const createKiosk = async () => {
  try {
    const res = await fetch('/api/kiosks', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(form.value)
    })
    const data = await res.json()
    if (res.ok) {
      showToast(`Kiosk ${data.name} provisioned successfully!`)
      showCreateModal.value = false
      form.value = {
        name: '',
        device_type: 'dell_nseries',
        target_ip: '',
        target_protocol: 'http',
        target_port: 80,
        node_id: ''
      }
      fetchKiosks()
    } else {
      showToast(data.detail || 'Provisioning failed', 'error')
    }
  } catch (err) {
    showToast('Network error during provisioning', 'error')
  }
}

const restartKiosk = async (id) => {
  try {
    const res = await fetch(`/api/kiosks/${id}/restart`, {
      method: 'POST',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast('Restart triggered successfully')
      fetchKiosks()
    } else {
      showToast('Failed to restart container', 'error')
    }
  } catch (err) {
    showToast('Error sending restart command', 'error')
  }
}

const deleteKiosk = async (id, name) => {
  if (!confirm(`Are you sure you want to delete ${name}? This will remove the JumpServer asset and container.`)) {
    return
  }
  try {
    const res = await fetch(`/api/kiosks/${id}`, {
      method: 'DELETE',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast(`Kiosk ${name} removed cleanly`)
      fetchKiosks()
    } else {
      showToast('Failed to delete kiosk', 'error')
    }
  } catch (err) {
    showToast('Error deleting kiosk', 'error')
  }
}

onMounted(() => {
  fetchKiosks()
})
</script>

<template>
  <div class="dashboard-layout">
    <!-- Top Navbar -->
    <header class="navbar glass-panel">
      <div class="brand">
        <div class="brand-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div>
          <h1>JumpServer <span>Kiosk Manager</span></h1>
          <p class="subtitle">Automated RDP Web Assets</p>
        </div>
      </div>
      
      <div class="actions">
        <button class="btn btn-secondary" @click="fetchKiosks">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
          </svg>
          Refresh
        </button>
        <button class="btn btn-primary" @click="showCreateModal = true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          New Device Kiosk
        </button>
      </div>
    </header>

    <!-- Toast Notification -->
    <div v-if="notification" :class="['toast', notification.type]">
      {{ notification.msg }}
    </div>

    <!-- Main Content -->
    <main class="content-container">
      <!-- Stat Cards -->
      <div class="stats-grid">
        <div class="glass-panel stat-card">
          <span class="stat-label">Total Kiosks</span>
          <span class="stat-value">{{ kiosks.length }}</span>
        </div>
        <div class="glass-panel stat-card">
          <span class="stat-label">Active & Healthy</span>
          <span class="stat-value success">{{ kiosks.filter(k => k.status === 'RUNNING').length }}</span>
        </div>
        <div class="glass-panel stat-card">
          <span class="stat-label">Allocated Ports</span>
          <span class="stat-value accent">{{ kiosks.length }}/30</span>
        </div>
      </div>

      <!-- Kiosks Table -->
      <section class="glass-panel table-wrapper">
        <div class="table-header">
          <h2>Active Device Kiosks</h2>
          <span class="badge">{{ kiosks.length }} configured</span>
        </div>

        <table class="kiosks-table">
          <thead>
            <tr>
              <th>Device Name</th>
              <th>Type</th>
              <th>Target URL</th>
              <th>RDP Port</th>
              <th>Status</th>
              <th>Container Health</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="kiosks.length === 0 && !loading">
              <td colspan="7" class="empty-state">
                No kiosks provisioned yet. Click "New Device Kiosk" to create your first RDP asset.
              </td>
            </tr>
            <tr v-for="k in kiosks" :key="k.id">
              <td class="name-cell">
                <strong>{{ k.name }}</strong>
              </td>
              <td>
                <span class="chip chip-type">{{ k.device_type }}</span>
              </td>
              <td class="mono-cell">
                <a :href="k.target_url" target="_blank" rel="noopener">{{ k.target_url }}</a>
              </td>
              <td class="mono-cell">
                <span class="chip chip-port">:{{ k.rdp_port }}</span>
              </td>
              <td>
                <span :class="['status-dot', k.status.toLowerCase()]"></span>
                {{ k.status }}
              </td>
              <td>
                <span :class="['chip', k.container_health === 'healthy' ? 'chip-success' : 'chip-muted']">
                  {{ k.container_health }}
                </span>
              </td>
              <td class="actions-cell">
                <button class="icon-btn" title="Restart" @click="restartKiosk(k.id)">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                  </svg>
                </button>
                <button class="icon-btn danger" title="Delete" @click="deleteKiosk(k.id, k.name)">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>

    <!-- Create Kiosk Modal -->
    <div v-if="showCreateModal" class="modal-backdrop">
      <div class="modal-window glass-panel">
        <div class="modal-header">
          <h3>Provision New Device Kiosk</h3>
          <button class="close-btn" @click="showCreateModal = false">&times;</button>
        </div>
        <form @submit.prevent="createKiosk" class="modal-form">
          <div class="form-group">
            <label>Device Name (JumpServer Asset)</label>
            <input v-model="form.name" placeholder="e.g. SWSR-CORE02 or zabbix local" required />
          </div>

          <div class="form-row">
            <div class="form-group flex-1">
              <label>Device Type Profile</label>
              <select v-model="form.device_type">
                <option value="dell_nseries">Dell N-Series Switch</option>
                <option value="fortigate">Fortinet FortiGate</option>
                <option value="aruba">Aruba AP / Switch</option>
                <option value="idrac">Dell iDRAC</option>
                <option value="generic">Generic Web Console</option>
              </select>
            </div>
            <div class="form-group flex-1">
              <label>Protocol</label>
              <select v-model="form.target_protocol">
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group flex-2">
              <label>Device IP Address</label>
              <input v-model="form.target_ip" placeholder="192.168.0.221" required />
            </div>
            <div class="form-group flex-1">
              <label>Port</label>
              <input v-model.number="form.target_port" type="number" required />
            </div>
          </div>

          <div class="form-group">
            <label>Path or Custom URL (Optional)</label>
            <input v-model="form.target_url" placeholder="e.g. /zabbix/ or http://192.168.1.110/zabbix/" />
          </div>

          <div class="form-group">
            <label>JumpServer Node ID (Optional)</label>
            <input v-model="form.node_id" placeholder="Leave empty for root node" />
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="showCreateModal = false">Cancel</button>
            <button type="submit" class="btn btn-primary">Provision & Link JumpServer</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-layout {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px;
  margin-bottom: 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-icon {
  background: var(--accent-gradient);
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: #fff;
  box-shadow: var(--accent-glow);
}

.brand h1 {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.brand h1 span {
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.actions {
  display: flex;
  gap: 12px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  border: none;
}

.btn-primary {
  background: var(--accent-gradient);
  color: #fff;
  box-shadow: var(--accent-glow);
}

.btn-primary:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.1);
}

.toast {
  position: fixed;
  top: 24px;
  right: 24px;
  padding: 14px 20px;
  border-radius: 8px;
  background: #1e293b;
  color: #fff;
  z-index: 1000;
  border-left: 4px solid var(--accent-primary);
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
}

.toast.error {
  border-left-color: var(--status-danger);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-label {
  font-size: 0.85rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
}

.stat-value.success { color: var(--status-success); }
.stat-value.accent { color: var(--accent-primary); }

.table-wrapper {
  padding: 20px;
  overflow: hidden;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.table-header h2 {
  font-size: 1.15rem;
  font-weight: 600;
}

.badge {
  font-size: 0.75rem;
  background: rgba(255,255,255,0.06);
  padding: 4px 10px;
  border-radius: 20px;
  color: var(--text-secondary);
}

.kiosks-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.kiosks-table th {
  padding: 12px 14px;
  font-size: 0.8rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border-subtle);
}

.kiosks-table td {
  padding: 14px;
  font-size: 0.9rem;
  border-bottom: 1px solid var(--border-subtle);
}

.mono-cell {
  font-family: var(--font-mono);
  font-size: 0.85rem;
}

.mono-cell a {
  color: var(--text-secondary);
  text-decoration: none;
}

.mono-cell a:hover {
  color: var(--accent-primary);
  text-decoration: underline;
}

.chip {
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-family: var(--font-mono);
}

.chip-type { background: rgba(139, 92, 246, 0.15); color: #c4b5fd; }
.chip-port { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; }
.chip-success { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; }
.chip-muted { background: rgba(148, 163, 184, 0.1); color: #94a3b8; }

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}

.status-dot.running { background: var(--status-success); box-shadow: 0 0 8px var(--status-success); }
.status-dot.pending { background: var(--status-warning); }
.status-dot.failed { background: var(--status-danger); }

.actions-cell {
  text-align: right;
  white-space: nowrap;
}

.icon-btn {
  background: rgba(255,255,255,0.05);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 6px;
}

.icon-btn:hover {
  background: rgba(255,255,255,0.15);
  color: #fff;
}

.icon-btn.danger:hover {
  background: rgba(239, 68, 68, 0.2);
  color: var(--status-danger);
  border-color: var(--status-danger);
}

.empty-state {
  text-align: center;
  padding: 40px !important;
  color: var(--text-muted);
}

/* Modal styles */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}

.modal-window {
  width: 100%;
  max-width: 520px;
  padding: 28px;
  background: #111827;
  border: 1px solid rgba(255,255,255,0.15);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.close-btn {
  background: transparent;
  border: none;
  font-size: 1.5rem;
  color: var(--text-muted);
}

.form-group {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: flex;
  gap: 12px;
}

.flex-1 { flex: 1; }
.flex-2 { flex: 2; }

label {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

input, select {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 10px 12px;
  border-radius: 8px;
  outline: none;
}

input:focus, select:focus {
  border-color: var(--accent-primary);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}
</style>
