# Guía de Arquitectura: JumpServer Kiosk Manager

## 1. Visión General

**JumpServer Kiosk Manager** resuelve la necesidad de conectar operadores a aplicaciones y consolas web de infraestructura crítica mediante **JumpServer Community Edition (v4.10.x CE)** sin requerir complementos comerciales Enterprise (Web Terminal).

Para lograr esto de forma segura, escalable y con mínimo impacto en recursos (especialmente en entornos Proxmox VE con contenedores LXC o máquinas virtuales), se implementó una **Arquitectura Efímera Bajo Demanda (Just-In-Time / Ephemeral On-Demand)**.

---

## 2. Componentes Clave de la Arquitectura

### A. RDP Dispatcher Asíncrono (`backend/app/dispatcher/service.py`)
- **Proxy TCP Transparente Asíncrono (`asyncio`):** El backend ejecuta en modo de red host (`network_mode: "host"`) y levanta un servidor TCP asíncrono para cada quiosco aprovisionado en el rango de puertos configurable `33891 - 33920`.
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
- **Navegador Web:** Chromium en modo `--kiosk` y `--app="TARGET_URL"`.
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
- Servida por **Nginx** en el puerto `8080` que actúa como reverse proxy hacia la API FastAPI (`127.0.0.1:8000/api/`).
- Admite operaciones CRUD completas (`GET`, `POST`, `PUT`, `DELETE`), pruebas de conectividad de destino en vivo (`test-url`) y acceso directo con un clic a JumpServer Luna.
