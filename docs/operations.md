# Manual de Operaciones y Mantenimiento: JumpServer Kiosk Manager

## 1. Servicios del Sistema y Comandos de Control

En producción, JumpServer Kiosk Manager opera típicamente mediante Docker Compose (`docker-compose.prod.yml`) o a través de servicios systemd:

### Despliegue en Docker Compose (Recomendado)

| Contenedor | Red | Función |
| :--- | :--- | :--- |
| **kiosk-manager-backend** | `host` | API FastAPI, Dispatcher TCP, orquestador Docker |
| **kiosk-manager-frontend** | `bridge` (`8080:80`) | Dashboard SPA Nginx + Vue 3 |
| **pam-web-kiosk (efímeros)** | `bridge` | Sesiones Chromium/XRDP bajo demanda |

```bash
# Estado de los contenedores
docker compose -f docker-compose.prod.yml ps

# Logs del backend y Dispatcher en tiempo real
docker compose -f docker-compose.prod.yml logs -f backend

# Reiniciar el stack
docker compose -f docker-compose.prod.yml restart

# Ver quioscos efímeros activos o detenidos
docker ps -a --filter label=managed-by=jumpserver-kiosk-manager

# Comprobar puertos RDP escuchando en el host
ss -tulpn | grep 3389
```

### Modo Servicio Systemd (Despliegue Host Directo)

```bash
# Ver estado del backend y dispatcher
systemctl status kiosk-backend.service --no-pager

# Seguir logs del backend en tiempo real
journalctl -u kiosk-backend.service -f

# Reiniciar servicio backend
systemctl restart kiosk-backend.service
```

---

## 2. Gestión de la Imagen Docker de Quiosco

La imagen `pam-web-kiosk` contiene la configuración de Openbox, Chromium, políticas corporativas y XRDP.

### Para reconstruir la imagen localmente:
```bash
docker build -t ghcr.io/larentimatias7-oss/jumpsrv/pam-web-kiosk:latest ./kiosk-image
```

### Para reiniciar todos los quioscos y que tomen la nueva imagen:
Al ser una arquitectura bajo demanda, simplemente detén o elimina los contenedores existentes (los volúmenes conservarán las cookies y contraseñas guardadas):
```bash
docker rm -f $(docker ps -aq --filter label=managed-by=jumpserver-kiosk-manager)
```
La próxima conexión levantará automáticamente un nuevo contenedor con la imagen actualizada.

---

## 3. Hardening Dinámico de Chromium y Optimización de Almacenamiento

Ubicación: `kiosk-image/entrypoint.sh` y `kiosk-image/startwm.sh`  
Ruta de políticas dentro del contenedor: `/etc/chromium/policies/managed/kiosk_policy.json`

### Hardening de Políticas Corporativas (Generadas Dinámicamente):
- `URLBlocklist`: Bloquea esquemas internos y protocolos peligrosos (`chrome://*`, `chrome-extension://*`, `edge://*`, `file://*`, `ftp://*`, `javascript://*`).
- `URLAllowlist`: Permite navegación segura únicamente a destinos `http://*` y `https://*`.
- `DeveloperToolsAvailability: 2`: Herramientas de desarrollador (F12 / Inspeccionar) desactivadas de forma estricta.
- `PasswordManagerEnabled: true`: Permite que Chromium almacene contraseñas en el llavero local para el operador sin romper el flujo de acceso continuo.
- `PasswordSharingEnabled: false`: Bloquea exportación o compartición de credenciales guardadas.
- `DownloadRestrictions: 3`: Bloquea todas las descargas de archivos para evitar fugas de datos o descargas de malware.
- `DisablePrint: true`: Impresión deshabilitada.

### Protección de Almacenamiento (Prevención de Fugas de Disco):
Para evitar acumulación descontrolada de gigabytes de datos temporales sin romper el gestor de contraseñas:
1. **Límites estrictos de caché por flags en `startwm.sh`:**
   - `--disk-cache-size=33554432` (Límite máximo de 32 MB para caché web en disco).
   - `--media-cache-size=16777216` (Límite máximo de 16 MB para caché de multimedia).
   - `--disable-application-cache` (Desactiva cachés obsoletas de aplicaciones web).
   - `--disable-gpu-program-cache` (Evita crecimiento indiscriminado de binarios GPU compilados).
2. **Purga selectiva al inicio en `startwm.sh`:**
   - Elimina automáticamente: `Default/Cache*`, `Default/Code Cache`, `Default/GPUCache`, `Default/ShaderCache`, y `Service Worker/*Cache*`.
   - **Conserva intactos:** `Login Data` (credenciales recordadas), `Cookies` (sesiones persistentes) y `Preferences`.

---

## 4. Políticas de Ciclo de Vida y Liberación de Memoria RAM

El sistema incluye 4 mecanismos automáticos e independientes de control de recursos en el host:

| Política | Variable de Entorno | Valor por Defecto | Descripción |
| :--- | :--- | :--- | :--- |
| **Ventana de Gracia tras Desconexión** | `KIOSK_DISCONNECT_GRACE_SECONDS` | `30` seg | Espera antes de apagar el contenedor cuando `active_connections == 0` (tolera recargas F5 o microcortes). |
| **Inactividad por Falta de Tráfico** | `KIOSK_IDLE_TIMEOUT_SECONDS` | `900` seg (15 min) | Cierra sockets y detiene el contenedor si no se transmite tráfico RDP en este lapso. |
| **Límite Continuo por Sesión** | `KIOSK_MAX_SESSION_LIFETIME_SECONDS` | `14400` seg (4 horas) | Límite máximo ininterrumpido absoluto para prevenir retención indefinida de memoria RAM. |
| **Límite de Concurrencia Simultánea** | `KIOSK_MAX_CONCURRENT_SESSIONS` | `4` sesiones | Límite máximo de contenedores simultáneos en ejecución para proteger la RAM del host contra OOM. |

### Cómo Ajustar las Políticas:
1. **Desde el Panel Web (`:8080`):** Hacer clic en el icono de engranaje (⚙️) en la barra superior ("Ajustes de API JumpServer / Ajustes del Sistema"), ajustar los valores numéricos y guardar en caliente.
2. **Vía API REST:**
   ```bash
   # Consultar políticas activas
   curl -u admin:admin http://127.0.0.1:8000/api/settings

   # Actualizar políticas en caliente (sin reiniciar el backend)
   curl -X PUT -u admin:admin http://127.0.0.1:8000/api/settings \
     -H "Content-Type: application/json" \
     -d '{"disconnect_grace_seconds": 45, "idle_timeout_seconds": 600, "max_session_lifetime_seconds": 7200, "max_concurrent_sessions": 6}'
   ```
3. **Vía `.env`:** Declarar las variables en `/opt/jumpsrv/.env` y reiniciar el stack.

---

## 5. Pruebas de Integración y Validación E2E

El repositorio incluye una suite automatizada de 8 fases para validar el ciclo de vida completo en el host:

```bash
python3 scripts/e2e_test_runner.py
```

En entornos de desarrollo sobre Windows con WSL:
```bash
wsl bash -c "/tmp/venv/bin/pytest backend/tests"
```

---

## 6. Respaldos Automatizados (Backup Online SQLite y Volúmenes)

### 6.1 Respaldo Online de Base de Datos SQLite (`scripts/backup_database.sh`)
La base de datos SQLite opera en modo WAL (`Write-Ahead Logging`), lo que permite realizar copias en caliente consistentes sin detener el backend ni bloquear transacciones mediante el comando online `.backup`:

```bash
# Ejecución manual del script de respaldo
/opt/jumpsrv/scripts/backup_database.sh /data/kiosk.db /backup 7
```

**Características del script:**
- Realiza copia en caliente online (`.backup`) mediante `sqlite3` CLI o la API `sqlite3.backup` de Python.
- Valida la integridad del archivo resultante (`PRAGMA integrity_check`).
- Rota automáticamente los respaldos eliminando archivos con más de 7 días de antigüedad (`-mtime +7`).

### 6.2 Automatización Diaria vía Cron
Para ejecutar respaldos automáticos todos los días a las 03:00 AM, configura una tarea en crontab:

```bash
# Editar crontab del host
crontab -e
```

Añadir la siguiente directiva:
```cron
# Respaldo diario de base de datos Kiosk Manager a las 03:00 AM (retención 7 días)
0 3 * * * /opt/jumpsrv/scripts/backup_database.sh /var/lib/docker/volumes/jumpsrv_kiosk_db_data/_data/kiosk.db /backup/kiosk_db 7 >> /var/log/kiosk_backup.log 2>&1
```

### 6.3 Respaldo Integral de Volúmenes y Secretos
Para un respaldo completo que incluya las cookies/credenciales de los quioscos y los secretos de JumpServer:
```bash
/opt/jumpsrv/scripts/backup.sh
```
O manualmente:
```bash
tar -czvf /backup/backup_kiosk_full_$(date +%F).tar.gz \
  /opt/jumpsrv/.env \
  /var/lib/docker/volumes/jumpsrv_kiosk_db_data/ \
  /opt/jumpsrv/secrets/
```
