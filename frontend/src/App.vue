<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import MilicicLogo from './components/MilicicLogo.vue'

// --- State Management ---
const kiosks = ref([])
const loading = ref(false)
const showCreateModal = ref(false)
const showEditModal = ref(false)
const showSettingsModal = ref(false)
const showActionsDropdown = ref(false)
const showUserDropdown = ref(false)
const showStatsPanel = ref(false)
const notification = ref(null)

// Search & Filtering
const searchQuery = ref('')
const selectedTypeFilter = ref('all')
const selectedStatusFilter = ref('all') // 'all', 'running', 'idle'
const selectedCategoryFilter = ref('all') // 'all', 'web', 'network', 'monitoring', 'virtualization'
const activeTab = ref('normal') // 'normal', 'luna', 'stats'
const activeSidebarItem = ref('kiosks') // 'dashboard', 'kiosks', 'active_sessions', 'idle_sessions'
const searchInputRef = ref(null)

// Live URL probe status per kiosk { [id]: { testing, ok, status_code, latency_ms, error } }
const urlTestResults = ref({})
const editUrlTesting = ref(false)
const editUrlTestResult = ref(null)

// Auth Credentials
const authCredentials = ref({
  user: localStorage.getItem('kiosk_user') || 'admin',
  pass: localStorage.getItem('kiosk_pass') || 'admin'
})

// --- Session Lifecycle & RAM Conservation Policies ---
const lifecycleSettings = ref({
  disconnect_grace_seconds: 30,
  idle_timeout_seconds: 900,
  max_session_lifetime_seconds: 14400,
  max_concurrent_sessions: 4
})
const loadingSettings = ref(false)
const savingSettings = ref(false)

const openSettingsModal = () => {
  showSettingsModal.value = true
  fetchSettings()
}

const fetchSettings = async () => {
  loadingSettings.value = true
  try {
    const res = await fetch('/api/settings', { headers: getHeaders() })
    if (res.ok) {
      const data = await res.json()
      lifecycleSettings.value = {
        disconnect_grace_seconds: data.disconnect_grace_seconds ?? 30,
        idle_timeout_seconds: data.idle_timeout_seconds ?? 900,
        max_session_lifetime_seconds: data.max_session_lifetime_seconds ?? 14400,
        max_concurrent_sessions: data.max_concurrent_sessions ?? 4
      }
    }
  } catch (err) {
    console.error('Error al cargar configuración del sistema:', err)
  } finally {
    loadingSettings.value = false
  }
}

const saveAllSettings = async () => {
  const grace = Number(lifecycleSettings.value.disconnect_grace_seconds)
  const idle = Number(lifecycleSettings.value.idle_timeout_seconds)
  const maxLife = Number(lifecycleSettings.value.max_session_lifetime_seconds)
  const maxConcurrent = Number(lifecycleSettings.value.max_concurrent_sessions)

  if (isNaN(grace) || grace < 5 || grace > 3600) {
    showToast('Tiempo de gracia inválido (debe ser entre 5 y 3600 segundos)', 'error')
    return
  }
  if (isNaN(idle) || idle < 30 || idle > 86400) {
    showToast('Tiempo de inactividad inválido (debe ser entre 30 y 86400 segundos)', 'error')
    return
  }
  if (isNaN(maxLife) || maxLife < 60 || maxLife > 604800) {
    showToast('Límite máximo de sesión inválido (debe ser entre 60 y 604800 segundos)', 'error')
    return
  }
  if (isNaN(maxConcurrent) || maxConcurrent < 1 || maxConcurrent > 100) {
    showToast('Límite de concurrencia inválido (debe ser entre 1 y 100 sesiones)', 'error')
    return
  }

  savingSettings.value = true
  localStorage.setItem('kiosk_user', authCredentials.value.user)
  localStorage.setItem('kiosk_pass', authCredentials.value.pass)

  try {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify({
        disconnect_grace_seconds: grace,
        idle_timeout_seconds: idle,
        max_session_lifetime_seconds: maxLife,
        max_concurrent_sessions: maxConcurrent
      })
    })
    if (res.ok) {
      const updated = await res.json()
      lifecycleSettings.value = updated
      showToast('Configuración y políticas de sesión guardadas con éxito')
      showSettingsModal.value = false
      fetchKiosks()
    } else {
      const errData = await res.json().catch(() => ({}))
      showToast(`Error al guardar configuración: ${errData.detail || res.statusText}`, 'error')
    }
  } catch (err) {
    showToast('Error de red al guardar la configuración', 'error')
  } finally {
    savingSettings.value = false
  }
}

const saveCredentials = saveAllSettings

// Forms
const form = ref({
  name: '',
  device_type: 'generic',
  target_ip: '',
  target_protocol: 'http',
  target_port: 80,
  target_url: '',
  category_name: 'SWITCHES ROSARIO',
  node_id: ''
})

const editForm = ref({
  id: '',
  name: '',
  device_type: 'generic',
  target_url: '',
  category_name: 'SWITCHES ROSARIO'
})

// Categories & JumpServer Dynamic Node Catalog
const categories = ref([])
const loadingCategories = ref(false)
const syncingJms = ref(false)

const availableCategories = computed(() => {
  if (categories.value && categories.value.length > 0) {
    return categories.value
  }
  return [
    { name: 'SWITCHES ROSARIO', icon: '⚡' },
    { name: 'SERVERS INFRA', icon: '🖥️' },
    { name: 'SERVERS BACKUP', icon: '💾' },
    { name: 'WEB MANAGEMENT', icon: '🌐' },
    { name: 'FIREWALLS / UTM', icon: '🛡️' }
  ]
})

// Device Types Catalog
const deviceTypes = [
  { id: 'generic', label: 'Generic Web Console', category: 'web', icon: '🌐' },
  { id: 'zabbix', label: 'Zabbix Monitoring', category: 'monitoring', icon: '📊' },
  { id: 'router', label: 'Router / Gateway', category: 'network', icon: '🔀' },
  { id: 'switch', label: 'Switch / Core', category: 'network', icon: '⚡' },
  { id: 'proxmox', label: 'Proxmox / Hypervisor', category: 'virtualization', icon: '🖥️' },
  { id: 'camera', label: 'IP Camera / CCTV', category: 'monitoring', icon: '📹' },
  { id: 'idrac', label: 'Dell iDRAC / IPMI', category: 'virtualization', icon: '⚙️' },
  { id: 'fortigate', label: 'Fortinet FortiGate', category: 'network', icon: '🛡️' }
]

// --- Notifications ---
const showToast = (msg, type = 'success') => {
  notification.value = { msg, type }
  setTimeout(() => { notification.value = null }, 4000)
}

// --- API Helpers ---
const getHeaders = () => {
  const token = btoa(`${authCredentials.value.user}:${authCredentials.value.pass}`)
  return {
    'Authorization': `Basic ${token}`,
    'Content-Type': 'application/json'
  }
}

// --- Fetch Data ---
const fetchKiosks = async (showLoading = true) => {
  if (showLoading) loading.value = true
  try {
    const res = await fetch('/api/kiosks', { headers: getHeaders() })
    if (res.ok) {
      kiosks.value = await res.json()
    } else if (res.status === 401 && showLoading) {
      showToast('Autenticación requerida o credenciales inválidas', 'error')
    }
  } catch (err) {
    if (showLoading) {
      showToast('Error de conexión con el API de JumpServer Kiosk', 'error')
    }
  } finally {
    if (showLoading) loading.value = false
  }
}

// --- CRUD Actions ---
const createKiosk = async () => {
  try {
    const res = await fetch('/api/kiosks', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(form.value)
    })
    const data = await res.json()
    if (res.ok) {
      showToast(`Quiosco "${data.name}" aprovisionado con éxito!`)
      showCreateModal.value = false
      form.value = {
        name: '',
        device_type: 'generic',
        target_ip: '',
        target_protocol: 'http',
        target_port: 80,
        target_url: '',
        category_name: categories.value.length ? categories.value[0].name : 'SWITCHES ROSARIO',
        node_id: ''
      }
      fetchKiosks()
    } else {
      showToast(data.detail || 'Fallo al aprovisionar quiosco', 'error')
    }
  } catch (err) {
    showToast('Error de red durante el aprovisionamiento', 'error')
  }
}

const openEditModal = (kiosk) => {
  editForm.value = {
    id: kiosk.id,
    name: kiosk.name,
    device_type: kiosk.device_type || 'generic',
    target_url: kiosk.target_url,
    category_name: kiosk.category_name || kiosk.jms_node_name || (categories.value.length ? categories.value[0].name : 'SWITCHES ROSARIO')
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
        target_url: editForm.value.target_url,
        category_name: editForm.value.category_name
      })
    })
    const data = await res.json()
    if (res.ok) {
      showToast(`Quiosco "${data.name}" actualizado con éxito!`)
      showEditModal.value = false
      fetchKiosks()
    } else {
      showToast(data.detail || 'Error al actualizar el quiosco', 'error')
    }
  } catch (err) {
    showToast('Error de red al guardar cambios', 'error')
  }
}

const fetchCategories = async () => {
  loadingCategories.value = true
  try {
    const res = await fetch('/api/categories', { headers: getHeaders() })
    if (res.ok) {
      const data = await res.json()
      categories.value = data
      if (data.length > 0 && !form.value.category_name) {
        form.value.category_name = data[0].name
      }
    }
  } catch (err) {
    console.error('Error al cargar categorías:', err)
  } finally {
    loadingCategories.value = false
  }
}

const syncJmsNodes = async () => {
  syncingJms.value = true
  try {
    const res = await fetch('/api/categories/sync-jms-nodes', {
      method: 'POST',
      headers: getHeaders()
    })
    if (res.ok) {
      const data = await res.json()
      showToast(`Nodos sincronizados con JumpServer (${data.total_categories} categorías activas)`)
      await fetchCategories()
    } else {
      showToast('Error al sincronizar categorías con JumpServer', 'error')
    }
  } catch (err) {
    showToast('Error de conexión al sincronizar nodos', 'error')
  } finally {
    syncingJms.value = false
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
      showToast(`${kiosk.name} accesible (HTTP ${data.status_code} en ${data.latency_ms}ms)`)
    } else {
      showToast(`${kiosk.name} inaccesible: ${data.error}`, 'error')
    }
  } catch (err) {
    urlTestResults.value[kiosk.id] = { testing: false, ok: false, error: 'Sonda fallida' }
    showToast(`Error de prueba para ${kiosk.name}`, 'error')
  }
}

const testAllConnectivity = async () => {
  showActionsDropdown.value = false
  showToast('Iniciando prueba de conectividad en todos los quioscos...')
  for (const k of kiosks.value) {
    testConnectivity(k)
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
    editUrlTestResult.value = { ok: false, error: 'Error de red al probar URL' }
  } finally {
    editUrlTesting.value = false
  }
}

const clearCache = async (kiosk) => {
  if (!confirm(`¿Desea limpiar caché, cookies y sesiones de "${kiosk.name}"?`)) {
    return
  }
  try {
    const res = await fetch(`/api/kiosks/${kiosk.id}/clear-cache`, {
      method: 'POST',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast(`Caché limpiada para ${kiosk.name}`)
      fetchKiosks()
    } else {
      showToast('Error al limpiar caché', 'error')
    }
  } catch (err) {
    showToast('Error enviando comando de limpieza', 'error')
  }
}

const restartKiosk = async (id, name) => {
  try {
    const res = await fetch(`/api/kiosks/${id}/restart`, {
      method: 'POST',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast(`Reinicio iniciado para ${name || 'el quiosco'}`)
      fetchKiosks()
    } else {
      showToast('Fallo al reiniciar contenedor', 'error')
    }
  } catch (err) {
    showToast('Error al enviar comando de reinicio', 'error')
  }
}

const deleteKiosk = async (id, name) => {
  if (!confirm(`¿Confirma eliminar el quiosco "${name}"? Esta acción eliminará el contenedor Docker y el activo en JumpServer.`)) {
    return
  }
  try {
    const res = await fetch(`/api/kiosks/${id}`, {
      method: 'DELETE',
      headers: getHeaders()
    })
    if (res.ok) {
      showToast(`Quiosco "${name}" eliminado correctamente`)
      fetchKiosks()
    } else {
      showToast('Error al eliminar quiosco', 'error')
    }
  } catch (err) {
    showToast('Error de red al eliminar quiosco', 'error')
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

// --- Computed & Filters ---
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
    // Text search
    const q = searchQuery.value.toLowerCase().trim()
    const matchSearch = !q ||
      k.name.toLowerCase().includes(q) ||
      (k.target_url && k.target_url.toLowerCase().includes(q)) ||
      (k.target_ip && k.target_ip.toLowerCase().includes(q)) ||
      (k.rdp_username && k.rdp_username.toLowerCase().includes(q)) ||
      (k.category_name && k.category_name.toLowerCase().includes(q)) ||
      (k.jms_node_name && k.jms_node_name.toLowerCase().includes(q))

    // Device type filter
    const matchType = selectedTypeFilter.value === 'all' || k.device_type === selectedTypeFilter.value

    // Status filter
    const matchStatus = selectedStatusFilter.value === 'all' ||
      (selectedStatusFilter.value === 'running' && k.container_status === 'running') ||
      (selectedStatusFilter.value === 'idle' && k.container_status !== 'running')

    // Category filter
    const deviceDef = deviceTypes.find(d => d.id === k.device_type)
    const matchCategory = selectedCategoryFilter.value === 'all' ||
      (k.category_name && k.category_name.toLowerCase() === selectedCategoryFilter.value.toLowerCase()) ||
      (k.jms_node_name && k.jms_node_name.toLowerCase() === selectedCategoryFilter.value.toLowerCase()) ||
      (deviceDef && deviceDef.category === selectedCategoryFilter.value)

    return matchSearch && matchType && matchStatus && matchCategory
  })
})

// --- Modern Utilities & Theme Management ---
// 1. Theme State (Dark / Light)
const isDarkMode = ref(false)

const applyTheme = (theme) => {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem('kiosk_theme', theme)
  const meta = document.querySelector('meta[name="color-scheme"]')
  if (meta) meta.content = theme
}

const toggleTheme = () => {
  isDarkMode.value = !isDarkMode.value
  const theme = isDarkMode.value ? 'dark' : 'light'
  applyTheme(theme)
  showToast(isDarkMode.value ? 'Modo oscuro activado 🌙' : 'Modo claro activado ☀️')
}

const initTheme = () => {
  const currentAttr = document.documentElement.getAttribute('data-theme')
  if (currentAttr) {
    isDarkMode.value = currentAttr === 'dark'
  } else {
    const saved = localStorage.getItem('kiosk_theme')
    if (saved) {
      isDarkMode.value = saved === 'dark'
    } else {
      isDarkMode.value = window.matchMedia('(prefers-color-scheme: dark)').matches
    }
  }
  applyTheme(isDarkMode.value ? 'dark' : 'light')
}

// 2. Auto-Refresh with visual countdown (0 = off, 15s, 30s, 60s)
const autoRefreshInterval = ref(Number(localStorage.getItem('kiosk_autorefresh')) || 0)
const refreshCountdown = ref(autoRefreshInterval.value)
let autoRefreshTimer = null

const cycleAutoRefresh = () => {
  const intervals = [0, 15, 30, 60]
  const currentIndex = intervals.indexOf(autoRefreshInterval.value)
  const nextInterval = intervals[(currentIndex + 1) % intervals.length]
  setAutoRefresh(nextInterval)
}

const setAutoRefresh = (seconds) => {
  autoRefreshInterval.value = seconds
  refreshCountdown.value = seconds
  localStorage.setItem('kiosk_autorefresh', seconds)
  resetAutoRefreshTimer()
  if (seconds > 0) {
    showToast(`Auto-refresco activado cada ${seconds}s`)
  } else {
    showToast('Auto-refresco desactivado')
  }
}

const resetAutoRefreshTimer = () => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
  if (autoRefreshInterval.value > 0) {
    refreshCountdown.value = autoRefreshInterval.value
    autoRefreshTimer = setInterval(() => {
      if (refreshCountdown.value > 1) {
        refreshCountdown.value--
      } else {
        refreshCountdown.value = autoRefreshInterval.value
        fetchKiosks(false) // Silent background poll
      }
    }, 1000)
  }
}

// 3. Quick Copy RDP Endpoint
const copiedKioskId = ref(null)

const copyRdpDetails = async (kiosk) => {
  const host = window.location.hostname || '127.0.0.1'
  const endpoint = `${host}:${kiosk.rdp_port}`
  try {
    await navigator.clipboard.writeText(endpoint)
    copiedKioskId.value = kiosk.id
    showToast(`Punto de conexión RDP copiado: ${endpoint}`)
    setTimeout(() => {
      if (copiedKioskId.value === kiosk.id) copiedKioskId.value = null
    }, 2500)
  } catch (err) {
    showToast(`Error al copiar al portapapeles: ${endpoint}`, 'error')
  }
}

// 4. Export Inventory to JSON / CSV
const exportInventory = (format = 'csv') => {
  showActionsDropdown.value = false
  const list = filteredKiosks.value
  if (!list.length) {
    showToast('No hay quioscos para exportar con los filtros actuales', 'error')
    return
  }

  const dateStr = new Date().toISOString().slice(0, 10)
  if (format === 'json') {
    const dataStr = JSON.stringify(list, null, 2)
    const blob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `jumpserver_kiosks_${dateStr}.json`
    a.click()
    URL.revokeObjectURL(url)
    showToast(`Exportados ${list.length} quioscos a JSON`)
  } else {
    const headers = ['Nombre', 'Tipo', 'IP', 'Protocolo', 'Puerto', 'URL', 'Puerto RDP', 'Usuario RDP', 'Estado Contenedor', 'ID Activo JumpServer']
    const rows = list.map(k => [
      `"${(k.name || '').replace(/"/g, '""')}"`,
      `"${k.device_type || 'generic'}"`,
      `"${k.target_ip || ''}"`,
      `"${k.target_protocol || 'http'}"`,
      `"${k.target_port || 80}"`,
      `"${(k.target_url || '').replace(/"/g, '""')}"`,
      `"${k.rdp_port || ''}"`,
      `"${k.rdp_username || ''}"`,
      `"${k.container_status || 'standby'}"`,
      `"${k.jms_asset_id || ''}"`
    ])
    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\r\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `jumpserver_kiosks_${dateStr}.csv`
    a.click()
    URL.revokeObjectURL(url)
    showToast(`Exportados ${list.length} quioscos a CSV`)
  }
}

// 5. Table Density Toggle ('normal' | 'compact')
const tableDensity = ref(localStorage.getItem('kiosk_density') || 'normal')

const toggleTableDensity = () => {
  tableDensity.value = tableDensity.value === 'normal' ? 'compact' : 'normal'
  localStorage.setItem('kiosk_density', tableDensity.value)
  showToast(tableDensity.value === 'compact' ? 'Vista compacta activada' : 'Vista cómoda activada')
}

// Keyboard shortcuts (Ctrl+K or /, Escape)
const handleKeydown = (e) => {
  if ((e.ctrlKey && e.key.toLowerCase() === 'k') || (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA')) {
    e.preventDefault()
    searchInputRef.value?.focus()
  } else if (e.key === 'Escape') {
    if (showCreateModal.value) showCreateModal.value = false
    else if (showEditModal.value) showEditModal.value = false
    else if (showSettingsModal.value) showSettingsModal.value = false
    else if (showActionsDropdown.value) showActionsDropdown.value = false
    else if (showUserDropdown.value) showUserDropdown.value = false
    else if (searchQuery.value) searchQuery.value = ''
  }
}

// Sidebar item selection
const selectSidebar = (item) => {
  activeSidebarItem.value = item
  if (item === 'dashboard') {
    showStatsPanel.value = true
    selectedStatusFilter.value = 'all'
  } else if (item === 'active_sessions') {
    showStatsPanel.value = false
    selectedStatusFilter.value = 'running'
  } else if (item === 'idle_sessions') {
    showStatsPanel.value = false
    selectedStatusFilter.value = 'idle'
  } else {
    showStatsPanel.value = false
    selectedStatusFilter.value = 'all'
    selectedTypeFilter.value = 'all'
    selectedCategoryFilter.value = 'all'
  }
}

const systemThemeMediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
const onSystemThemeChange = (e) => {
  if (!localStorage.getItem('kiosk_theme')) {
    isDarkMode.value = e.matches
    applyTheme(e.matches ? 'dark' : 'light')
  }
}

onMounted(() => {
  initTheme()
  fetchKiosks()
  fetchCategories()
  fetchSettings()
  resetAutoRefreshTimer()
  window.addEventListener('keydown', handleKeydown)
  systemThemeMediaQuery.addEventListener('change', onSystemThemeChange)
})

onUnmounted(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
  window.removeEventListener('keydown', handleKeydown)
  systemThemeMediaQuery.removeEventListener('change', onSystemThemeChange)
})
</script>

<template>
  <div class="jms-app-container">
    <!-- TOP NAVBAR (Milicic Official Dark Slate #2A343D Bar with White Logo) -->
    <header class="jms-navbar">
      <div class="jms-navbar-left">
        <!-- Milicic Brand + JumpServer Integration -->
        <div class="jms-brand-group">
          <!-- Official Milicic Logo in White (Matching Website) -->
          <div class="milicic-brand-wrap" title="Milicic S.A. Construcciones y Servicios">
            <MilicicLogo height="24" :white="true" />
          </div>

          <span class="jms-brand-divider">|</span>

          <!-- JumpServer Hexagonal Icon -->
          <div class="jms-logo-icon" title="JumpServer Enterprise PAM">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
          </div>
          <span class="jms-brand-title">Kiosk Manager</span>

          <span class="jms-brand-badge">PAM RDP</span>
        </div>
      </div>

      <!-- Center Global Search Input (Ctrl+K) -->
      <div class="jms-navbar-center">
        <div class="jms-global-search">
          <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input 
            ref="searchInputRef"
            v-model="searchQuery" 
            placeholder="Buscar quioscos, IP o URL..." 
            class="search-input"
          />
          <span class="search-kbd">Ctrl+K</span>
        </div>
      </div>

      <!-- Right Actions & User Profile -->
      <div class="jms-navbar-right">
        <!-- Active Sessions Notification Bell with Milicic Orange Badge -->
        <div class="jms-nav-btn" :title="`${activeSessionsCount} sesiones activas en ejecución`" @click="selectSidebar('active_sessions')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          <span v-if="activeSessionsCount > 0" class="badge-counter">{{ activeSessionsCount }}</span>
        </div>

        <!-- Luna Web Terminal Direct Link -->
        <a href="/luna/" target="_blank" class="jms-nav-btn" title="Abrir Consola JumpServer Luna">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </a>

        <!-- Settings Modal Trigger -->
        <div class="jms-nav-btn" title="Ajustes del Sistema & Políticas de Sesión" @click="openSettingsModal">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </div>

        <!-- Theme Toggle (Sol / Luna) -->
        <div 
          class="jms-nav-btn theme-toggle-btn" 
          :title="isDarkMode ? 'Cambiar a Modo Claro (Sol)' : 'Cambiar a Modo Oscuro (Luna)'" 
          @click="toggleTheme"
        >
          <svg v-if="isDarkMode" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/>
            <line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        </div>

        <!-- Documentation / Help -->
        <a href="/guia-usuario.html" target="_blank" class="jms-nav-btn" title="Guía de Usuario y Documentación">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </a>

        <!-- Language Selector -->
        <div class="jms-lang-selector">
          <span>Español</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>

        <!-- User Profile Pill -->
        <div class="jms-user-profile" @click="showUserDropdown = !showUserDropdown">
          <div class="jms-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </div>
          <span class="jms-username">{{ authCredentials.user }}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"/>
          </svg>

          <!-- Dropdown -->
          <div v-if="showUserDropdown" class="user-dropdown-menu" @click.stop>
            <div class="dropdown-item" @click="toggleTheme(); showUserDropdown = false">
              <span v-if="isDarkMode">☀️ Modo Claro</span>
              <span v-else>🌙 Modo Oscuro</span>
            </div>
            <div class="dropdown-item" @click="openSettingsModal(); showUserDropdown = false">
              ⚙️ Ajustes y Políticas
            </div>
            <a href="/guia-usuario.html" target="_blank" class="dropdown-item">
              📖 Manual de Usuario
            </a>
            <a href="/manual_instalacion_kiosk_manager.html" target="_blank" class="dropdown-item">
              🚀 Manual de Despliegue
            </a>
            <div class="dropdown-divider"></div>
            <div class="dropdown-item danger" @click="authCredentials.user = ''; authCredentials.pass = ''; saveCredentials()">
              🚪 Salir
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Toast Alerts -->
    <transition name="fade">
      <div v-if="notification" :class="['jms-toast', notification.type]">
        <span v-if="notification.type === 'success'">✅</span>
        <span v-else>⚠️</span>
        <span>{{ notification.msg }}</span>
      </div>
    </transition>

    <!-- BODY CONTAINER (Sidebar + Main Content) -->
    <div class="jms-main-body">
      <!-- LEFT SIDEBAR MENU -->
      <aside class="jms-sidebar">
        <!-- Consola Section Header -->
        <div class="sidebar-header">
          <span class="sidebar-title">Consola</span>
          <div class="sidebar-toggle-btn" title="Alternar panel">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="17 1 21 5 17 9"/>
              <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
              <polyline points="7 23 3 19 7 15"/>
              <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
            </svg>
          </div>
        </div>

        <!-- Sidebar Navigation List -->
        <nav class="sidebar-nav">
          <div class="nav-section-title">GESTIÓN DE QUIOSCOS</div>

          <div 
            :class="['nav-item', { active: activeSidebarItem === 'dashboard' }]" 
            @click="selectSidebar('dashboard')"
          >
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7"/>
              <rect x="14" y="3" width="7" height="7"/>
              <rect x="14" y="14" width="7" height="7"/>
              <rect x="3" y="14" width="7" height="7"/>
            </svg>
            <span>Panel de control</span>
          </div>

          <div 
            :class="['nav-item', { active: activeSidebarItem === 'kiosks' }]" 
            @click="selectSidebar('kiosks')"
          >
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
            <span>Lista de quioscos</span>
            <span class="nav-badge">{{ kiosks.length }}</span>
          </div>

          <div 
            :class="['nav-item', { active: activeSidebarItem === 'active_sessions' }]" 
            @click="selectSidebar('active_sessions')"
          >
            <svg class="nav-icon active-green" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            <span>Sesiones activas</span>
            <span v-if="activeSessionsCount > 0" class="nav-badge orange">{{ activeSessionsCount }}</span>
          </div>

          <div 
            :class="['nav-item', { active: activeSidebarItem === 'idle_sessions' }]" 
            @click="selectSidebar('idle_sessions')"
          >
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
            <span>En espera (0% RAM)</span>
            <span class="nav-badge gray">{{ standbyCount }}</span>
          </div>

          <div class="nav-section-title">GESTIÓN DE ACTIVOS</div>

          <a href="/luna/" target="_blank" class="nav-item">
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            <span>Consola Luna PAM</span>
          </a>

          <div 
            :class="['nav-item', { active: selectedCategoryFilter === 'network' }]" 
            @click="selectedCategoryFilter = selectedCategoryFilter === 'network' ? 'all' : 'network'; activeSidebarItem = 'network'"
          >
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <span>Equipos de red</span>
          </div>

          <div class="nav-section-title">SISTEMA Y AYUDA</div>

          <a href="/guia-usuario.html" target="_blank" class="nav-item">
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
            </svg>
            <span>Guía de usuario</span>
          </a>

          <a href="/manual_instalacion_kiosk_manager.html" target="_blank" class="nav-item">
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            <span>Manual de despliegue</span>
          </a>

          <div class="nav-item" @click="openSettingsModal">
            <svg class="nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>Ajustes & Políticas</span>
          </div>
        </nav>
      </aside>

      <!-- MAIN WORKSPACE CONTENT -->
      <main class="jms-content">
        <!-- Breadcrumbs & Navigation Bar -->
        <div class="jms-content-header">
          <div class="content-title-row">
            <div class="title-left">
              <button class="back-btn" title="Restablecer filtros" @click="selectedTypeFilter = 'all'; selectedStatusFilter = 'all'; selectedCategoryFilter = 'all'">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <line x1="19" y1="12" x2="5" y2="12"/>
                  <polyline points="12 19 5 12 12 5"/>
                </svg>
              </button>
              <h2>Gestión de Quioscos RDP</h2>
            </div>

            <!-- Header Action Links -->
            <div class="title-actions">
              <a href="/guia-usuario.html" target="_blank" class="link-btn">
                📖 Manual de usuario
              </a>
              <a href="/manual_instalacion_kiosk_manager.html" target="_blank" class="link-btn">
                🚀 Despliegue
              </a>
              <a href="/luna/" target="_blank" class="link-btn">
                🖥️ Acceso a Luna
              </a>
            </div>
          </div>

          <!-- Horizontal Category Tabs -->
          <div class="jms-tabs">
            <button 
              :class="['tab-item', { active: activeTab === 'normal' }]"
              @click="activeTab = 'normal'; showStatsPanel = false"
            >
              Quioscos activos
            </button>
            <button 
              :class="['tab-item', { active: activeTab === 'luna' }]"
              @click="activeTab = 'luna'; showStatsPanel = false"
            >
              Sesiones Luna
              <span class="tab-info-icon" title="Acceso directo a sesiones RDP Luna">ⓘ</span>
            </button>
            <button 
              :class="['tab-item', { active: activeTab === 'stats' }]"
              @click="activeTab = 'stats'; showStatsPanel = true"
            >
              Métricas de ahorro & RAM
            </button>
          </div>
        </div>

        <!-- STAT CARDS BANNER (Milicic Circular Achievements Design Style) -->
        <div v-if="showStatsPanel || activeTab === 'stats'" class="milicic-stats-grid">
          <div class="milicic-stat-card">
            <div class="milicic-circle-badge">
              <span class="circle-number">{{ kiosks.length }}</span>
            </div>
            <span class="stat-main-label">Activos Totales</span>
            <span class="stat-sub-label">Dispositivos web registrados</span>
          </div>

          <div class="milicic-stat-card highlight">
            <div class="milicic-circle-badge orange">
              <span class="circle-number">{{ activeSessionsCount }}</span>
            </div>
            <span class="stat-main-label">Sesiones Activas</span>
            <span class="stat-sub-label">{{ activeSessionsCount }} contenedores en ejecución</span>
          </div>

          <div class="milicic-stat-card">
            <div class="milicic-circle-badge">
              <span class="circle-number">{{ ramSavedGb }}</span>
            </div>
            <span class="stat-main-label">RAM Ahorrada (GB)</span>
            <span class="stat-sub-label">{{ standbyCount }} quioscos en espera (0% RAM)</span>
          </div>

          <div class="milicic-stat-card">
            <div class="milicic-circle-badge">
              <span class="circle-number">{{ kiosks.length }}/30</span>
            </div>
            <span class="stat-main-label">Puertos RDP</span>
            <span class="stat-sub-label">Pool asignado :33891 - :33920</span>
          </div>
        </div>

        <!-- MAIN TABLE PANEL (Full Width) -->
        <div class="jms-table-panel">
          <!-- QUICK FILTER ROWS (ESTADO, TIPO) -->
          <div class="jms-quick-filters">
            <div class="filter-row">
              <span class="filter-row-label">ESTADO DE SESIÓN</span>
              <div class="filter-links">
                <button 
                  :class="['filter-link', { active: selectedStatusFilter === 'all' }]"
                  @click="selectedStatusFilter = 'all'"
                >
                  Todo
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedStatusFilter === 'running' }]"
                  @click="selectedStatusFilter = 'running'"
                >
                  Activos en sesión ({{ activeSessionsCount }})
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedStatusFilter === 'idle' }]"
                  @click="selectedStatusFilter = 'idle'"
                >
                  En espera (0% RAM) ({{ standbyCount }})
                </button>
              </div>
            </div>

            <div class="filter-row">
              <span class="filter-row-label">TIPO DE DISPOSITIVO</span>
              <div class="filter-links">
                <button 
                  :class="['filter-link', { active: selectedCategoryFilter === 'all' && selectedTypeFilter === 'all' }]"
                  @click="selectedCategoryFilter = 'all'; selectedTypeFilter = 'all'"
                >
                  Todo
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedCategoryFilter === 'web' }]"
                  @click="selectedCategoryFilter = selectedCategoryFilter === 'web' ? 'all' : 'web'; selectedTypeFilter = 'all'"
                >
                  Web Consoles
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedCategoryFilter === 'network' }]"
                  @click="selectedCategoryFilter = selectedCategoryFilter === 'network' ? 'all' : 'network'; selectedTypeFilter = 'all'"
                >
                  Equipos de red
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedCategoryFilter === 'monitoring' }]"
                  @click="selectedCategoryFilter = selectedCategoryFilter === 'monitoring' ? 'all' : 'monitoring'; selectedTypeFilter = 'all'"
                >
                  Monitorización & CCTV
                </button>
                <span class="filter-sep">|</span>
                <button 
                  :class="['filter-link', { active: selectedCategoryFilter === 'virtualization' }]"
                  @click="selectedCategoryFilter = selectedCategoryFilter === 'virtualization' ? 'all' : 'virtualization'; selectedTypeFilter = 'all'"
                >
                  Virtualización & Servidores
                </button>
              </div>
            </div>
          </div>

          <!-- ACTION TOOLBAR (Milicic Orange Button + Tools) -->
          <div class="jms-toolbar">
            <div class="toolbar-left">
              <!-- + Crear Button (Milicic Orange) -->
              <button class="jms-btn jms-btn-primary" @click="showCreateModal = true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                Crear Quiosco
              </button>

              <!-- Refrescar Button -->
              <button class="jms-btn jms-btn-default" @click="fetchKiosks(true)" :disabled="loading">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'spinning': loading }">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                </svg>
                Refrescar
              </button>

              <!-- Auto-Refresh Toggle Button -->
              <button 
                :class="['auto-refresh-badge', { active: autoRefreshInterval > 0 }]"
                @click="cycleAutoRefresh"
                :title="autoRefreshInterval > 0 ? `Auto-refresco cada ${autoRefreshInterval}s (próximo en ${refreshCountdown}s). Clic para cambiar.` : 'Clic para activar auto-refresco (15s, 30s, 60s)'"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'spinning': autoRefreshInterval > 0 && refreshCountdown <= 1 }">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                <span v-if="autoRefreshInterval === 0">Auto: Off</span>
                <span v-else>Auto: {{ refreshCountdown }}s</span>
              </button>

              <!-- Más acciones ▾ Dropdown -->
              <div class="dropdown-wrapper">
                <button class="jms-btn jms-btn-default" @click="showActionsDropdown = !showActionsDropdown">
                  Más acciones
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>

                <div v-if="showActionsDropdown" class="toolbar-dropdown-menu" @click.stop>
                  <div class="dropdown-menu-item" @click="testAllConnectivity">
                    ⚡ Probar conectividad de todas las URLs
                  </div>
                  <div class="dropdown-menu-item" @click="exportInventory('csv')">
                    📥 Exportar inventario (CSV)
                  </div>
                  <div class="dropdown-menu-item" @click="exportInventory('json')">
                    📋 Exportar inventario (JSON)
                  </div>
                  <div class="dropdown-divider"></div>
                  <a href="/luna/" target="_blank" class="dropdown-menu-item">
                    🖥️ Abrir consola JumpServer Luna
                  </a>
                  <div class="dropdown-menu-item" @click="showStatsPanel = !showStatsPanel; showActionsDropdown = false">
                    📊 Alternar métricas de ahorro
                  </div>
                </div>
              </div>
            </div>

            <!-- Toolbar Right: Search Box + Tools -->
            <div class="toolbar-right">
              <div class="table-search-box">
                <svg class="search-tag-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
                  <line x1="7" y1="7" x2="7.01" y2="7"/>
                </svg>
                <input 
                  v-model="searchQuery" 
                  placeholder="Ingresa / o Ctrl+K..."
                  class="toolbar-search-input"
                />
                <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''">×</button>
              </div>

              <div class="toolbar-tool-icons">
                <!-- Density toggle button (Normal / Compact) -->
                <button 
                  class="icon-tool-btn" 
                  :title="tableDensity === 'compact' ? 'Cambiar a Vista Cómoda' : 'Cambiar a Vista Compacta'" 
                  @click="toggleTableDensity"
                >
                  <svg v-if="tableDensity === 'compact'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="6" x2="21" y2="6"/>
                    <line x1="3" y1="12" x2="21" y2="12"/>
                    <line x1="3" y1="18" x2="21" y2="18"/>
                  </svg>
                  <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="4" x2="21" y2="4"/>
                    <line x1="3" y1="9" x2="21" y2="9"/>
                    <line x1="3" y1="15" x2="21" y2="15"/>
                    <line x1="3" y1="20" x2="21" y2="20"/>
                  </svg>
                </button>

                <!-- Filter running toggle -->
                <button 
                  :class="['icon-tool-btn', { active: selectedStatusFilter === 'running' }]" 
                  title="Filtrar activos en ejecución" 
                  @click="selectedStatusFilter = selectedStatusFilter === 'all' ? 'running' : 'all'"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
                  </svg>
                </button>

                <!-- Settings -->
                <button class="icon-tool-btn" title="Ajustes y Políticas" @click="openSettingsModal">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <!-- ASSETS TABLE -->
          <div class="table-scroll-container">
            <table :class="['jms-data-table', tableDensity]">
              <thead>
                <tr>
                  <th style="width: 40px; text-align: center;">
                    <input type="checkbox" />
                  </th>
                  <th>Activos</th>
                  <th>Categoría / Nodo JMS</th>
                  <th>Plataforma</th>
                  <th>Conexión</th>
                  <th>Estado Contenedor</th>
                  <th>Latencia / URL</th>
                  <th style="text-align: right; width: 220px;">Operaciones</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="filteredKiosks.length === 0 && !loading">
                  <td colspan="8" class="empty-cell">
                    <div class="empty-state-box">
                      <span class="empty-icon">🔍</span>
                      <p class="empty-text">No se encontraron quioscos para los filtros seleccionados.</p>
                    </div>
                  </td>
                </tr>

                <tr v-for="k in filteredKiosks" :key="k.id" class="table-row">
                  <!-- Checkbox -->
                  <td style="text-align: center;">
                    <input type="checkbox" />
                  </td>

                  <!-- Activos (Name & Sub-identity) -->
                  <td class="cell-asset">
                    <div class="asset-info">
                      <a href="javascript:void(0)" class="asset-name" @click="openLunaSession(k)">
                        {{ k.name }}
                      </a>
                      <div class="asset-sub">
                        <span class="rdp-user">{{ k.rdp_username }}</span>
                        <span v-if="k.jms_asset_id" class="asset-id-tag">ID: {{ k.jms_asset_id.substring(0, 8) }}</span>
                      </div>
                    </div>
                  </td>

                  <!-- Categoría / Nodo JMS (RBAC Badge) -->
                  <td class="cell-category">
                    <div class="category-node-badge" :title="'Nodo JumpServer: ' + (k.category_name || k.jms_node_name || 'SWITCHES ROSARIO') + ' (Herencia de permisos RBAC en Luna)'">
                      <span class="category-icon">📁</span>
                      <span class="category-label">{{ k.category_name || k.jms_node_name || 'SWITCHES ROSARIO' }}</span>
                      <span class="rbac-tag" title="Herencia automática de permisos RBAC">RBAC</span>
                    </div>
                  </td>

                  <!-- Plataforma (Windows Icon & Badge) -->
                  <td class="cell-platform">
                    <div class="platform-badge">
                      <svg class="win-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.951-1.802"/>
                      </svg>
                      <span>Windows</span>
                    </div>
                  </td>

                  <!-- Conexión (Port Chip) -->
                  <td class="cell-connection">
                    <div class="connection-group">
                      <svg class="conn-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                        <line x1="8" y1="21" x2="16" y2="21"/>
                        <line x1="12" y1="17" x2="12" y2="21"/>
                      </svg>
                      <span class="port-chip">:{{ k.rdp_port }}</span>
                    </div>
                  </td>

                  <!-- Estado Contenedor (Active Green Pulse or Idle Moon) -->
                  <td class="cell-lifecycle">
                    <div v-if="k.container_status === 'running'" class="status-pill running">
                      <span class="pulse-indicator"></span>
                      <span>Activo (En Sesión)</span>
                    </div>
                    <div v-else class="status-pill idle" title="Ahorrando 768MB RAM. Se activa automáticamente al conectar.">
                      <span class="idle-moon">💤</span>
                      <span>En Espera (0% RAM)</span>
                    </div>
                  </td>

                  <!-- Latencia / URL Probe Status -->
                  <td class="cell-url">
                    <div class="url-info">
                      <a :href="k.target_url" target="_blank" rel="noopener" class="url-text" :title="k.target_url">
                        {{ k.target_url }}
                      </a>
                      <div class="probe-indicator">
                        <span v-if="urlTestResults[k.id]?.testing" class="probe-tag testing">
                          Probando...
                        </span>
                        <span v-else-if="urlTestResults[k.id]?.ok" class="probe-tag ok" :title="`HTTP ${urlTestResults[k.id]?.status_code}`">
                          HTTP {{ urlTestResults[k.id]?.status_code }} ({{ urlTestResults[k.id]?.latency_ms }}ms)
                        </span>
                        <span v-else-if="urlTestResults[k.id]?.error" class="probe-tag err" :title="urlTestResults[k.id]?.error">
                          Inaccesible
                        </span>
                      </div>
                    </div>
                  </td>

                  <!-- Operaciones (Action Buttons) -->
                  <td class="cell-actions" style="text-align: right;">
                    <div class="actions-group">
                      <!-- Conectar en Luna (Primary Eye Button) -->
                      <button class="action-btn action-connect" title="Abrir sesión en JumpServer Luna" @click="openLunaSession(k)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                          <circle cx="12" cy="12" r="3"/>
                        </svg>
                      </button>

                      <!-- Copiar Punto de Conexión RDP -->
                      <button 
                        class="action-btn" 
                        :class="{ 'copied': copiedKioskId === k.id }" 
                        :title="copiedKioskId === k.id ? '¡Punto de conexión RDP copiado!' : `Copiar conexión RDP (:puerto ${k.rdp_port})`" 
                        @click="copyRdpDetails(k)"
                      >
                        <svg v-if="copiedKioskId === k.id" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#38A169" stroke-width="2.8">
                          <polyline points="20 6 9 17 4 12"/>
                        </svg>
                        <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                      </button>

                      <!-- Probar Conectividad -->
                      <button class="action-btn" title="Probar conectividad de la URL" @click="testConnectivity(k)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                        </svg>
                      </button>

                      <!-- Editar -->
                      <button class="action-btn" title="Editar quiosco" @click="openEditModal(k)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                      </button>

                      <!-- Limpiar Caché -->
                      <button class="action-btn" title="Limpiar cookies y contraseñas guardadas de Chromium" @click="clearCache(k)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/>
                          <line x1="18" y1="9" x2="12" y2="15"/>
                          <line x1="12" y1="9" x2="18" y2="15"/>
                        </svg>
                      </button>

                      <!-- Reiniciar -->
                      <button class="action-btn" title="Reiniciar sesión / contenedor" @click="restartKiosk(k.id, k.name)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                        </svg>
                      </button>

                      <!-- Eliminar -->
                      <button class="action-btn danger" title="Eliminar quiosco y activo" @click="deleteKiosk(k.id, k.name)">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <polyline points="3 6 5 6 21 6"/>
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- TABLE PAGINATION FOOTER -->
          <div class="jms-pagination">
            <div class="pagination-total">
              Total {{ filteredKiosks.length }}
            </div>
            <div class="pagination-controls">
              <div class="page-size-selector">
                <span>15/página</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </div>
              <button class="page-btn" disabled>‹</button>
              <button class="page-btn active">1</button>
              <button class="page-btn" disabled>›</button>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- CREATE KIOSK MODAL -->
    <div v-if="showCreateModal" class="jms-modal-backdrop" @click.self="showCreateModal = false">
      <div class="jms-modal-dialog">
        <div class="modal-head">
          <div class="modal-head-title">
            <h3>Aprovisionar Nuevo Quiosco Web</h3>
            <p>Crea un contenedor RDP aislado y vincúlalo como activo en JumpServer</p>
          </div>
          <button class="modal-close-btn" @click="showCreateModal = false">&times;</button>
        </div>

        <form @submit.prevent="createKiosk" class="modal-body-form">
          <div class="form-item">
            <label class="form-label required">Nombre del Activo (JumpServer Asset)</label>
            <input v-model="form.name" placeholder="Ej: ROUTER-MIKROTIK o ZABBIX-LOCAL" required />
          </div>

          <div class="form-row">
            <div class="form-item flex-1">
              <label class="form-label required">Perfil / Tipo de Dispositivo</label>
              <select v-model="form.device_type">
                <option v-for="d in deviceTypes" :key="d.id" :value="d.id">
                  {{ d.icon }} {{ d.label }}
                </option>
              </select>
            </div>
            <div class="form-item flex-1">
              <label class="form-label required">Protocolo</label>
              <select v-model="form.target_protocol">
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-item flex-2">
              <label class="form-label required">Dirección IP del Dispositivo</label>
              <input v-model="form.target_ip" placeholder="192.168.1.10" required />
            </div>
            <div class="form-item flex-1">
              <label class="form-label required">Puerto</label>
              <input v-model.number="form.target_port" type="number" required />
            </div>
          </div>

          <div class="form-item">
            <label class="form-label">Ruta o URL Personalizada (Opcional)</label>
            <input v-model="form.target_url" placeholder="Ej: /zabbix/ o http://192.168.1.10:8080/ui" />
            <span class="field-hint">Si se deja en blanco, se generará como protocolo://ip:puerto automáticamente.</span>
          </div>

          <div class="form-item">
            <div class="category-label-row">
              <label class="form-label required">Categoría / Nodo JumpServer (RBAC)</label>
              <button type="button" class="btn-sync-node" @click="syncJmsNodes" :disabled="syncingJms" title="Sincronizar categorías con el árbol de activos en JumpServer">
                <span v-if="syncingJms">⏳ Sincronizando...</span>
                <span v-else>🔄 Sincronizar Nodos JMS</span>
              </button>
            </div>
            <select v-model="form.category_name" class="category-select" required>
              <option v-for="c in availableCategories" :key="c.name" :value="c.name">
                {{ c.icon || '📁' }} {{ c.name }}
              </option>
            </select>
            <div class="rbac-inheritance-hint" v-if="form.category_name">
              <span class="rbac-badge">
                <span class="rbac-icon">🛡️</span> Herencia RBAC Luna: <strong>{{ form.category_name }}</strong>
              </span>
              <span class="rbac-text">El dispositivo se integrará en este nodo de JumpServer. Los usuarios y grupos autorizados heredarán el acceso automáticamente.</span>
            </div>
          </div>

          <div class="modal-foot">
            <button type="button" class="jms-btn jms-btn-default" @click="showCreateModal = false">Cancelar</button>
            <button type="submit" class="jms-btn jms-btn-primary">Aprovisionar y Vincular</button>
          </div>
        </form>
      </div>
    </div>

    <!-- EDIT KIOSK MODAL -->
    <div v-if="showEditModal" class="jms-modal-backdrop" @click.self="showEditModal = false">
      <div class="jms-modal-dialog">
        <div class="modal-head">
          <div class="modal-head-title">
            <h3>Editar Quiosco Web</h3>
            <p>Modifica la URL de destino o el tipo de dispositivo</p>
          </div>
          <button class="modal-close-btn" @click="showEditModal = false">&times;</button>
        </div>

        <form @submit.prevent="saveKioskEdit" class="modal-body-form">
          <div class="form-item">
            <label class="form-label required">Nombre del Dispositivo</label>
            <input v-model="editForm.name" required />
          </div>

          <div class="form-item">
            <label class="form-label required">Perfil / Tipo de Dispositivo</label>
            <select v-model="editForm.device_type">
              <option v-for="d in deviceTypes" :key="d.id" :value="d.id">
                {{ d.icon }} {{ d.label }}
              </option>
            </select>
          </div>

          <div class="form-item">
            <div class="category-label-row">
              <label class="form-label required">Categoría / Nodo JumpServer (RBAC)</label>
              <button type="button" class="btn-sync-node" @click="syncJmsNodes" :disabled="syncingJms" title="Sincronizar categorías con el árbol de activos en JumpServer">
                <span v-if="syncingJms">⏳ Sincronizando...</span>
                <span v-else>🔄 Sincronizar</span>
              </button>
            </div>
            <select v-model="editForm.category_name" class="category-select" required>
              <option v-for="c in availableCategories" :key="c.name" :value="c.name">
                {{ c.icon || '📁' }} {{ c.name }}
              </option>
            </select>
            <div class="rbac-inheritance-hint" v-if="editForm.category_name">
              <span class="rbac-badge">
                <span class="rbac-icon">🛡️</span> Herencia RBAC Luna: <strong>{{ editForm.category_name }}</strong>
              </span>
              <span class="rbac-text">Al guardar, el activo se moverá a este nodo en JumpServer y heredará sus permisos.</span>
            </div>
          </div>

          <div class="form-item">
            <div class="label-with-test">
              <label class="form-label required">Target URL (URL Completa)</label>
              <button type="button" class="inline-test-btn" @click="testEditUrl" :disabled="editUrlTesting">
                <span v-if="editUrlTesting">Probando...</span>
                <span v-else>⚡ Probar Conectividad</span>
              </button>
            </div>
            <input v-model="editForm.target_url" placeholder="http://192.168.1.110/zabbix/" required />
            <span class="field-hint">Chromium abrirá exactamente esta URL en pantalla completa al iniciar la sesión RDP.</span>

            <div v-if="editUrlTestResult" :class="['inline-probe-alert', editUrlTestResult.ok ? 'ok' : 'err']">
              <span v-if="editUrlTestResult.ok">
                ✅ Conexión exitosa: Código HTTP {{ editUrlTestResult.status_code }} ({{ editUrlTestResult.latency_ms }}ms)
              </span>
              <span v-else>
                ❌ Error de conexión: {{ editUrlTestResult.error }}
              </span>
            </div>
          </div>

          <div class="modal-foot">
            <button type="button" class="jms-btn jms-btn-default" @click="showEditModal = false">Cancelar</button>
            <button type="submit" class="jms-btn jms-btn-primary">Guardar Cambios</button>
          </div>
        </form>
      </div>
    </div>

    <!-- SETTINGS / CREDENTIALS & POLICIES MODAL -->
    <div v-if="showSettingsModal" class="jms-modal-backdrop" @click.self="showSettingsModal = false">
      <div class="jms-modal-dialog jms-modal-dialog-lg">
        <div class="modal-head">
          <div class="modal-head-title">
            <h3>Ajustes del Sistema & Políticas de Sesión</h3>
            <p>Configura credenciales y límites temporales para optimización y ahorro de RAM</p>
          </div>
          <button class="modal-close-btn" @click="showSettingsModal = false">&times;</button>
        </div>

        <form @submit.prevent="saveAllSettings" class="modal-body-form">
          <!-- SECCIÓN 1: CREDENCIALES PORTAL -->
          <div class="settings-section">
            <h4 class="settings-section-title">🔑 Credenciales de Acceso al Portal</h4>
            <div class="form-row">
              <div class="form-item flex-1">
                <label class="form-label required">Usuario Administrador</label>
                <input v-model="authCredentials.user" required />
              </div>
              <div class="form-item flex-1">
                <label class="form-label required">Contraseña / Token</label>
                <input v-model="authCredentials.pass" type="password" required />
              </div>
            </div>
          </div>

          <!-- SECCIÓN 2: POLÍTICAS DE CICLO DE VIDA Y LIBERACIÓN DE MEMORIA -->
          <div class="settings-section">
            <div class="section-title-with-badge">
              <h4 class="settings-section-title">⏱️ Políticas de Ciclo de Vida y Liberación de RAM</h4>
              <span class="badge-saving">0% RAM en Reposo</span>
            </div>

            <!-- 1. Ventana de gracia tras desconexión -->
            <div class="form-item">
              <div class="label-with-calc">
                <label class="form-label required">Ventana de Gracia tras Desconexión (segundos)</label>
                <span class="calc-badge">Tolerancia F5 / red</span>
              </div>
              <input 
                v-model.number="lifecycleSettings.disconnect_grace_seconds" 
                type="number" 
                min="5" 
                max="3600" 
                required 
              />
              <span class="field-hint">
                Tiempo de espera antes de apagar el contenedor cuando el operador cierra la pestaña o pierde conexión (por defecto: 30s).
              </span>
            </div>

            <!-- 2. Inactividad por falta de tráfico -->
            <div class="form-item">
              <div class="label-with-calc">
                <label class="form-label required">Tiempo de Inactividad de Tráfico (segundos)</label>
                <span class="calc-badge">Equivale a {{ (lifecycleSettings.idle_timeout_seconds / 60).toFixed(1) }} min</span>
              </div>
              <input 
                v-model.number="lifecycleSettings.idle_timeout_seconds" 
                type="number" 
                min="30" 
                max="86400" 
                required 
              />
              <span class="field-hint">
                Cierra forzosamente la sesión y apaga el contenedor si no se detecta tráfico RDP en este lapso (por defecto: 900s / 15m).
              </span>
            </div>

            <!-- 3. Límite máximo continuo absoluto -->
            <div class="form-item">
              <div class="label-with-calc">
                <label class="form-label required">Límite Máximo Absoluto por Sesión (segundos)</label>
                <span class="calc-badge">Equivale a {{ (lifecycleSettings.max_session_lifetime_seconds / 3600).toFixed(1) }} h</span>
              </div>
              <input 
                v-model.number="lifecycleSettings.max_session_lifetime_seconds" 
                type="number" 
                min="60" 
                max="604800" 
                required 
              />
              <span class="field-hint">
                Límite máximo continuo ininterrumpido. Al cumplirse, se fuerza el cierre para liberar memoria RAM (por defecto: 14400s / 4h).
              </span>
            </div>

            <!-- 4. Límite de concurrencia máxima simultánea -->
            <div class="form-item">
              <div class="label-with-calc">
                <label class="form-label required">Límite de Concurrencia Simultánea (sesiones)</label>
                <span class="calc-badge">Protección RAM Host</span>
              </div>
              <input 
                v-model.number="lifecycleSettings.max_concurrent_sessions" 
                type="number" 
                min="1" 
                max="100" 
                required 
              />
              <span class="field-hint">
                Máximo de quioscos ejecutándose en simultáneo en el host. Previene saturación de RAM y caídas por OOM (por defecto: 4).
              </span>
            </div>
          </div>

          <div class="modal-foot">
            <button type="button" class="jms-btn jms-btn-default" @click="showSettingsModal = false" :disabled="savingSettings">
              Cancelar
            </button>
            <button type="submit" class="jms-btn jms-btn-primary" :disabled="savingSettings">
              <span v-if="savingSettings">Guardando...</span>
              <span v-else>Guardar Ajustes y Políticas</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Main App Structure */
.jms-app-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background-color: var(--jms-bg-page);
}

/* TOP NAVBAR (Milicic Dark Slate #2A343D) */
.jms-navbar {
  height: var(--header-height);
  background-color: var(--jms-header-bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  color: #ffffff;
  position: sticky;
  top: 0;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}

.jms-navbar-left {
  display: flex;
  align-items: center;
}

.jms-brand-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.milicic-brand-wrap {
  display: flex;
  align-items: center;
}

.jms-brand-divider {
  color: rgba(255, 255, 255, 0.25);
  font-weight: 300;
  font-size: 15px;
}

.jms-logo-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--milicic-orange);
}

.jms-brand-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #ffffff;
}

.jms-brand-badge {
  font-size: 10px;
  font-weight: 700;
  background: var(--milicic-orange);
  color: #ffffff;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Center Search */
.jms-navbar-center {
  flex: 1;
  max-width: 380px;
  margin: 0 24px;
}

.jms-global-search {
  position: relative;
  display: flex;
  align-items: center;
}

.jms-global-search .search-icon {
  position: absolute;
  left: 10px;
  color: rgba(255, 255, 255, 0.6);
  pointer-events: none;
}

.jms-global-search .search-input {
  width: 100%;
  height: 32px;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 0 54px 0 32px;
  color: #ffffff;
  font-size: 12px;
}

.jms-global-search .search-input::placeholder {
  color: rgba(255, 255, 255, 0.55);
}

.jms-global-search .search-input:focus {
  background: rgba(0, 0, 0, 0.35);
  border-color: var(--milicic-orange);
  box-shadow: 0 0 0 2px rgba(243, 146, 0, 0.3);
}

.search-kbd {
  position: absolute;
  right: 8px;
  font-size: 10px;
  background: rgba(255, 255, 255, 0.15);
  padding: 2px 5px;
  border-radius: 3px;
  color: #ffffff;
}

/* Right Nav Buttons */
.jms-navbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.jms-nav-btn {
  position: relative;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  transition: all 0.15s ease;
}

.jms-nav-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.badge-counter {
  position: absolute;
  top: 1px;
  right: 1px;
  background: var(--milicic-orange);
  color: white;
  font-size: 10px;
  font-weight: 700;
  min-width: 15px;
  height: 15px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
  border: 1px solid var(--jms-header-bg);
}

.jms-lang-selector {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.9);
}

.jms-lang-selector:hover {
  background: rgba(255, 255, 255, 0.12);
}

.jms-user-profile {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  color: #ffffff;
}

.jms-user-profile:hover {
  background: rgba(255, 255, 255, 0.12);
}

.jms-avatar {
  width: 26px;
  height: 26px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.jms-username {
  font-size: 13px;
  font-weight: 500;
}

.user-dropdown-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 6px;
  background: var(--jms-bg-white);
  color: var(--jms-text-primary);
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  min-width: 200px;
  padding: 6px 0;
  z-index: 1050;
}

.dropdown-item {
  padding: 9px 14px;
  font-size: 13px;
  cursor: pointer;
  display: block;
  color: var(--jms-text-regular);
  transition: all 0.15s;
}

.dropdown-item:hover {
  background: var(--milicic-orange-light);
  color: var(--milicic-orange);
}

.dropdown-item.danger {
  color: var(--jms-danger);
}

.dropdown-item.danger:hover {
  background: var(--jms-danger-light);
}

.dropdown-divider {
  height: 1px;
  background: var(--jms-border-extra-light);
  margin: 4px 0;
}

/* Toast */
.jms-toast {
  position: fixed;
  top: 66px;
  right: 20px;
  background: var(--jms-bg-white);
  color: var(--jms-text-primary);
  padding: 12px 18px;
  border-radius: 6px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 500;
  z-index: 2000;
  border-left: 4px solid var(--milicic-orange);
  border-top: 1px solid var(--jms-border-base);
  border-right: 1px solid var(--jms-border-base);
  border-bottom: 1px solid var(--jms-border-base);
}

.jms-toast.error {
  border-left-color: var(--jms-danger);
}

/* MAIN BODY (Sidebar + Content) */
.jms-main-body {
  display: flex;
  flex: 1;
}

/* SIDEBAR */
.jms-sidebar {
  width: var(--sidebar-width);
  background: var(--jms-bg-white);
  border-right: 1px solid var(--jms-border-base);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--jms-border-extra-light);
}

.sidebar-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--milicic-slate);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.sidebar-toggle-btn {
  color: var(--jms-text-secondary);
  cursor: pointer;
}

.sidebar-nav {
  padding: 12px 0;
  display: flex;
  flex-direction: column;
}

.nav-section-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--milicic-gray-light);
  padding: 12px 18px 4px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 18px;
  font-size: 13px;
  color: var(--milicic-gray);
  cursor: pointer;
  transition: all 0.15s;
  text-decoration: none;
}

.nav-item:hover {
  background-color: var(--jms-bg-hover);
  color: var(--milicic-dark);
}

/* Active Nav Item: Milicic Soft Orange Glow + Orange Indicator */
.nav-item.active {
  background-color: var(--milicic-orange-light);
  color: var(--milicic-orange);
  font-weight: 600;
  border-right: 3px solid var(--milicic-orange);
}

.nav-icon {
  color: inherit;
  flex-shrink: 0;
}

.nav-icon.active-green {
  color: var(--milicic-orange);
}

.nav-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--jms-border-extra-light);
  color: var(--jms-text-secondary);
}

.nav-badge.orange {
  background: var(--milicic-orange-light);
  color: var(--milicic-orange);
  font-weight: 700;
}

.nav-badge.gray {
  background: var(--jms-border-extra-light);
  color: var(--jms-text-secondary);
}

/* MAIN CONTENT AREA */
.jms-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 18px 24px;
  overflow-x: hidden;
}

/* Header & Breadcrumb */
.jms-content-header {
  background: var(--jms-bg-white);
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  padding: 16px 20px 0;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.content-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.title-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-btn {
  color: var(--milicic-gray);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  border-radius: 4px;
}

.back-btn:hover {
  background: var(--jms-bg-hover);
  color: var(--milicic-orange);
}

.title-left h2 {
  font-size: 17px;
  font-weight: 700;
  color: var(--milicic-dark);
}

.title-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.link-btn {
  font-size: 12px;
  font-weight: 500;
  color: var(--jms-text-regular);
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  padding: 5px 12px;
  background: var(--jms-bg-white);
  transition: all 0.15s ease;
}

.link-btn:hover {
  border-color: var(--milicic-orange);
  color: var(--milicic-orange);
}

/* Tabs */
.jms-tabs {
  display: flex;
  gap: 28px;
  border-bottom: 1px solid var(--jms-border-base);
}

.tab-item {
  font-size: 13px;
  font-weight: 500;
  color: var(--milicic-gray);
  padding: 10px 0;
  border-bottom: 2px solid transparent;
  display: flex;
  align-items: center;
  gap: 5px;
}

.tab-item:hover {
  color: var(--milicic-dark);
}

.tab-item.active {
  color: var(--milicic-orange);
  font-weight: 600;
  border-bottom-color: var(--milicic-orange);
}

.tab-info-icon {
  font-size: 12px;
  color: var(--jms-text-secondary);
}

/* MILICIC STATS GRID (Circular Achievements Design) */
.milicic-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.milicic-stat-card {
  background: var(--jms-bg-white);
  border: 1px solid var(--jms-border-base);
  border-radius: 8px;
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.2s ease;
}

.milicic-stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.milicic-stat-card.highlight {
  border-color: var(--milicic-orange-border);
  background: var(--jms-bg-white);
}

.milicic-circle-badge {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  border: 3px solid var(--milicic-orange);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  background: var(--milicic-orange-light);
}

.milicic-circle-badge.orange {
  background: var(--milicic-orange);
  border-color: var(--milicic-orange);
}

.milicic-circle-badge.orange .circle-number {
  color: #ffffff;
}

.circle-number {
  font-size: 1.55rem;
  font-weight: 800;
  color: var(--milicic-dark);
  letter-spacing: -0.02em;
}

.stat-main-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--milicic-dark);
  margin-bottom: 3px;
}

.stat-sub-label {
  font-size: 12px;
  color: var(--milicic-gray-light);
}

/* FULL-WIDTH TABLE PANEL */
.jms-table-panel {
  flex: 1;
  background: var(--jms-bg-white);
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* QUICK FILTERS ROWS */
.jms-quick-filters {
  padding: 14px 20px;
  border-bottom: 1px solid var(--jms-border-extra-light);
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 12px;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.filter-row-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--milicic-gray-light);
  width: 140px;
  flex-shrink: 0;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.filter-links {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-link {
  font-size: 12px;
  color: var(--milicic-gray);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.filter-link:hover {
  color: var(--milicic-orange);
}

.filter-link.active {
  color: var(--milicic-orange);
  background: var(--milicic-orange-light);
  font-weight: 700;
}

.filter-sep {
  color: var(--jms-border-base);
  font-size: 10px;
}

/* TOOLBAR */
.jms-toolbar {
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--jms-border-extra-light);
  background: var(--jms-bg-white);
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Auto-Refresh Badge */
.auto-refresh-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  border: 1px solid var(--jms-border-base);
  background-color: var(--jms-bg-white);
  color: var(--jms-text-regular);
  cursor: pointer;
  transition: all 0.2s ease;
}

.auto-refresh-badge:hover {
  border-color: var(--milicic-orange);
  color: var(--milicic-orange);
}

.auto-refresh-badge.active {
  background-color: var(--milicic-orange-light);
  border-color: var(--milicic-orange-border);
  color: var(--milicic-orange);
}

/* Milicic Styled Buttons */
.jms-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.jms-btn-primary {
  background-color: var(--milicic-orange);
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(243, 146, 0, 0.25);
}

.jms-btn-primary:hover {
  background-color: var(--milicic-orange-hover);
  box-shadow: 0 4px 10px rgba(243, 146, 0, 0.35);
  transform: translateY(-1px);
}

.jms-btn-default {
  background-color: var(--jms-bg-white);
  color: var(--jms-text-primary);
  border: 1px solid var(--jms-border-base);
}

.jms-btn-default:hover {
  color: var(--milicic-orange);
  border-color: var(--milicic-orange);
  background-color: var(--milicic-orange-light);
}

.dropdown-wrapper {
  position: relative;
}

.toolbar-dropdown-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 6px;
  background: var(--jms-bg-white);
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.15);
  min-width: 230px;
  z-index: 500;
  padding: 6px 0;
}

.dropdown-menu-item {
  padding: 8px 16px;
  font-size: 12px;
  color: var(--jms-text-regular);
  cursor: pointer;
  display: block;
}

.dropdown-menu-item:hover {
  background: var(--milicic-orange-light);
  color: var(--milicic-orange);
}

/* Toolbar Right */
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.table-search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.search-tag-icon {
  position: absolute;
  left: 9px;
  color: var(--jms-text-placeholder);
}

.toolbar-search-input {
  width: 200px;
  height: 32px;
  padding: 0 26px 0 28px;
  font-size: 12px;
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
}

.clear-btn {
  position: absolute;
  right: 8px;
  color: var(--jms-text-placeholder);
  font-size: 14px;
}

.toolbar-tool-icons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.icon-tool-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--jms-text-regular);
  background: var(--jms-bg-white);
  transition: all 0.15s;
}

.icon-tool-btn:hover {
  border-color: var(--milicic-orange);
  color: var(--milicic-orange);
}

.icon-tool-btn.active {
  background: var(--milicic-orange-light);
  border-color: var(--milicic-orange-border);
  color: var(--milicic-orange);
}

/* DATA TABLE */
.table-scroll-container {
  overflow-x: auto;
}

.jms-data-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.jms-data-table th {
  background: var(--jms-bg-table-header);
  color: var(--milicic-slate);
  font-size: 12px;
  font-weight: 700;
  padding: 12px 16px;
  border-bottom: 1px solid var(--jms-border-base);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.jms-data-table td {
  padding: 14px 16px;
  font-size: 13px;
  border-bottom: 1px solid var(--jms-border-extra-light);
  color: var(--milicic-gray);
}

.jms-data-table .table-row:hover {
  background-color: var(--jms-bg-hover);
}

/* Asset Cell */
.cell-asset .asset-name {
  font-weight: 700;
  color: var(--milicic-dark);
  font-size: 13px;
  transition: color 0.15s;
}

.cell-asset .asset-name:hover {
  color: var(--milicic-orange);
  text-decoration: underline;
}

.asset-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--milicic-gray-light);
  margin-top: 3px;
}

.asset-id-tag {
  background: var(--jms-bg-subtle);
  color: var(--jms-text-secondary);
  padding: 1px 5px;
  border-radius: 3px;
}

/* Platform Cell */
.platform-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--milicic-dark);
}

.win-icon {
  color: #0078d7;
}

/* Connection Cell */
.connection-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.conn-icon {
  color: var(--jms-text-secondary);
}

.port-chip {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  background: var(--milicic-orange-light);
  color: var(--milicic-orange);
  border: 1px solid var(--milicic-orange-border);
  padding: 2px 7px;
  border-radius: 4px;
}

/* Lifecycle Badges */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
}

.status-pill.running {
  background: var(--jms-success-light);
  color: var(--jms-success);
  font-weight: 600;
}

.status-pill.idle {
  background: var(--jms-bg-subtle);
  color: var(--jms-text-secondary);
}

.pulse-indicator {
  width: 8px;
  height: 8px;
  background: var(--jms-success);
  border-radius: 50%;
  animation: pulse-dot 1.5s infinite;
}

@keyframes pulse-dot {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(56, 161, 105, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 5px rgba(56, 161, 105, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(56, 161, 105, 0); }
}

/* Compact Table Density Mode */
.jms-data-table.compact th {
  padding: 7px 12px;
  font-size: 11px;
}

.jms-data-table.compact td {
  padding: 6px 12px;
  font-size: 12px;
}

.jms-data-table.compact .action-btn {
  width: 24px;
  height: 24px;
}

/* URL Cell */
.url-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 280px;
}

.url-text {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--jms-text-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.probe-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
}

.probe-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
}

.probe-tag.ok {
  background: var(--jms-success-light);
  color: var(--jms-success);
}

.probe-tag.testing {
  background: var(--jms-info-light);
  color: var(--jms-info);
}

.probe-tag.err {
  background: var(--jms-danger-light);
  color: var(--jms-danger);
}

/* Actions Group */
.actions-group {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
}

.action-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--jms-border-base);
  background: var(--jms-bg-white);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--jms-text-regular);
  transition: all 0.15s;
}

.action-btn:hover {
  border-color: var(--milicic-orange);
  color: var(--milicic-orange);
  background: var(--milicic-orange-light);
}

.action-btn.copied {
  border-color: var(--jms-success);
  background: var(--jms-success-light);
  color: var(--jms-success);
}

.action-btn.action-connect {
  background: var(--milicic-orange-light);
  border-color: var(--milicic-orange-border);
  color: var(--milicic-orange);
  font-weight: 600;
}

.action-btn.action-connect:hover {
  background: var(--milicic-orange);
  color: #ffffff;
}

.action-btn.danger:hover {
  border-color: var(--jms-danger);
  color: var(--jms-danger);
  background: var(--jms-danger-light);
}

/* Empty Cell */
.empty-cell {
  text-align: center;
  padding: 48px !important;
}

.empty-state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.empty-icon {
  font-size: 28px;
}

.empty-text {
  font-size: 13px;
  color: var(--milicic-gray-light);
}

/* PAGINATION FOOTER */
.jms-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--jms-border-base);
  font-size: 12px;
  color: var(--milicic-gray);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-size-selector {
  display: flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.page-btn {
  min-width: 26px;
  height: 26px;
  border: 1px solid var(--jms-border-base);
  border-radius: 6px;
  background: var(--jms-bg-white);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--jms-text-regular);
}

.page-btn.active {
  background: var(--milicic-orange);
  color: #ffffff;
  border-color: var(--milicic-orange);
  font-weight: 700;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* MODALS */
.jms-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 20, 26, 0.7);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 3000;
}

.jms-modal-dialog {
  background: var(--jms-bg-white);
  border: 1px solid var(--jms-border-base);
  border-radius: 8px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.4);
  width: 90%;
  max-width: 520px;
  overflow: hidden;
}

.jms-modal-dialog-lg {
  max-width: 600px;
}

.modal-head {
  padding: 18px 24px;
  border-bottom: 1px solid var(--jms-border-base);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  background: var(--jms-bg-subtle);
}

.modal-head-title h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--milicic-dark);
}

.modal-head-title p {
  font-size: 12px;
  color: var(--milicic-gray-light);
  margin-top: 3px;
}

.modal-close-btn {
  font-size: 22px;
  color: var(--milicic-gray-light);
  cursor: pointer;
  line-height: 1;
}

.modal-close-btn:hover {
  color: var(--milicic-dark);
}

.modal-body-form {
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 80vh;
  overflow-y: auto;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px dashed var(--jms-border-base);
}

.settings-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

.settings-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--milicic-dark);
  margin: 0;
}

.section-title-with-badge {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.badge-saving {
  font-size: 11px;
  font-weight: 700;
  color: var(--milicic-orange);
  background: var(--milicic-orange-light);
  padding: 3px 9px;
  border-radius: 4px;
  border: 1px solid var(--milicic-orange-border);
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: flex;
  gap: 14px;
}

.flex-1 { flex: 1; }
.flex-2 { flex: 2; }

.form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--milicic-dark);
}

.form-label.required::before {
  content: "* ";
  color: var(--milicic-orange);
}

.label-with-calc, .label-with-test {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.calc-badge {
  font-size: 11px;
  color: var(--milicic-orange);
  font-weight: 600;
  background: var(--milicic-orange-light);
  padding: 1px 7px;
  border-radius: 4px;
}

.inline-test-btn {
  font-size: 11px;
  color: var(--milicic-orange);
  font-weight: 700;
}

.field-hint {
  font-size: 11px;
  color: var(--milicic-gray-light);
}

.inline-probe-alert {
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-top: 4px;
}

.inline-probe-alert.ok {
  background: var(--jms-success-light);
  color: var(--jms-success);
}

.inline-probe-alert.err {
  background: var(--jms-danger-light);
  color: var(--jms-danger);
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--jms-border-base);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
