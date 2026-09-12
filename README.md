# JumpServer Kiosk Manager 🚀

**JumpServer Kiosk Manager** es una solución integral y autónoma para la gestión y aprovisionamiento automatizado de **activos web aislados mediante RDP** en **JumpServer Community Edition (CE)**.

Permite acceder a consolas web de infraestructura crítica (Zabbix, switches, routers MikroTik, firewalls FortiGate, hipervisores Proxmox/VMware, consolas iDRAC/iLO, cámaras CCTV, etc.) a través de JumpServer Luna sin requerir complementos Enterprise, con auditoría centralizada, grabación de sesiones y autenticación robusta.

---

## 🌟 Características Principales

- **Arquitectura Bajo Demanda (Ephemeral On-Demand):**
  - Consumo de **0% CPU y 0 MB RAM en reposo**.
  - Los contenedores Docker se inician automáticamente solo cuando un operador solicita la conexión en JumpServer Luna (detección del paquete `RDP-SYN`).
  - Apagado automático programado tras **120 segundos de inactividad** después de cerrar la sesión.
  - Límite de recursos estricto por sesión: `768 MB RAM`, `1 CPU`, `256 MB /dev/shm`.
- **Integración Nativa con JumpServer 4.x:**
  - Creación automática de Activos (`/api/v1/assets/hosts/`), Cuentas de Acceso y Reglas de Autorización mediante firmas criptográficas **HMAC-SHA256**.
  - Parámetros de seguridad optimizados para JumpServer Lion (`security: any`, `ignore_cert: true`).
- **Imagen de Quiosco Ultraligera (`pam-web-kiosk:v1`):**
  - Basada en Debian 12 Bookworm Slim + Openbox + XorgXRDP + Chromium Native.
  - Políticas gestionadas corporativas (`kiosk_policy.json`): bloquea atajos peligrosos, F12, descargas y navegación externa, habilitando el gestor de contraseñas integrado.
  - Persistencia de credenciales y cookies mediante volúmenes Docker dedicados por dispositivo.
- **Dashboard Web de Administración (`:8080`):**
  - Desplegado con Vue 3 + FastAPI + Nginx Reverse Proxy.
  - **Edición en Caliente:** Permite modificar URLs de destino, nombres y tipos de dispositivo en cualquier momento.
  - **One-Click Connect:** Botón de conexión directa que abre la sesión gráfica en JumpServer Luna.
  - **Sondeo de Conectividad HTTP en Vivo:** Valida si el equipo destino está online con código HTTP y latencia en milisegundos.
  - **Limpieza de Caché y Sesión:** Resetea cookies y sesiones web sin eliminar el activo.
  - **Buscador y Filtros:** Organización instantánea por nombre, IP y tipo de equipo.
  - **Monitor de Ahorro de Memoria:** Muestra en tiempo real la RAM ahorrada en Proxmox/host.

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
|                           JUMPSERVER COMMUNITY                              |
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
|  | SQLite / Models    |                                   |                 |
|  +---------+----------+                                   |                 |
+------------|----------------------------------------------|-----------------+
             | Docker Engine API                            | Internal Bridge
             +----------------------+-----------------------+ (172.17.0.x:3389)
                                    v
+-----------------------------------------------------------------------------+
|                     CONTENEDOR KIOSK (On-Demand)                            |
|                       pam-web-kiosk:v1                                      |
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

## 🚀 Despliegue Rápido y Puertos

| Servicio | Puerto | Descripción |
| :--- | :--- | :--- |
| **Kiosk Manager Dashboard** | `8080/tcp` | Interfaz web de administración (Nginx) |
| **Backend FastAPI** | `8000/tcp` | API interna de orquestación y aprovisionamiento |
| **RDP Dispatcher Pool** | `33891 - 33920` | Rango de puertos asignados a los quioscos RDP |
| **JumpServer Web/Luna** | `80/tcp` | Portal principal de acceso JumpServer |

### Comandos de Control del Servicio
```bash
# Estado del backend y dispatcher
systemctl status kiosk-backend.service

# Reiniciar el backend
systemctl restart kiosk-backend.service

# Ver logs del Dispatcher en tiempo real
journalctl -u kiosk-backend.service -f

# Reconstruir imagen de quiosco
docker build -t pam-web-kiosk:v1 /root/jumpserver-kiosk-manager/kiosk-image
```

---

## 📖 Documentación Detallada

- [Guía de Arquitectura](docs/architecture.md): Detalles técnicos del ciclo de vida bajo demanda y relay TCP.
- [Guía de Aprovisionamiento](docs/provisioning.md): Flujo paso a paso de registro de activos y firmas JumpServer.
- [Guía de Operaciones](docs/operations.md): Mantenimiento, respaldos, comandos útiles y políticas corporativas.
- [Guía de Solución de Problemas](docs/troubleshooting.md): Resolución de errores comunes (Guacamole 519, permisos PAM, certificados).
- [Manual de Usuario Web](docs/guia-usuario.html): Manual interactivo para administradores y operadores.
