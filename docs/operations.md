# Manual de Operaciones y Mantenimiento: JumpServer Kiosk Manager

## 1. Servicios del Sistema y Comandos de Control

El sistema opera mediante los siguientes componentes:

| Componente | Tipo | Control |
| :--- | :--- | :--- |
| **kiosk-backend.service** | Servicio systemd | `systemctl restart kiosk-backend.service` |
| **nginx** | Servidor web / Proxy inverso | `systemctl reload nginx` |
| **Docker Engine** | Motor de contenedores | `docker ps -a` |
| **PostgreSQL / Redis** | Infraestructura JumpServer | Contenedores `jms_postgresql`, `jms_redis` |

### Comandos de Operación Habitual

```bash
# Ver estado del backend y dispatcher
systemctl status kiosk-backend.service --no-pager

# Seguir logs del backend en tiempo real
journalctl -u kiosk-backend.service -f

# Inspeccionar puertos RDP escuchando en el host
ss -tulpn | grep 3389

# Ver contenedores de quiosco activos o en reposo
docker ps -a --filter label=managed-by=jumpserver-kiosk-manager

# Comprobar uso de memoria y carga del sistema
free -m
uptime
```

---

## 2. Gestión de la Imagen Docker de Quiosco

La imagen `pam-web-kiosk:v1` contiene la configuración de Openbox, Chromium, políticas corporativas y XRDP.

### Para reconstruir la imagen tras modificar configuraciones:
```bash
docker build -t pam-web-kiosk:v1 /root/jumpserver-kiosk-manager/kiosk-image
```

### Para reiniciar todos los quioscos y que tomen la nueva imagen:
Al ser una arquitectura bajo demanda, simplemente elimina los contenedores activos existentes:
```bash
docker rm -f $(docker ps -aq --filter label=managed-by=jumpserver-kiosk-manager)
```
La próxima conexión levantará automáticamente un nuevo contenedor con la imagen actualizada.

---

## 3. Política Corporativa de Chromium (`kiosk_policy.json`)

Ubicación: `/root/jumpserver-kiosk-manager/kiosk-image/kiosk_policy.json`
Ruta dentro del contenedor: `/etc/chromium/policies/managed/kiosk_policy.json`

Políticas implementadas:
- `URLBlocklist`: Bloquea `chrome://*`, `chrome-extension://*`, `edge://*`, `file://*`.
- `URLAllowlist`: Permite `http://*`, `https://*`.
- `DeveloperToolsAvailability: 2`: Herramientas de desarrollador (F12) desactivadas por completo.
- `PasswordManagerEnabled: true`: Permite que Chromium recuerde contraseñas del dispositivo si el operador lo autoriza.
- `DownloadRestrictions: 3`: Bloquea todas las descargas de archivos para evitar fugas de datos o descargas maliciosas.
- `DisablePrint: true`: Impresión deshabilitada.

---

## 4. Respaldos (Backup y Recuperación)

Los datos del Kiosk Manager residen en:
1. **Base de Datos SQLite:** `/root/jumpserver-kiosk-manager/kiosk.db`
2. **Volúmenes de Credenciales:** Volúmenes Docker `kiosk_vol_*` ubicados en `/var/lib/docker/volumes/`

### Copia de seguridad rápida:
```bash
tar -czvf /root/backup_kiosk_manager_$(date +%F).tar.gz \
  /root/jumpserver-kiosk-manager/kiosk.db \
  /root/jumpserver-kiosk-manager/.env \
  /etc/systemd/system/kiosk-backend.service \
  /etc/nginx/sites-available/
```
