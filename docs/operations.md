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

## 3. Política Corporativa de Chromium (`kiosk_policy.json`)

Ubicación: `kiosk-image/kiosk_policy.json`  
Ruta dentro del contenedor: `/etc/chromium/policies/managed/kiosk_policy.json`

Políticas implementadas:
- `URLBlocklist`: Bloquea esquemas internos peligrosos (`chrome://*`, `chrome-extension://*`, `edge://*`, `file://*`).
- `URLAllowlist`: Permite navegación hacia `http://*`, `https://*`.
- `DeveloperToolsAvailability: 2`: Herramientas de desarrollador (F12) desactivadas por completo.
- `PasswordManagerEnabled: true`: Permite que Chromium recuerde contraseñas del dispositivo si el operador lo autoriza.
- `DownloadRestrictions: 3`: Bloquea todas las descargas de archivos para evitar fugas de datos o descargas maliciosas.
- `DisablePrint: true`: Impresión deshabilitada.

---

## 4. Políticas de Ciclo de Vida y Liberación de Memoria RAM

El sistema incluye 3 mecanismos automáticos e independientes de liberación de recursos en el host:

| Política | Variable de Entorno | Valor por Defecto | Descripción |
| :--- | :--- | :--- | :--- |
| **Ventana de Gracia tras Desconexión** | `KIOSK_DISCONNECT_GRACE_SECONDS` | `30` seg | Espera antes de apagar el contenedor cuando `active_connections == 0` (tolera recargas F5 o pérdidas de red). |
| **Inactividad por Falta de Tráfico** | `KIOSK_IDLE_TIMEOUT_SECONDS` | `900` seg (15 min) | Cierra sockets y detiene el contenedor si no se transmite tráfico RDP en este lapso. |
| **Límite Continuo por Sesión** | `KIOSK_MAX_SESSION_LIFETIME_SECONDS` | `14400` seg (4 horas) | Límite máximo ininterrumpido absoluto para prevenir retención indefinida de memoria RAM. |

### Cómo Ajustar las Políticas:
1. **Desde el Panel Web (`:8080`):** Hacer clic en el icono de engranaje (⚙️) en la barra superior ("Ajustes de API JumpServer / Ajustes del Sistema"), ajustar los valores numéricos y guardar.
2. **Vía API REST:**
   ```bash
   # Consultar políticas activas
   curl -u admin:admin http://127.0.0.1:8000/api/settings

   # Actualizar políticas en caliente (sin reiniciar)
   curl -X PUT -u admin:admin http://127.0.0.1:8000/api/settings \
     -H "Content-Type: application/json" \
     -d '{"disconnect_grace_seconds": 45, "idle_timeout_seconds": 600, "max_session_lifetime_seconds": 7200}'
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

## 6. Respaldos (Backup y Recuperación)

Los datos del Kiosk Manager residen en:
1. **Base de Datos SQLite:** `/app/data/kiosk.db` (en volumen `kiosk_db_data`)
2. **Volúmenes de Credenciales:** Volúmenes Docker `rdp_*` creados con etiqueta `managed-by=jumpserver-kiosk-manager`.
3. **Configuración y Secretos:** Archivos `.env` y `./secrets/`

### Copia de seguridad rápida:
```bash
tar -czvf /opt/backup_kiosk_manager_$(date +%F).tar.gz \
  /opt/jumpsrv/.env \
  /var/lib/docker/volumes/jumpsrv_kiosk_db_data/ \
  /opt/jumpsrv/secrets/
```
