<script setup>
import { ref, computed, onMounted } from 'vue'

const kiosks = ref([])
const loading = ref(false)
const showCreateModal = ref(false)
const showEditModal = ref(false)
const notification = ref(null)
const searchQuery = ref('')
const selectedTypeFilter = ref('all')

// Live URL probe status per kiosk { [id]: { testing, ok, status_code, latency_ms, error } }
const urlTestResults = ref({})
const editUrlTesting = ref(false)
const editUrlTestResult = ref(null)

const authCredentials = ref({
  user: localStorage.getItem('kiosk_user') || 'admin',
  pass: localStorage.getItem('kiosk_pass') || 'admin'
})

const form = ref({
  name: '',
  device_type: 'generic',
  target_ip: '',
  target_protocol: 'http',
  target_port: 80,
  target_url: '',
  node_id: ''
})

const editForm = ref({
  id: '',
  name: '',
  device_type: 'generic',
  target_url: ''
})

const deviceTypes = [
  { id: 'generic', label: 'Generic Web Console', icon: '🌐' },
  { id: 'zabbix', label: 'Zabbix Monitoring', icon: '📊' },
  { id: 'router', label: 'Router / Gateway', icon: '🔀' },
  { id: 'switch', label: 'Switch / Core', icon: '⚡' },
  { id: 'proxmox', label: 'Proxmox / Hypervisor', icon: '🖥️' },
  { id: 'camera', label: 'IP Camera / CCTV', icon: '📹' },
  { id: 'idrac', label: 'Dell iDRAC / IPMI', icon: '⚙️' },
  { id: 'fortigate', label: 'Fortinet FortiGate', icon: '🛡️' }
]

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
        device_type: 'generic',
        target_ip: '',
        target_protocol: 'http',
        target_port: 80,
        target_url: '',
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

const openEditModal = (kiosk) => {
  editForm.value = {
    id: kiosk.id,
    name: kiosk.name,
    device_type: kiosk.device_type || 'generic',
    target_url: kiosk.target_url
  }
  editUrlTestResult.value = null
  showEditModal.value = true
}

const saveKioskEdit = async () => {
  try {
    const res = await fetch(`/api/kiosks/${editForm.value.id}`, {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify({
        name: editForm.value.name,
        device_type: editForm.value.device_type,
        target_url: editForm.value.target_url
      })
    })
    const data = await res.json()
    if (res.ok) {
      showToast(`Kiosk ${data.name} updated successfully!`)
      showEditModal.value = false
      fetchKiosks()
    } else {
      showToast(data.detail || 'Failed to update kiosk', 'error')
    }
  } catch (err) {
    showToast('Network error while saving changes', 'error')
  }
}

const testConnectivity = async (kiosk) => {
  urlTestResults.value[kiosk.id] = { testing: true }
  try {
    const res = await fetch(`/api/kiosks/${kiosk.id}/test-url`, { headers: getHeaders() })
    const data = await res.json()
    urlTestResults.value[kiosk.id] = {
      testing: false,
      ok: data.ok,
      status_code: data.status_code,
      latency_ms: data.latency_ms,
      error: data.error
    }
    if (data.ok) {
      showToast(`${kiosk.name} reachable (${data.status_code} in ${data.latency_ms}ms)`)
    } else {
      showToast(`${kiosk.name} unreachable: ${data.error}`, 'error')
    }
  } catch (err) {
    urlTestResults.value[kiosk.id] = { testing: false, ok: false, error: 'Probe request failed' }
    showToast(`Error probing ${kiosk.name}`, 'error')
  }
}

const testEditUrl = async () => {
  if (!editForm.value.id) return
  editUrlTesting.value = true
  editUrlTestResult.value = null
  try {
    const res = await fetch(`/api/kiosks/${editForm.value.id}/test-url`, { headers: getHeaders() })
    const data = await res.json()
    editUrlTestResult.value = data
  } catch (err) {
    editUrlTestResult.value = { ok: false, error: 'Network error probing URL' }
  } finally {
    editUrlTesting.value = false
  }
}

const clearCache = async (kiosk) => {
  if (!confirm(`Clear web browser cache and cookies for "${kiosk.name}"? Active login sessions will be reset.`)) {
    return
  }
  try {
    const res = await fetch(`/api/kiosks/${kiosk.id}/clear-cache`, {
      method: 'POST',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast(`Browser cache cleared for ${kiosk.name}`)
      fetchKiosks()
    } else {
      showToast('Failed to clear cache', 'error')
    }
  } catch (err) {
    showToast('Error clearing cache', 'error')
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
  if (!confirm(`Are you sure you want to delete ${name}? This will permanently remove the JumpServer asset and container volume.`)) {
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

const openLunaSession = (kiosk) => {
  if (kiosk.jms_asset_id && kiosk.jms_account_id) {
    const url = `/luna/admin-connect?asset=${kiosk.jms_asset_id}&account=${kiosk.jms_account_id}&protocol=rdp`
    window.open(url, '_blank')
  } else if (kiosk.jms_asset_id) {
    const url = `/luna/admin-connect?asset=${kiosk.jms_asset_id}`
    window.open(url, '_blank')
  } else {
    window.open('/luna/', '_blank')
  }
}

// Computed stats and filtering
const activeSessionsCount = computed(() => {
  return kiosks.value.filter(k => k.container_status === 'running').length
})

const standbyCount = computed(() => {
  return kiosks.value.filter(k => k.container_status !== 'running').length
})

const ramSavedGb = computed(() => {
  return ((standbyCount.value * 768) / 1024).toFixed(1)
})

const filteredKiosks = computed(() => {
  return kiosks.value.filter(k => {
    const matchSearch = !searchQuery.value ||
      k.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      k.target_url.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
      k.target_ip.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchType = selectedTypeFilter.value === 'all' || k.device_type === selectedTypeFilter.value
    return matchSearch && matchType
  })
})

const getTypeLabel = (typeId) => {
  const match = deviceTypes.find(d => d.id === typeId)
  return match ? `${match.icon} ${match.label}` : typeId
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
          <p class="subtitle">Automated RDP Web Assets & On-Demand Lifecycle</p>
        </div>
      </div>
      
      <div class="actions">
        <a href="/luna/" target="_blank" class="btn btn-ghost" title="Abrir JumpServer Luna">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
            <polyline points="15 3 21 3 21 9"/>
            <line x1="10" y1="14" x2="21" y2="3"/>
          </svg>
          JumpServer Luna
        </a>
        <button class="btn btn-secondary" @click="fetchKiosks" :disabled="loading">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'spinning': loading }">
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
          <span class="stat-sub">Configured Web Assets</span>
        </div>
        <div class="glass-panel stat-card">
          <span class="stat-label">Active Sessions</span>
          <span class="stat-value" :class="activeSessionsCount > 0 ? 'success' : 'muted'">
            {{ activeSessionsCount }}
          </span>
          <span class="stat-sub">{{ activeSessionsCount }} running containers</span>
        </div>
        <div class="glass-panel stat-card">
          <span class="stat-label">RAM Saved (On-Demand)</span>
          <span class="stat-value accent">{{ ramSavedGb }} GB</span>
          <span class="stat-sub">{{ standbyCount }} idle / sleeping kiosks</span>
        </div>
        <div class="glass-panel stat-card">
          <span class="stat-label">Allocated Ports</span>
          <span class="stat-value">{{ kiosks.length }}/30</span>
          <span class="stat-sub">:33891 - :33920</span>
        </div>
      </div>

      <!-- Kiosks Table Section -->
      <section class="glass-panel table-wrapper">
        <div class="table-toolbar">
          <div class="table-header">
            <h2>Active Device Kiosks</h2>
            <span class="badge">{{ filteredKiosks.length }} visible</span>
          </div>

          <!-- Search & Filter Controls -->
          <div class="filter-controls">
            <div class="search-input-wrapper">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input v-model="searchQuery" placeholder="Search by name, URL, or IP..." />
              <button v-if="searchQuery" class="clear-search" @click="searchQuery = ''">&times;</button>
            </div>

            <select v-model="selectedTypeFilter" class="filter-select">
              <option value="all">All Device Types</option>
              <option v-for="d in deviceTypes" :key="d.id" :value="d.id">{{ d.label }}</option>
            </select>
          </div>
        </div>

        <table class="kiosks-table">
          <thead>
            <tr>
              <th>Device Name</th>
              <th>Type</th>
              <th>Target URL</th>
              <th>RDP Port</th>
              <th>Container Lifecycle</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredKiosks.length === 0 && !loading">
              <td colspan="6" class="empty-state">
                <div class="empty-box">
                  <span class="empty-icon">🔍</span>
                  <p>No kiosks match your search or filters.</p>
                </div>
              </td>
            </tr>
            <tr v-for="k in filteredKiosks" :key="k.id" class="table-row">
              <td class="name-cell">
                <div class="device-name-group">
                  <strong>{{ k.name }}</strong>
                  <span class="sub-asset-id" :title="'JMS ID: ' + (k.jms_asset_id || 'N/A')">
                    {{ k.rdp_username }}
                  </span>
                </div>
              </td>
              <td>
                <span class="chip chip-type">{{ getTypeLabel(k.device_type) }}</span>
              </td>
              <td class="mono-cell">
                <div class="url-group">
                  <a :href="k.target_url" target="_blank" rel="noopener" class="url-link">{{ k.target_url }}</a>
                  
                  <!-- URL probe latency pill -->
                  <span v-if="urlTestResults[k.id]?.testing" class="probe-pill probing">
                    Probing...
                  </span>
                  <span v-else-if="urlTestResults[k.id]?.ok" class="probe-pill ok" :title="'Status: ' + urlTestResults[k.id]?.status_code">
                    HTTP {{ urlTestResults[k.id]?.status_code }} ({{ urlTestResults[k.id]?.latency_ms }}ms)
                  </span>
                  <span v-else-if="urlTestResults[k.id]?.error" class="probe-pill err" :title="urlTestResults[k.id]?.error">
                    Offline
                  </span>
                </div>
              </td>
              <td class="mono-cell">
                <span class="chip chip-port">:{{ k.rdp_port }}</span>
              </td>
              <td>
                <div class="lifecycle-cell">
                  <span v-if="k.container_status === 'running'" class="badge-lifecycle running">
                    <span class="pulse-dot"></span>
                    Activo (En Sesión)
                  </span>
                  <span v-else class="badge-lifecycle idle" title="Apagado para ahorrar 768MB de RAM. Se enciende automáticamente al conectar en JumpServer.">
                    💤 En Espera (0% RAM)
                  </span>
                </div>
              </td>
              <td class="actions-cell">
                <!-- Connect in Luna -->
                <button class="btn-action btn-connect" title="Abrir sesión en JumpServer Luna" @click="openLunaSession(k)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                  </svg>
                  Conectar
                </button>

                <!-- Test Connectivity -->
                <button class="icon-btn" title="Probar conectividad de la URL destino" @click="testConnectivity(k)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                  </svg>
                </button>

                <!-- Edit Kiosk -->
                <button class="icon-btn" title="Editar URL o Parámetros" @click="openEditModal(k)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                </button>

                <!-- Clear Cache -->
                <button class="icon-btn" title="Limpiar cookies y contraseñas guardadas del navegador" @click="clearCache(k)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/>
                    <line x1="18" y1="9" x2="12" y2="15"/>
                    <line x1="12" y1="9" x2="18" y2="15"/>
                  </svg>
                </button>

                <!-- Restart -->
                <button class="icon-btn" title="Reiniciar sesión" @click="restartKiosk(k.id)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                  </svg>
                </button>

                <!-- Delete -->
                <button class="icon-btn danger" title="Eliminar quiosco" @click="deleteKiosk(k.id, k.name)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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

    <!-- Edit Kiosk Modal -->
    <div v-if="showEditModal" class="modal-backdrop">
      <div class="modal-window glass-panel">
        <div class="modal-header">
          <div class="modal-title-group">
            <h3>Editar Quiosco Web</h3>
            <p class="modal-subtitle">Modifica la URL de destino o el tipo de dispositivo</p>
          </div>
          <button class="close-btn" @click="showEditModal = false">&times;</button>
        </div>
        <form @submit.prevent="saveKioskEdit" class="modal-form">
          <div class="form-group">
            <label>Nombre del Dispositivo</label>
            <input v-model="editForm.name" required />
          </div>

          <div class="form-group">
            <label>Perfil / Tipo de Dispositivo</label>
            <select v-model="editForm.device_type">
              <option v-for="d in deviceTypes" :key="d.id" :value="d.id">
                {{ d.label }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <div class="label-with-action">
              <label>Target URL (URL Completa)</label>
              <button type="button" class="btn-inline-test" @click="testEditUrl" :disabled="editUrlTesting">
                <span v-if="editUrlTesting">Probando...</span>
                <span v-else>⚡ Probar URL</span>
              </button>
            </div>
            <input v-model="editForm.target_url" placeholder="e.g. http://192.168.1.110/zabbix/" required />
            <small class="form-hint">Chromium abrirá exactamente esta URL en pantalla completa al iniciar la sesión.</small>

            <!-- Test Result inside Modal -->
            <div v-if="editUrlTestResult" :class="['inline-probe-alert', editUrlTestResult.ok ? 'ok' : 'err']">
              <span v-if="editUrlTestResult.ok">
                ✅ Conexión exitosa: Código HTTP {{ editUrlTestResult.status_code }} ({{ editUrlTestResult.latency_ms }}ms)
              </span>
              <span v-else>
                ❌ Error de conexión: {{ editUrlTestResult.error }}
              </span>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="showEditModal = false">Cancelar</button>
            <button type="submit" class="btn btn-primary">Guardar Cambios</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Create Kiosk Modal -->
    <div v-if="showCreateModal" class="modal-backdrop">
      <div class="modal-window glass-panel">
        <div class="modal-header">
          <div class="modal-title-group">
            <h3>Provision New Device Kiosk</h3>
            <p class="modal-subtitle">Añade un nuevo activo RDP para acceso web en JumpServer</p>
          </div>
          <button class="close-btn" @click="showCreateModal = false">&times;</button>
        </div>
        <form @submit.prevent="createKiosk" class="modal-form">
          <div class="form-group">
            <label>Device Name (JumpServer Asset)</label>
            <input v-model="form.name" placeholder="e.g. ROUTER-MIKROTIK o ZABBIX-LOCAL" required />
          </div>

          <div class="form-row">
            <div class="form-group flex-1">
              <label>Device Type Profile</label>
              <select v-model="form.device_type">
                <option v-for="d in deviceTypes" :key="d.id" :value="d.id">
                  {{ d.label }}
                </option>
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
              <input v-model="form.target_ip" placeholder="192.168.1.1" required />
            </div>
            <div class="form-group flex-1">
              <label>Port</label>
              <input v-model.number="form.target_port" type="number" required />
            </div>
          </div>

          <div class="form-group">
            <label>Path or Custom URL (Optional)</label>
            <input v-model="form.target_url" placeholder="e.g. /zabbix/ or http://192.168.1.110/zabbix/" />
            <small class="form-hint">Si dejas esto vacío, se generará como protocol://ip:port automáticamente.</small>
          </div>

          <div class="form-group">
            <label>JumpServer Node ID (Optional)</label>
            <input v-model="form.node_id" placeholder="Leave empty for root node (/DEFAULT)" />
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
  max-width: 1320px;
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
  align-items: center;
  gap: 12px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: 8px;
  border: 1px solid transparent;
  text-decoration: none;
}

.btn-primary {
  background: var(--accent-gradient);
  color: white;
  border: none;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);
}

.btn-primary:hover {
  filter: brightness(1.1);
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

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.success { color: var(--status-success); }
.stat-value.accent { color: #a855f7; }
.stat-value.muted { color: var(--text-muted); }

.stat-sub {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.table-wrapper {
  overflow: hidden;
  margin-bottom: 40px;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-subtle);
}

.table-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.table-header h2 {
  font-size: 1.1rem;
  font-weight: 600;
}

.badge {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
  font-size: 0.75rem;
  padding: 3px 8px;
  border-radius: 6px;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-input-wrapper svg {
  position: absolute;
  left: 12px;
  color: var(--text-muted);
  pointer-events: none;
}

.search-input-wrapper input {
  padding: 8px 32px 8px 34px;
  font-size: 0.82rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-primary);
  width: 240px;
  transition: width 0.2s, border-color 0.2s;
}

.search-input-wrapper input:focus {
  outline: none;
  width: 280px;
  border-color: var(--accent-primary);
}

.clear-search {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 1.1rem;
}

.filter-select {
  padding: 8px 12px;
  font-size: 0.82rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-primary);
}

.kiosks-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.kiosks-table th {
  padding: 12px 24px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-subtle);
}

.kiosks-table td {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: middle;
  font-size: 0.875rem;
}

.table-row:hover {
  background: rgba(255, 255, 255, 0.02);
}

.device-name-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.device-name-group strong {
  color: var(--text-primary);
  font-size: 0.95rem;
}

.sub-asset-id {
  font-size: 0.72rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.chip-type {
  background: rgba(139, 92, 246, 0.12);
  color: #c084fc;
  border: 1px solid rgba(139, 92, 246, 0.25);
}

.chip-port {
  font-family: var(--font-mono);
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
}

.mono-cell {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}

.url-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.url-link {
  color: #38bdf8;
  text-decoration: none;
}

.url-link:hover {
  text-decoration: underline;
}

.probe-pill {
  font-size: 0.68rem;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.probe-pill.probing {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.probe-pill.ok {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.probe-pill.err {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}

.badge-lifecycle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.badge-lifecycle.running {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-lifecycle.idle {
  background: rgba(100, 116, 139, 0.12);
  color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  background: #10b981;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.actions-cell {
  text-align: right;
  white-space: nowrap;
}

.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  font-size: 0.75rem;
  font-weight: 600;
  border-radius: 6px;
  margin-right: 6px;
}

.btn-connect {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
  border: none;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
}

.btn-connect:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
}

.icon-btn {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.icon-btn.danger:hover {
  background: rgba(239, 68, 68, 0.15);
  color: var(--status-danger);
  border-color: rgba(239, 68, 68, 0.3);
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-window {
  width: 100%;
  max-width: 520px;
  border: 1px solid var(--border-subtle);
  background: #0f172a;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
  overflow: hidden;
}

.modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.modal-title-group h3 {
  font-size: 1.15rem;
  font-weight: 600;
}

.modal-subtitle {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-top: 2px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: var(--text-muted);
  line-height: 1;
}

.close-btn:hover {
  color: var(--text-primary);
}

.modal-form {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: flex;
  gap: 16px;
}

.flex-1 { flex: 1; }
.flex-2 { flex: 2; }

.label-with-action {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-inline-test {
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.3);
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
}

.btn-inline-test:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.3);
}

.inline-probe-alert {
  font-size: 0.78rem;
  padding: 8px 12px;
  border-radius: 6px;
  margin-top: 4px;
}

.inline-probe-alert.ok {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #34d399;
}

.inline-probe-alert.err {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
}

.form-hint {
  font-size: 0.72rem;
  color: var(--text-muted);
}

label {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-secondary);
}

input, select {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 14px;
  color: var(--text-primary);
  font-size: 0.875rem;
}

input:focus, select:focus {
  outline: none;
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 10px;
}

.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  z-index: 2000;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  animation: slideIn 0.3s ease;
}

.toast.success {
  background: #065f46;
  color: #6ee7b7;
  border: 1px solid #047857;
}

.toast.error {
  background: #7f1d1d;
  color: #fca5a5;
  border: 1px solid #991b1b;
}

.empty-state {
  text-align: center;
  padding: 48px 24px;
}

.empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 2rem;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes slideIn {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
</style>
