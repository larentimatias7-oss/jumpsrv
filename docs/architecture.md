# Guía de Arquitectura: JumpServer Kiosk Manager

## 1. Visión General

**JumpServer Kiosk Manager** resuelve la necesidad de conectar operadores a aplicaciones y consolas web de infraestructura crítica mediante **JumpServer Community Edition (v4.10.x CE)** sin requerir complementos comerciales Enterprise (Web Terminal).

Para lograr esto de forma segura, escalable y con mínimo impacto en recursos (especialmente en entornos Proxmox VE con contenedores LXC o máquinas virtuales), se implementó una **Arquitectura Efímera Bajo Demanda (Just-In-Time / Ephemeral On-Demand)**.

---

## 2. Componentes Clave de la Arquitectura

### A. RDP Dispatcher Asíncrono (`backend/app/dispatcher/service.py`)
- **Proxy TCP Transparente Asíncrono (`asyncio`):** El backend ejecuta en modo de red host (`network_mode: "host"`) y levanta un servidor TCP asíncrono para cada quiosco aprovisionado en el rango de puertos configurable `33891 - 34090` (hasta 200 quioscos).
- **Detección de Conexión (RDP-SYN):** Al recibir la primera solicitud de conexión desde `jms_lion` (Apache Guacamole):
  1. Consulta la base de datos local SQLite para obtener los metadatos del quiosco (`container_name`, `volume_name`, `target_url`, `rdp_username`, etc.).
  2. Arranca el contenedor Docker correspondiente de forma instantánea (`ensure_container_running`).
  3. Ejecuta un bucle de sondeo con backoff hacia la IP interna del contenedor (`172.17.0.x:3389`) hasta que XRDP esté completamente operativo y acepte tráfico.
  4. Conmuta bidireccionalmente los streams de red cliente <-> XRDP con liberación asíncrona inmediata (`asyncio.FIRST_COMPLETED`).
- **Políticas de Ciclo de Vida y Ahorro de RAM:**
  - **Ventana de Gracia tras Desconexión (`KIOSK_DISCONNECT_GRACE_SECONDS`, default 30s):** Cuando la sesión finaliza y no quedan conexiones activas (`active_connections == 0`), inicia un temporizador de gracia configurable antes de apagar el contenedor (`docker stop`) y cambiar el estado a `IDLE`. Tolera recargas de página (F5) o microcortes sin interrumpir el flujo.
  - **Watchdog de Inactividad de Tráfico (`KIOSK_IDLE_TIMEOUT_SECONDS`, default 900s / 15m):** Durante la sesión activa, si no se registra tráfico RDP bidireccional durante el periodo configurado, interrumpe la sesión forzando el cierre de sockets y liberando la memoria RAM.
  - **Límite Máximo Absoluto por Sesión (`KIOSK_MAX_SESSION_LIFETIME_SECONDS`, default 14400s / 4h):** Límite continuo absoluto. Al alcanzarse, fuerza la desconexión y detención del contenedor efímero, emitiendo log estructurado (`max_lifetime_exceeded`).
  - **Límite Preventivo de Concurrencia (`KIOSK_MAX_CONCURRENT_SESSIONS`, default 4):** Verifica la cantidad de contenedores simultáneos gestionados antes de iniciar un contenedor detenido; si se alcanza la cuota máxima, rechaza la nueva conexión RDP de manera preventiva para proteger al host de saturación de RAM u OOM kills.
- **Configuración Dinámica y Persistencia (`/api/settings`):** Los parámetros de ciclo de vida pueden ajustarse en vivo desde el panel web o API REST, persistiendo en la tabla `system_settings` de SQLite con actualización inmediata en el Dispatcher sin requerir reinicios del servicio.

### B. Contenedor Quiosco Aislado (`pam-web-kiosk:latest`)
- **Base:** Debian 12 (Bookworm) Slim.
- **Gestor de Pantalla:** XRDP + backend nativo `xorgxrdp` + servidor Xorg con aceleración por software optimizada.
- **Gestor de Ventanas:** `openbox` (ultraligero, consumo <20 MB RAM, sin barras de tareas ni menús contextuales).
- **Navegador Web:** Chromium en modo ventana maximizada (`--app="TARGET_URL"`, `--start-maximized`, `--disable-hang-monitor`).
- **Inyección de Entorno:** El script `entrypoint.sh` inyecta las variables del contenedor (`TARGET_URL`, `KIOSK_NAME`) en `/etc/environment`, permitiendo que la sesión PAM no privilegiada (`kiosk`) navegue directamente a la URL indicada sin intermediarios ni pantallas en blanco.
- **Hardening Dinámico de Políticas Corporativas:** `entrypoint.sh` genera dinámicamente `/etc/chromium/policies/managed/kiosk_policy.json` bloqueando esquemas internos y protocolos no deseados (`chrome://*`, `chrome-extension://*`, `edge://*`, `file://*`, `ftp://*`, `javascript://*`), desactivando DevTools (`DeveloperToolsAvailability: 2`), prohibiendo descargas (`DownloadRestrictions: 3`) y deshabilitando impresión.
- **Optimización de Almacenamiento y Retención de Credenciales:**
  - Aplica límites estrictos de caché en disco (`--disk-cache-size=33554432`, `--media-cache-size=16777216`, `--disable-application-cache`, `--disable-gpu-program-cache`).
  - Purga selectiva en `startwm.sh` de directorios temporales de caché (`Cache/`, `Code Cache/`, `GPUCache/`, `ShaderCache/`) preservando intactos `Login Data`, `Cookies` y `Preferences`.
- **Límites de Seguridad Estrictos:**
  - `mem_limit`: 768 MB (evita saturación en el host).
  - `nano_cpus`: 1.0 core.
  - `shm_size`: 256 MB.
  - Etiqueta obligatoria: `managed-by=jumpserver-kiosk-manager`.

### C. Motor Docker y Auto-descubrimiento (`/var/run/docker.sock`)
- El backend monta el socket Docker del host `/var/run/docker.sock`:
  1. **Autodescubrimiento Zero-Config:** Conecta con el contenedor `jms_core` en ejecución y ejecuta comandos en el shell de Django para resolver un `AccessKey` administrativo activo sin intervención manual.
  2. **Ciclo de Vida JIT:** Crea, arranca, detiene y destruye contenedores y volúmenes según la demanda de los operadores.
  3. **Aislamiento Seguro:** Toda acción destructiva verifica estrictamente la etiqueta `managed-by=jumpserver-kiosk-manager`.

### D. Integración Criptográfica con JumpServer v4 (RBAC)
- **Autenticación HMAC-SHA256:** Cada petición HTTP saliente hacia la API REST de JumpServer es firmada criptográficamente:
  `Authorization: Signature keyid="<KEY_ID>",algorithm="hmac-sha256",headers="(request-target) date x-jms-org",signature="<BASE64>"`
- **Modelo RBAC JumpServer v4:**
  - Consulta de administradores a través del modelo de roles: `role__name__icontains="Admin"` (con fallback seguro a `username="admin"`). En JumpServer v4, el campo legacy `is_superuser` fue deprecado en el ORM.
  - Organización por defecto: `00000000-0000-0000-0000-000000000002` (System Org).
- **Aprovisionamiento Transaccional:**
  1. Activo de Tipo Host en `/api/v1/assets/hosts/` asignado al nodo `/DEFAULT`.
  2. Protocolo RDP con parámetros `security: any` e `ignore_cert: true` para compatibilidad universal con Lion.
  3. Cuenta de acceso RDP con contraseña aleatoria de 32 caracteres generada criptográficamente en `/api/v1/accounts/accounts/`.
  4. Regla de Permiso y Autorización en `/api/v1/perms/asset-permissions/` vinculada al grupo de administradores.

### E. Interfaz de Administración Corporativa (`frontend/` + Nginx `:8080`)
- Single Page Application (SPA) construida en **Vue 3** y empaquetada con **Vite**.
- **Sistema de Diseño Corporativo Milicic (`.agent/skills/diseno-UI-milicic/SKILL.md`):**
  - **Paleta de Identidad y Modo Dual:** Cabecera en Gris Pizarra Oscuro (`#2A343D` / `#141A20` en modo oscuro) con logotipo institucional en blanco, color de acento y CTA en Naranja Milicic (`#F39200`), fondos limpios en blanco/neutro (`#FFFFFF`/`#F8F9FA`) y modo oscuro de alto contraste (`#0F141A`/`#1A222B`) con persistencia en `localStorage` y detección de `prefers-color-scheme`.
  - **Tarjetas de Métricas Circulares:** Métricas visuales de impacto (activos totales, sesiones activas, memoria RAM ahorrada en reposo y puertos RDP asignados) inspiradas en los badges de la web corporativa.
  - **Panel de Políticas Dinámicas:** Modal integrado para ajustar en tiempo real los 4 parámetros de ciclo de vida (`disconnect_grace_seconds`, `idle_timeout_seconds`, `max_session_lifetime_seconds`, `max_concurrent_sessions`) con persistencia en SQLite (`/api/settings`).
  - **Utilidades de Productividad y Operación NOC:**
    - **Modo Oscuro (Dark Mode):** Alternador Sol/Luna con transición suave y cero FOUC.
    - **Auto-Refresco con Temporizador Regresivo:** Intervalos de 15s, 30s o 60s con sondeo silencioso en background.
    - **Copia Rápida RDP:** Copia directa del endpoint de conexión (`host:puerto`) con feedback visual verde.
    - **Exportación de Inventario:** Descarga inmediata en formatos CSV y JSON desde la barra de herramientas.
    - **Densidad de Tabla:** Alternancia entre vista cómoda y compacta para visualización de alta densidad.
    - **Atajos Globales:** `Ctrl+K` o `/` para búsqueda global, `Escape` para limpiar o cerrar modales.
- Servida por **Nginx** en el puerto `8080` que actúa como reverse proxy hacia la API FastAPI (`127.0.0.1:8000/api/`).
- Admite operaciones CRUD completas (`GET`, `POST`, `PUT`, `DELETE`), pruebas de conectividad de destino en vivo (`test-url`), limpieza de caché de Chromium, reinicio y acceso directo con un clic a JumpServer Luna.

### F. Seguridad en Luna y Contexto Seguro W3C (HTTPS / Portapapeles)
- **Restricción W3C Secure Context:** Para habilitar la API `navigator.clipboard` que permite copiar y pegar credenciales y comandos entre la estación de trabajo y la sesión remota en JumpServer Luna, los navegadores modernos exigen estrictamente una conexión segura **HTTPS** (o `localhost`). En conexiones HTTP no seguras, el navegador bloquea el acceso (`navigator.clipboard api not found`).
- **Soporte de Conectividad `JMS_VERIFY_SSL`:** Al desplegar JumpServer en HTTPS con certificados autofirmados con SAN IP, el cliente HTTP de `kiosk-manager` soporta la bandera `JMS_VERIFY_SSL=false` (o montaje de CA bundle corporativo mediante `JMS_CA_BUNDLE`), evitando fallos por `SSLCertVerificationError` durante el aprovisionamiento y sincronización de activos.

### G. Autenticación Delegada (JumpServer SSO Pasivo) y Acceso Directo Web App
- **Single Sign-On Pasivo por Sesión JumpServer:**
  - `kiosk-manager` delega la autenticación directamente en el bastión JumpServer (`172.30.20.62` / `JMS_BASE_URL`).
  - Cada petición HTTP es evaluada por la dependencia FastAPI `get_current_user` (`backend/app/auth/jms_auth.py`), la cual captura la cookie de sesión `jms_sessionid` (o header `Authorization`) y consulta en tiempo real el endpoint `GET /api/v1/users/profile/` en JumpServer.
  - Si la sesión es válida (HTTP 200), extrae el perfil del operador (`id`, `username`, `name`, `email`, `roles`).
  - Si no existe sesión o caducó (HTTP 401/403), deniega el acceso a los endpoints sensibles (`/api/kiosks`, `/api/categories`, `/api/settings`) retornando `401 Unauthorized`.
- **Auth Guard Visual en Frontend (`App.vue`):**
  - Al iniciar la aplicación, se consulta `GET /api/auth/me` con `credentials: 'include'`.
  - En caso de sesión no detectada o expirada, se bloquea la vista de control y se despliega una tarjeta institucional con la estética Milicic/JumpServer informando el estado y proveyendo un botón de redirección inmediata al portal de login de JumpServer (`https://172.30.20.62/ui/#/login`).
  - Si la sesión es válida, la barra superior muestra la insignia `👤 {user.name} ({user.username})` y el menú de usuario incluye la opción de cierre de sesión hacia `https://172.30.20.62/ui/#/logout`.
- **Trazabilidad Forense:** El nombre de usuario autenticado se inyecta automáticamente en los comentarios de auditoría de los activos registrados en JumpServer: `Managed by Kiosk-Manager | Device: {device} | CreatedBy: {username}`.
- **Registro Nativo de Aplicación Web ("Agregar Sitio WEB"):**
  - Durante el arranque o sincronización inicial, `JumpServerClient.ensure_web_application_asset()` registra de forma idempotente la URL pública configurada (`KIOSK_MANAGER_PUBLIC_URL`, por defecto `http://172.30.20.62:8000`) en `/api/v1/applications/applications/`.
  - Esto permite a los operadores acceder a Kiosk Manager con un clic directamente desde su espacio de trabajo en JumpServer (Lina/Luna) sin modificar el código fuente del bastión.

### H. Sincronización Dinámica de Categorías y Árbol de Nodos JumpServer (Herencia RBAC)
- **Mapeo Dinámico Categorías <-> Nodos (`/api/v1/assets/nodes/`):**
  - Cada categoría gestionada en `kiosk-manager` (ej. `SWITCHES ROSARIO`, `SERVERS INFRA`, `SERVERS BACKUP`) se sincroniza bidireccionalmente con el árbol de Nodos organizativos de JumpServer.
  - Al aprovisionar un quiosco, el backend resuelve o asegura el nodo homólogo en JumpServer (`ensure_node`) y envía el UUID del nodo en el payload del activo (`nodes: [node_uuid]`).
- **Herencia Automática de Permisos RBAC en Luna:**
  - En JumpServer, los permisos de autorización delegados sobre una carpeta/nodo se heredan automáticamente por todos los activos contenidos en dicho nodo.
  - Al inyectar el nodo explícito en lugar de dejar el activo huérfano en `DEFAULT`, los grupos de usuarios autorizados (por ejemplo, `Switch Admins Rosario`) obtienen visibilidad y capacidad de conexión inmediata al quiosco en Luna sin requerir asignación manual de permisos por dispositivo.
- **Ciclo de Vida Idempotente:**
  - **Creación:** Se asegura el nodo en JumpServer vía `POST /api/v1/assets/nodes/` antes de persistir la categoría local.
  - **Renombrado:** Modificaciones en categorías se propagan mediante `PATCH /api/v1/assets/nodes/{id}/` y actualizan los quioscos vinculados.
  - **Eliminación Segura:** Antes de remover una categoría con activos asociados, el sistema reasigna los dispositivos huérfanos al nodo por defecto (`JMS_DEFAULT_NODE_NAME`), evitando la pérdida de trazabilidad.
  - **Sincronización Inicial:** El endpoint `POST /api/categories/sync-jms-nodes` importa nodos preexistentes en JumpServer y asegura que el catálogo local y remoto permanezcan unificados.
- **Variables de Configuración:**
  - `JMS_DEFAULT_NODE_NAME`: Nombre del nodo de respaldo por defecto (por defecto: `"SWITCHES ROSARIO"`).
  - `JMS_DEFAULT_NODE_ID`: UUID opcional para fijar estáticamente el nodo de destino.

### H. Resiliencia Empresarial, Healthcheck RDP y Ciclo de Vida Completo (Enterprise-Grade)

Para garantizar estabilidad de nivel producción en despliegues con alto volumen de operadores y quioscos concurrentes, se incorporaron cuatro pilares de confiabilidad:

1. **Desaprovisionamiento Idempotente y Garbage Collection:**
   - **`delete_asset(asset_id: str) -> bool`:** Ejecuta `DELETE /api/v1/assets/assets/{asset_id}/` tolerando respuestas `404 Not Found` como éxito (idempotencia garantizada).
   - **Hook en Destrucción (`deprovision`):** Al eliminar un quiosco desde el portal o API, se purgan secuencialmente la regla de permiso (`asset-permissions`), la cuenta de credenciales (`accounts`) y el activo (`assets`) en JumpServer, junto con el contenedor y volumen Docker.
   - **Job de Reconciliación Periódica (`POST /api/kiosks/reconcile-jms` y `POST /api/kiosk/reconcile-jms`):** Obtiene todos los activos gestionados en JumpServer (identificados por tags `kiosk-manager`, `ephemeral` o prefijo de comentario), compara contra el catálogo de quioscos activos en SQLite y purga cualquier activo huérfano o remanente sin contenedor local.

2. **Readiness Gate de Socket RDP (`wait_for_rdp_ready`):**
   - **Prevención de Conexión Rechazada en Luna:** Si un usuario abre la consola inmediatamente tras aprovisionar el quiosco, Lion/Guacamole podría fallar si el servicio XRDP aún está levantando en el contenedor.
   - **Sondeo Asíncrono de Socket:** `wait_for_rdp_ready(host, port, timeout=10.0, interval=0.5)` verifica la apertura efectiva del socket TCP. Si supera el tiempo límite, el estado del quiosco se establece en `PROVISION_FAILED` y se ejecuta rollback de recursos locales sin crear activos inválidos o inalcanzables en JumpServer.

3. **Resiliencia HTTP con Backoff Exponencial y Renovación Transparente de Token:**
   - **Reintentos Exponenciales:** Las peticiones salientes hacia JumpServer reintentan automáticamente ante fallas de transporte (`httpx.ConnectError`, `httpx.TimeoutException`, errores `502`, `503`, `504`) con hasta 3 intentos y retroceso exponencial de 1 a 4 segundos.
   - **Renovación Transparente de Token/Sesión:** Si JumpServer retorna `401 Unauthorized` o `403 Forbidden` (por token caducado o rotación de AccessKey), el cliente invalida la caché local, reautentica automáticamente (vía `/api/v1/authentication/auth/` o redescubrimiento Docker de `jms_core`) y reintenta la solicitud original de manera transparente sin interrumpir la operación del usuario.

4. **Metadatos Forenses de Auditoría y Trazabilidad (Audit Tags):**
   - Cada activo registrado en JumpServer incorpora metadatos estructurados para auditoría y trazabilidad:
     ```json
     {
       "comment": "Managed by Kiosk-Manager | Device: {device_name} | CreatedBy: {requester_username}",
       "tags": ["kiosk-manager", "ephemeral", "category:{category_name}"]
     }
     ```
   - Esto permite que los auditores identifiquen de inmediato el origen del quiosco efímero, su categoría y el operador responsable tanto en el inventario de activos como en los registros de auditoría y grabaciones de sesión de JumpServer.

5. **Reconciliación Automática en Background (`auto_reconcile_loop`):**
   - Tarea asíncrona en segundo plano iniciada en FastAPI (`main.py`) que ejecuta de forma autónoma la detección y purga de activos huérfanos cada `JMS_RECONCILE_INTERVAL_HOURS` horas (por defecto 12h, ajustable o desactivable con `0`), garantizando que JumpServer permanezca limpio sin depender exclusivamente de tareas cron en el host.

6. **Detención Manual de Sesión y Liberación Instantánea de RAM (`stop_session`):**
   - Endpoint `POST /api/kiosks/{id}/stop` y botón de acción en la interfaz web para que los operadores del NOC finalicen una sesión activa y liberen de inmediato los 768 MB de RAM del host, complementando las políticas automatizadas de inactividad.


