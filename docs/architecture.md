# Guía de Arquitectura: JumpServer Kiosk Manager

## 1. Visión General

JumpServer Kiosk Manager resuelve la necesidad de conectar operadores a aplicaciones y dispositivos web internos mediante JumpServer Community Edition sin requerir el módulo comercial Web Terminal.

Para lograr esto de forma segura, escalable y con mínimo impacto en recursos (especialmente en entornos Proxmox VE con contenedores LXC), se implementó una **Arquitectura Bajo Demanda (Ephemeral On-Demand)**.

---

## 2. Componentes Clave

### A. RDP Dispatcher (`backend/app/dispatcher/service.py`)
- **Proxy TCP Transparente Asíncrono (`asyncio`):** Escucha en `0.0.0.0` en cada puerto asignado del rango `33891 - 33920`.
- **Detección de Conexión (RDP-SYN):** Al recibir la primera solicitud de conexión desde `jms_lion` (Apache Guacamole), el Dispatcher:
  1. Consulta la base de datos para obtener los parámetros del quiosco (`container_name`, `volume_name`, `target_url`, etc.).
  2. Arranca el contenedor Docker de forma instantánea (`ensure_container_running`).
  3. Ejecuta un bucle de sondeo con backoff corto hacia `172.17.0.x:3389` dentro del contenedor hasta que XRDP esté completamente operativo y acepte tráfico.
  4. Realiza la conmutación bidireccional de sockets cliente <-> XRDP con liberación asíncrona inmediata (`asyncio.FIRST_COMPLETED`).
- **Temporizador de Inactividad (Idle Shutdown):** Cuando la sesión RDP finaliza y no quedan conexiones activas, programa un temporizador de **120 segundos**. Si no hay nuevas conexiones en esa ventana, detiene el contenedor para liberar el 100% de la memoria RAM y CPU.

### B. Contenedor Quiosco (`pam-web-kiosk:v1`)
- **Base:** Debian 12 (Bookworm) Slim.
- **Gestor de Pantalla:** XRDP + backend nativo `xorgxrdp` + servidor Xorg con aceleración por software optimizada.
- **Gestor de Ventanas:** `openbox` (ultraligero, consume <20 MB RAM, sin barras de tareas ni menús contextuales conflictivos).
- **Navegador Web:** Chromium en modo `--kiosk` y `--app="TARGET_URL"`.
- **Heredabilidad de Entorno:** El script `entrypoint.sh` inyecta las variables del contenedor (`TARGET_URL`, `KIOSK_NAME`) en `/etc/environment`, permitiendo que la sesión PAM no privilegiada (`kiosk`) lea y navegue directamente a la URL indicada sin intermediarios ni pantallas en blanco.
- **Persistencia de Credenciales:** Monta un volumen Docker individual (`volume_name`) en `/home/kiosk/.config/chromium` que preserva cookies, sesiones y el almacén de contraseñas básico (`--password-store=basic --enable-features=PasswordManager`).
- **Límites de Seguridad:**
  - `mem_limit`: 768 MB (evita saturación en el host).
  - `nano_cpus`: 1.0 core.
  - `shm_size`: 256 MB.

### C. Integración Criptográfica con JumpServer (`backend/app/jumpserver/`)
- **Autenticación HMAC-SHA256:** Firma cada petición HTTP saliente con cabecera `Date` y clave de acceso del sistema JumpServer (`JMS_KEY_ID` / `JMS_SECRET_FILE`).
- **Aprovisionamiento Automático:**
  1. Activo de Tipo Windows/Host en `/api/v1/assets/hosts/` asignado al nodo `/DEFAULT`.
  2. Protocolo RDP con parámetros `security: any` e `ignore_cert: true` para compatibilidad universal con Lion.
  3. Cuenta de acceso con contraseña aleatoria de 32 caracteres generada criptográficamente.
  4. Regla de Permiso y Autorización (`/api/v1/perms/asset-permissions/`) vinculada al grupo de administradores.

### D. Interfaz de Administración (`frontend/` + Nginx `:8080`)
- Single Page Application (SPA) construida en **Vue 3** y empaquetada con **Vite**.
- Servida por **Nginx** en el puerto `8080` que actúa como reverse proxy hacia la API FastAPI (`127.0.0.1:8000/api/`).
- Admite operaciones CRUD completas (`GET`, `POST`, `PUT`, `DELETE`), pruebas de red en vivo y acceso directo con un clic a JumpServer Luna.
