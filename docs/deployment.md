# Guía de Despliegue en Producción: JumpServer Kiosk Manager

Esta guía detalla el procedimiento oficial y validado para desplegar **JumpServer Kiosk Manager** en entornos corporativos de producción junto con **JumpServer Community Edition (v4.10.x CE)**.

---

## 1. Requisitos de JumpServer: Habilitación de HTTPS para Portapapeles en Luna

> [!IMPORTANT]
> **Contexto Seguro Obligatorio (W3C Secure Context):**  
> Para que los navegadores web modernos (Google Chrome, Microsoft Edge, Mozilla Firefox) permitan a la interfaz web de JumpServer Luna acceder a la API nativa de portapapeles (`navigator.clipboard`), la aplicación **debe servirse estrictamente bajo HTTPS** (o `localhost`).  
> Si JumpServer opera bajo HTTP plano (`http://<SERVER_IP>/`), el navegador bloquea el acceso al portapapeles arrojando el error `navigator.clipboard api not found`, lo que imposibilita copiar y pegar contraseñas o comandos en las consolas web remotas de los quioscos.

### Procedimiento Paso a Paso para Habilitar HTTPS en JumpServer

#### Paso 1: Generación de Certificados SSL con SAN IP (Subject Alternative Name)
Para evitar que los navegadores rechacen el certificado por falta de coincidencia de nombre o IP, genere un certificado autofirmado que incluya explícitamente la extensión `subjectAltName` con la dirección IP del servidor y loopback:

```bash
# Crear directorio de certificados de Nginx en JumpServer
mkdir -p /opt/jumpserver/config/nginx/cert

# Generar certificado X.509 y clave privada RSA (sustituir <SERVER_IP> por la IP del host)
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /opt/jumpserver/config/nginx/cert/server.key \
  -out /opt/jumpserver/config/nginx/cert/server.crt \
  -subj "/C=AR/ST=Santa Fe/L=Rosario/O=Milicic/CN=<SERVER_IP>" \
  -addext "subjectAltName=IP:<SERVER_IP>,IP:127.0.0.1"

# Asegurar permisos estrictos en la clave privada
chmod 600 /opt/jumpserver/config/nginx/cert/server.key
chmod 644 /opt/jumpserver/config/nginx/cert/server.crt
```

#### Paso 2: Configuración de Parámetros en JumpServer
Edite el archivo de configuración global `/opt/jumpserver/config/config.txt` y establezca los siguientes parámetros:

```ini
# Habilitar terminación SSL en el Nginx de JumpServer
USE_SSL=true
SSL_CERTIFICATE=server.crt
SSL_CERTIFICATE_KEY=server.key

# Declarar la IP o FQDN del servidor para evitar advertencias de Host
DOMAINS=<SERVER_IP>

# Orígenes confiables para CSRF en peticiones HTTPS
CSRF_TRUSTED_ORIGINS=https://<SERVER_IP>,http://<SERVER_IP>
```

#### Paso 3: Reglas de Firewall y Reinicio de JumpServer
Abra el puerto seguro `443/tcp` en el firewall del host y aplique los cambios en JumpServer:

```bash
# Habilitar puerto HTTPS en UFW
sudo ufw allow 443/tcp
sudo ufw reload

# Reiniciar todos los servicios de JumpServer
jmsctl restart
```

Verifique que JumpServer responda correctamente en `https://<SERVER_IP>/` y acceda desde el navegador aceptando la advertencia de certificado autofirmado. Al abrir una sesión en Luna, el navegador solicitará permiso para acceder al portapapeles (`Permitir ver texto e imágenes copiados en el portapapeles`), habilitando la funcionalidad bidireccional completa.

#### Paso 4: Ajuste de Conectividad en Kiosk Manager (`JMS_VERIFY_SSL`)
Cuando JumpServer opera bajo HTTPS con un certificado autofirmado o CA privada interna no instalada en el almacén raíz del sistema operativo, el cliente HTTP de `kiosk-manager` fallará con `SSLCertVerificationError` a menos que se configure la validación correspondiente:

En el archivo `/opt/jumpsrv/.env`:
```dotenv
# Apuntar a la URL segura de JumpServer
JMS_BASE_URL=https://127.0.0.1:443

# Desactivar la verificación estricta de CA para certificados autofirmados
JMS_VERIFY_SSL=false
```

Si en su infraestructura dispone del certificado de la CA privada corporativa, puede mantener `JMS_VERIFY_SSL=true` y montar el archivo CA mediante:
```dotenv
JMS_VERIFY_SSL=true
JMS_CA_BUNDLE=/app/secrets/corporate_ca.crt
```

---

## 2. Matriz de Puertos y Requisitos de Red

| Servicio | Puerto | Protocolo | Exposición | Función |
| :--- | :--- | :--- | :--- | :--- |
| **JumpServer Web/Luna** | `443/tcp` | HTTPS | LAN / WAN | Interfaz web principal, consola Luna Guacamole y API REST |
| **JumpServer Web (HTTP)**| `80/tcp` | HTTP | LAN | Redirección a HTTPS o acceso interno |
| **Kiosk Manager Dashboard (HTTPS)** | `8443/tcp` | HTTPS | LAN Admin | Panel seguro con TLS autofirmado y soporte pleno W3C Clipboard |
| **Kiosk Manager Dashboard (HTTP)** | `8080/tcp` | HTTP | LAN Admin | Panel web compatible HTTP con fallback de portapapeles |
| **Backend Kiosk API** | `8000/tcp` | HTTP | Localhost (`host`) | API REST FastAPI de orquestación y aprovisionamiento |
| **Dispatcher RDP Pool** | `33891 - 34090` | TCP | Host (`0.0.0.0`) | Listeners TCP donde `jms_lion` conecta las sesiones gráficas (200 puertos) |
| **Contenedores Efímeros** | `3389/tcp` | TCP | Red interna Docker (`172.17.0.x`) | XRDP en contenedores `pam-web-kiosk` bajo demanda |

Reglas UFW sugeridas en el host:
```bash
sudo ufw allow 443/tcp comment 'JumpServer HTTPS Luna'
sudo ufw allow 8443/tcp comment 'Kiosk Manager HTTPS Dashboard'
sudo ufw allow 8080/tcp comment 'Kiosk Manager HTTP Dashboard'
sudo ufw allow 33891:34090/tcp comment 'Kiosk Dispatcher RDP Pool'
```

---

## 2.1. Habilitación y Auto-Aprovisionamiento SSL/TLS en Kiosk Manager

> [!TIP]
> **Soporte de Portapapeles y Contexto Seguro:**
> En los navegadores modernos, la API nativa de portapapeles (`navigator.clipboard`) solo se habilita en conexiones seguras (**HTTPS** o `localhost`). Si accede mediante HTTP a una IP privada (ej: `http://172.30.20.62:8080`), la API nativa se bloquea.
> Para solucionar esto:
> 1. **Fallback Inteligente en la App:** Se implementó un fallback transparente mediante `document.execCommand('copy')` para que el botón de copiar funcione siempre, incluso en HTTP.
> 2. **Auto-Generación de Certificado TLS:** Kiosk Manager genera automáticamente un certificado autofirmado con SAN (Subject Alternative Names para IP y localhost) al iniciar el contenedor frontend o ejecutando el script oficial.

### Generación y Prueba Manual del Certificado SSL
En cualquier momento, en nuevas instalaciones o servidores desplegados:
```bash
# Detecta la IP del host y genera ssl/kiosk.crt y ssl/kiosk.key con SAN
./scripts/setup_ssl.sh

# O forzar una IP específica
./scripts/setup_ssl.sh --force --ip 172.30.20.62

# Verificar el estado y handshake del certificado
python3 scripts/kioskctl check-ssl --host 172.30.20.62 --port 8443
```
Una vez activo, acceda al panel seguro mediante:
`https://<SERVER_IP>:8443/luna/`


---

## 3. Despliegue de JumpServer Kiosk Manager

### 3.1. Prerrequisitos en el Host
Verifique que el host cuente con Docker Engine y Docker Compose v2:
```bash
docker --version
docker compose version
```

### 3.2. Instalación del Stack de Producción
```bash
# Crear directorio de trabajo
mkdir -p /opt/jumpsrv && cd /opt/jumpsrv

# Descargar docker-compose de producción
curl -sSL https://raw.githubusercontent.com/larentimatias7-oss/jumpsrv/main/docker-compose.prod.yml -o docker-compose.yml

# Crear archivo de configuración .env
cp .env.example .env  # o configurar manualmente
```

### 3.3. Configuración de Variables en `.env`
```dotenv
# Conexión con JumpServer
JMS_BASE_URL=https://127.0.0.1:443
JMS_VERIFY_SSL=false
JMS_ORG_ID=00000000-0000-0000-0000-000000000002

# Credenciales de API (se autodescubren de jms_core si se dejan vacías)
JMS_KEY_ID=
JMS_SECRET_KEY=

# Configuración de Nodos de Activos y Herencia RBAC (Luna)
JMS_DEFAULT_NODE_NAME="SWITCHES ROSARIO"
# JMS_DEFAULT_NODE_ID=8efe99ea-dee5-4ba0-9ad2-1978d91e8f65

# IP del Host para registro de activos RDP en JumpServer
KIOSK_HOST_IP=<IP_LAN_HOST>
KIOSK_PORT_RANGE_START=33891
KIOSK_PORT_RANGE_END=34090

# Credenciales administrativas del Dashboard (:8080)
PORTAL_ADMIN_USER=admin
PORTAL_ADMIN_PASSWORD=admin
```

### 3.4. Herencia de Permisos RBAC en JumpServer Luna
Para habilitar que los operadores accedan automáticamente a los quioscos creados:
1. En la consola de JumpServer, navegue a **Assets > Asset Permissions** (Permisos de Activos).
2. Cree una regla de autorización asignando los Nodos correspondientes (por ejemplo, nodo `/SWITCHES ROSARIO`) a los grupos de usuarios autorizados (por ejemplo, grupo `Switch Admins Rosario`).
3. Todo quiosco aprovisionado o asignado a esa categoría en **Kiosk Manager** se inyectará directamente con el UUID del nodo en `nodes: [node_uuid]`. De esta forma, el quiosco aparecerá de manera inmediata en la interfaz Luna de los usuarios del grupo con los permisos delegados en la carpeta, sin requerir asignación manual de permisos por dispositivo.

### 3.5. Inicialización y Arranque
```bash
docker compose pull
docker compose up -d
```

---

## 4. Verificación y Healthcheck

1. **Verificar estado de los contenedores:**
   ```bash
   docker compose ps
   ```
2. **Inspeccionar logs del backend:**
   ```bash
   docker compose logs -f backend
   ```
   Debe observar la inicialización correcta del Dispatcher, la detección de credenciales JumpServer y el log informativo `verify_ssl`.
3. **Comprobar listeners RDP:**
   ```bash
   ss -tulpn | grep 3389
   ```
4. **Acceso al Dashboard:**
   Navegar a `http://<SERVER_IP>:8080/` e iniciar sesión con las credenciales configuradas en `PORTAL_ADMIN_USER` / `PORTAL_ADMIN_PASSWORD`.

---

## 5. Mantenimiento, Reconciliación y Resiliencia Empresarial

### 5.1. Reconciliación Periódica y Garbage Collection de Activos
Para limpiar de forma proactiva activos huérfanos en JumpServer cuyos contenedores o quioscos locales ya hayan sido eliminados (por ejemplo, tras pruebas manuales o caídas del host):

```bash
# Invocar el endpoint de reconciliación administrativa
curl -X POST -u admin:admin http://127.0.0.1:8000/api/kiosks/reconcile-jms
```

Respuesta esperada:
```json
{
  "total_jms_assets": 12,
  "managed_jms_assets": 4,
  "local_kiosks_count": 3,
  "purged_count": 1,
  "purged_assets": [
    {"id": "a918f0c2-1234-5678-9abc-def012345678", "name": "OLD-TEST-KIOSK"}
  ]
}
```

Puede programarse como una tarea de cron periódica en el host:
```bash
# Ejecutar garbage collection cada noche a las 03:00 AM
0 3 * * * curl -s -X POST -u admin:admin http://127.0.0.1:8000/api/kiosks/reconcile-jms > /dev/null
```

De forma predeterminada, el backend de FastAPI ejecuta también un bucle asíncrono de reconciliación en segundo plano cada 12 horas. Este intervalo puede ajustarse en `.env`:
```dotenv
# Intervalo en horas para la reconciliación automática (0 para desactivar)
JMS_RECONCILE_INTERVAL_HOURS=12
```

### 5.2. Verificación de Socket RDP (Readiness Gate)
Si se desea exigir la apertura exitosa del socket XRDP antes de crear el activo en JumpServer, active la variable en `.env`:
```dotenv
KIOSK_VERIFY_RDP_READINESS=true
```
Esto evita la creación de activos no funcionales si un contenedor experimenta demoras de inicio o fallas en el servicio XRDP.

### 5.3. Resiliencia HTTP y Manejo de Tokens
El backend implementa de forma transparente:
- Reintentos con retroceso exponencial de 1 a 4 segundos ante errores de transporte (`502`, `503`, `504`, caídas de red o reinicios de `jms_core`).
- Reautenticación automática e invalidación de credenciales en caché si JumpServer responde `401 Unauthorized` o `403 Forbidden`, sin interrumpir las operaciones del usuario.

### 5.4. Autenticación Delegada (SSO) y Aplicación Web en JumpServer
Para integrar de forma nativa la experiencia del operador entre JumpServer y Kiosk Manager:
1. **Delegación de Sesión por Cookie (`jms_sessionid`):**
   - Cuando el operador navega a Kiosk Manager habiendo iniciado sesión en el bastión (`https://172.30.20.62`), el navegador propaga la cookie de sesión `jms_sessionid`.
   - Kiosk Manager valida la identidad contra el bastión sin solicitar credenciales adicionales.
   - Si no hay sesión activa, el Auth Guard visual presenta un botón directo hacia `https://172.30.20.62/ui/#/login`.
2. **Acceso Directo desde JumpServer ("Agregar Sitio WEB"):**
   - Configure en su archivo `.env`:
     ```dotenv
     # URL con la que los operadores acceden a Kiosk Manager
     KIOSK_MANAGER_PUBLIC_URL=http://172.30.20.62:8000
     # Registro automático en JumpServer al arrancar el backend
     JMS_SYNC_WEB_APP_ENABLED=true
     ```
   - Al iniciar, Kiosk Manager da de alta automáticamente la aplicación web en JumpServer con el nombre `"Agregar Sitio WEB"`.
   - Los operadores con permisos asignados verán el acceso directo en su consola de JumpServer para abrir Kiosk Manager en una pestaña nueva de forma transparente.

