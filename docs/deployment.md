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
| **Kiosk Manager Dashboard** | `8080/tcp` | HTTP | LAN Admin | Panel de control web Nginx + Vue 3 de administración de quioscos |
| **Backend Kiosk API** | `8000/tcp` | HTTP | Localhost (`host`) | API REST FastAPI de orquestación y aprovisionamiento |
| **Dispatcher RDP Pool** | `33891 - 33920` | TCP | Host (`0.0.0.0`) | Listeners TCP donde `jms_lion` conecta las sesiones gráficas |
| **Contenedores Efímeros** | `3389/tcp` | TCP | Red interna Docker (`172.17.0.x`) | XRDP en contenedores `pam-web-kiosk` bajo demanda |

Reglas UFW sugeridas en el host:
```bash
sudo ufw allow 443/tcp comment 'JumpServer HTTPS Luna'
sudo ufw allow 8080/tcp comment 'Kiosk Manager Dashboard'
sudo ufw allow 33891:33920/tcp comment 'Kiosk Dispatcher RDP Pool'
```

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
KIOSK_PORT_RANGE_END=33920

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

