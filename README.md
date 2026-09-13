# JumpServer Kiosk Manager 🚀

**JumpServer Kiosk Manager** es una solución integral y autónoma para la gestión y aprovisionamiento automatizado de **activos web aislados mediante RDP** en **JumpServer Community Edition (CE)** (totalmente optimizado y validado para **JumpServer v4.10.x CE**).

Permite acceder a consolas web de infraestructura crítica (Zabbix, switches, routers MikroTik, firewalls FortiGate, hipervisores Proxmox/VMware, consolas iDRAC/iLO, cámaras CCTV, etc.) a través de JumpServer Luna sin requerir complementos Enterprise, con auditoría centralizada, grabación de sesiones y autenticación robusta.

---

## 🌟 Características Principales

- **Arquitectura Bajo Demanda (Ephemeral On-Demand / JIT):**
  - Consumo de **0% CPU y 0 MB RAM en reposo**.
  - Los contenedores Docker se inician automáticamente solo cuando un operador solicita la conexión en JumpServer Luna (detección del paquete `RDP-SYN` en el Dispatcher TCP).
  - Apagado automático programado tras **120 segundos de inactividad** después de cerrar la sesión.
  - Límite de recursos estricto por sesión: `768 MB RAM`, `1 CPU`, `256 MB /dev/shm`.
- **Integración Nativa con JumpServer v4.10.x CE (RBAC):**
  - Compatibilidad completa con el modelo Role-Based Access Control (RBAC) de JumpServer v4.
  - Creación y vinculación automática de Activos (`/api/v1/assets/hosts/`), Cuentas de Acceso RDP (`/api/v1/accounts/accounts/`) y Reglas de Autorización (`/api/v1/perms/asset-permissions/`) mediante firmas criptográficas **HMAC-SHA256**.
  - Parámetros de seguridad optimizados para JumpServer Lion (`security: any`, `ignore_cert: true`).
- **Auto-descubrimiento Cero Configuración:**
  - El backend accede a `/var/run/docker.sock` para inspeccionar el contenedor `jms_core` local, extrayendo o creando un `AccessKey` administrativo de forma automática y segura.
  - Detección automática de la IP del host y persistencia en `/app/data/jms_credentials.json`.
- **Imagen de Quiosco Ultraligera (`pam-web-kiosk:v1` / `latest`):**
  - Basada en Debian 12 Bookworm Slim + Openbox + XorgXRDP + Chromium Native.
  - Políticas gestionadas corporativas (`kiosk_policy.json`): bloquea atajos peligrosos, F12, descargas y navegación externa, habilitando el gestor de contraseñas integrado.
  - Persistencia de credenciales y cookies mediante volúmenes Docker dedicados por dispositivo (`volume_name`), con etiquetas `managed-by=jumpserver-kiosk-manager`.
- **Dashboard Web Corporativo (`:8080`):**
  - Frontend moderno construido con **Vue 3** y **Vite**, con interfaz limpia y modo oscuro/claro corporativo.
  - **Edición en Caliente:** Permite modificar URLs de destino, nombres y tipos de dispositivo en caliente.
  - **One-Click Connect:** Botón de conexión directa que abre la sesión gráfica en JumpServer Luna.
  - **Sondeo de Conectividad HTTP en Vivo:** Valida si el equipo destino responde con código HTTP y latencia en milisegundos.
  - **Limpieza de Caché y Sesión:** Resetea cookies y perfiles web sin eliminar el activo.
  - **Buscador y Filtros en Tiempo Real:** Organización instantánea por nombre, IP y tipo de equipo.
  - **Monitor de Ahorro de Memoria:** Estimación visual de RAM ahorrada en el host en tiempo real.

---

## 🏛️ Arquitectura del Sistema

```
+-----------------------------------------------------------------------------+
|                                OPERADOR                                     |
|                       Navegador Web / Luna Client                           |
+-------------------------------------+---------------------------------------+
                                      | HTTP/WebSocket (:80)
                                      v
+-----------------------------------------------------------------------------+
|                           JUMPSERVER COMMUNITY v4                           |
|   +-------------------+                     +---------------------------+   |
|   |   jms_core (v4)   |                     |     jms_lion (Guacamole)  |   |
|   +---------+---------+                     +-------------+-------------+   |
+-------------|---------------------------------------------|-----------------+
              | API REST (HMAC-SHA256)                      | RDP Proxy (TLS)
              v                                             v
+-----------------------------------------------------------|-----------------+
|                    JUMPSERVER KIOSK MANAGER               |                 |
|                                                           |                 |
|  +--------------------+    +------------------------------+--------------+  |
|  | Web Panel (:8080)  |    | RDP Dispatcher Service (:33891 - :33920)    |  |
|  | Nginx + Vue 3      |    | - Detección de tráfico RDP-SYN              |  |
|  +---------+----------+    | - Just-In-Time Container Start              |  |
|            |               | - Sondeo de socket interno 3389             |  |
|            v               | - Proxy transparente bidireccional          |  |
|  +--------------------+    | - Temporizador de inactividad (120s)        |  |
|  | FastAPI (:8000)    |    +------------------------------+--------------+  |
|  | SQLite / WAL Mode  |                                   |                 |
|  +---------+----------+                                   |                 |
+------------|----------------------------------------------|-----------------+
             | Docker Engine API (/var/run/docker.sock)     | Internal Bridge
             +----------------------+-----------------------+ (172.17.0.x:3389)
                                    v
+-----------------------------------------------------------------------------+
|                     CONTENEDOR KIOSK (On-Demand)                            |
|                       pam-web-kiosk:latest                                  |
|  +-------------------+  +-------------------+  +-------------------------+  |
|  | XRDP + XorgXRDP   |  | Openbox WM        |  | Chromium Kiosk          |  |
|  | TLSv1.2 / TLSv1.3 |  | (Sesión limpia)   |  | --app=TARGET_URL        |  |
|  +-------------------+  +-------------------+  +-------------------------+  |
|                            | Persistencia                                   |
|                            v                                                |
|                 Volumen Docker (Credenciales)                               |
+-----------------------------------+-----------------------------------------+
                                    | HTTP / HTTPS
                                    v
+-----------------------------------------------------------------------------+
|                         DISPOSITIVO DESTINO                                 |
|             (Zabbix, Router, Switch, Firewall, Proxmox, etc.)               |
+-----------------------------------------------------------------------------+
```

---

## 🚀 Despliegue en Producción

### Puertos de Red

| Servicio | Puerto | Modo | Descripción |
| :--- | :--- | :--- | :--- |
| **Kiosk Manager Dashboard** | `8080/tcp` | Bridge (`8080:80`) | Interfaz de administración Nginx + Vue 3 |
| **Backend FastAPI** | `8000/tcp` | Host | API REST de orquestación y aprovisionamiento |
| **RDP Dispatcher Pool** | `33891 - 33920` | Host | Rango TCP para escucha de conexiones RDP entrantes |
| **JumpServer Web/Luna** | `80/tcp` | Host/Proxy | Portal principal de JumpServer |

### Despliegue Rápido (Stack Oficial)

Para desplegar JumpServer Kiosk Manager en el host donde corre JumpServer:

```bash
mkdir -p /opt/jumpsrv && cd /opt/jumpsrv && \
curl -sSL https://raw.githubusercontent.com/larentimatias7-oss/jumpsrv/main/docker-compose.prod.yml -o docker-compose.yml && \
docker compose pull && \
docker compose up -d
```

### Configuración de Credenciales JumpServer

1. **Auto-descubrimiento Automático (Recomendado):**
   - El contenedor `kiosk-manager-backend` monta `/var/run/docker.sock` y localiza automáticamente el contenedor `jms_core`.
   - Consulta el ORM de JumpServer v4 vía RBAC (`role__name__icontains="Admin"`), genera o recupera el `AccessKey` activo y lo almacena en `/app/data/jms_credentials.json`.
   - Si la IP del host no está configurada, detecta automáticamente la interfaz de red local.

2. **Configuración Explícita vía `.env`:**
   Si JumpServer está en un host remoto o se desean fijar credenciales manuales, crear `/opt/jumpsrv/.env`:

   ```bash
   # Generar o consultar AccessKey en JumpServer v4 (RBAC compliant):
   docker exec -i jms_core /opt/py3/bin/python /opt/jumpserver/apps/manage.py shell -c "
   from authentication.models import AccessKey
   from users.models import User
   u = User.objects.filter(role__name__icontains='Admin').first() or User.objects.filter(username='admin').first()
   ak = AccessKey.objects.filter(user=u, is_active=True).first() or AccessKey.objects.create(user=u)
   print(f'JMS_KEY_ID={ak.id}\nJMS_SECRET_KEY={ak.secret}')
   "
   ```

   Definir en `/opt/jumpsrv/.env`:
   ```dotenv
   JMS_BASE_URL=http://127.0.0.1:80
   JMS_KEY_ID=tu-access-key-uuid
   JMS_SECRET_KEY=tu-access-key-secret
   KIOSK_HOST_IP=192.168.1.120
   ```
   *(También se soportan transparentemente los alias `JUMPSERVER_BASE_URL`, `JUMPSERVER_KEY_ID`, `JUMPSERVER_KEY_SECRET`).*

   Reiniciar los servicios:
   ```bash
   docker compose up -d
   ```

---

## 🧪 Pruebas y Validación

### Suite de Pruebas Unitarias (WSL / POSIX)
En entornos de desarrollo en Windows, ejecute siempre las pruebas dentro de WSL para garantizar paridad con producción:

```bash
wsl bash -c "/tmp/venv/bin/pytest backend/tests"
```

### Suite E2E (`scripts/e2e_test_runner.py`)
El script de validación E2E automatiza 8 fases de verificación integral sobre un entorno en vivo:

1. **API Health & Auth Verification:** Comprobación de `/health`, frontend SPA y autenticación Basic Auth.
2. **JumpServer v4 RBAC Autodiscovery:** Validación de resolución de credenciales desde `jms_core`.
3. **Kiosk Provisioning Lifecycle:** Creación completa de un activo de prueba (`POST /api/kiosks`).
4. **JumpServer Integration Verification:** Verificación de Host Asset, Cuenta RDP y Regla de Permisos en JumpServer v4.
5. **Dispatcher RDP Port Listening:** Verificación del socket TCP en el puerto asignado.
6. **On-Demand Container Activation (JIT):** Envío de PDU de conexión RDP y verificación del arranque inmediato del contenedor con etiqueta `managed-by=jumpserver-kiosk-manager`.
7. **Target Connectivity Probe:** Comprobación del sondeo HTTP hacia el dispositivo objetivo.
8. **Deprovisioning & Safe Resource Cleanup:** Eliminación del activo (`DELETE /api/kiosks/{id}`), verificación de borrado de contenedor, volumen y activo en JumpServer, liberando el puerto.

Ejecución del test E2E:
```bash
python3 scripts/e2e_test_runner.py
```

---

## 📖 Documentación Técnica

- [Guía de Arquitectura](docs/architecture.md): Detalles técnicos del ciclo de vida bajo demanda, relay TCP y compatibilidad RBAC.
- [Guía de Aprovisionamiento](docs/provisioning.md): Flujo paso a paso de registro de activos, firmas HMAC-SHA256 y rollback no destructivo.
- [Guía de Operaciones](docs/operations.md): Mantenimiento, respaldos, comandos de diagnóstico y políticas corporativas.
- [Guía de Solución de Problemas](docs/troubleshooting.md): Resolución de errores comunes (Guacamole 519, permisos de socket Docker, RBAC).
- [Manual de Usuario Web](docs/guia-usuario.html): Manual interactivo para administradores y operadores del panel.
