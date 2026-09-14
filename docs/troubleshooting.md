# Guía de Diagnóstico y Solución de Problemas: JumpServer Kiosk Manager

## 1. Error de Conexión en Guacamole / Luna ("Client error 519: Server refused connection")

### Causa 1: Incompatibilidad de Cifrado / Handshake RDP
- **Síntoma:** El cliente web de Luna muestra el error 519 de inmediato o tras 2 segundos de conectar.
- **Diagnóstico:**
  Inspeccionar los logs de Lion y del contenedor del quiosco:
  ```bash
  docker logs jms_lion --tail 30
  docker exec <kiosk_container> cat /var/log/xrdp.log | grep -i security
  ```
- **Solución:**
  Verificar que `/etc/xrdp/xrdp.ini` tenga:
  ```ini
  security_layer=negotiate
  crypt_level=high
  certificate=/etc/xrdp/cert.pem
  key_file=/etc/xrdp/key.pem
  ssl_protocols=TLSv1.2, TLSv1.3
  ```
  Y que los archivos de clave tengan permisos legibles:
  ```bash
  chmod 644 /etc/xrdp/cert.pem /etc/xrdp/key.pem
  ```

### Causa 2: Timing / Contenedor no responde a tiempo (Cold Start Timeout)
- **Síntoma:** El Dispatcher emite `Timeout waiting for XRDP on 172.17.0.x:3389`.
- **Solución:** El loop de sondeo en `backend/app/dispatcher/service.py` dispone de hasta 300 intentos (30 segundos con backoff de 100ms) para tolerar arranques fríos de contenedores en hosts con alta carga.

---

## 2. Incompatibilidad JumpServer v4 RBAC: `FieldError: Cannot resolve keyword 'is_superuser'`

- **Síntoma:** Durante el autodescubrimiento o ejecución manual en `manage.py shell`, JumpServer arroja:
  `django.core.exceptions.FieldError: Cannot resolve keyword 'is_superuser' into field.`
- **Causa:** JumpServer v4 (v4.10.x CE) eliminó el campo booleano `is_superuser` en el modelo `User`, reemplazándolo por el sistema de roles RBAC (`role`).
- **Solución:**
  - En lugar de consultar `is_superuser=True`, resolver el usuario mediante su rol:
    ```python
    from authentication.models import AccessKey
    from users.models import User
    user = User.objects.filter(role__name__icontains='Admin').first() or User.objects.filter(username='admin').first()
    ```
  - La lógica de autodescubrimiento en `backend/app/jumpserver/autodiscovery.py` ya gestiona esta jerarquía de forma segura con captura de excepciones.

---

## 3. Acceso y Permisos del Socket Docker (`/var/run/docker.sock`)

- **Síntoma:** El backend no detecta `jms_core`, emite advertencias `Docker daemon not yet available` o falla al arrancar contenedores efímeros.
- **Diagnóstico:**
  Verificar que `/var/run/docker.sock` esté montado en el contenedor backend:
  ```bash
  docker exec kiosk-manager-backend ls -l /var/run/docker.sock
  ```
- **Solución:**
  - Asegurar que `docker-compose.prod.yml` contenga el montaje `- /var/run/docker.sock:/var/run/docker.sock`.
  - Si el socket tiene permisos restringidos en el host, verificar pertenencia al grupo `docker` o ajustar permisos del socket.

---

## 4. Pantalla Blanca o Mensaje "This page is blocked"

### Causa: Variable TARGET_URL no heredada o about:blank bloqueado
- **Síntoma:** La sesión RDP conecta pero la pantalla muestra *"This page is blocked. Your organization doesn't allow you to view this site"*.
- **Diagnóstico:**
  La sesión PAM de XRDP no heredaba la variable `TARGET_URL` y abría `about:blank`, el cual estaba en la lista negra de `kiosk_policy.json`.
- **Solución:**
  1. En `kiosk-image/kiosk_policy.json`, remover `"about:blank"` de `URLBlocklist`.
  2. En `kiosk-image/entrypoint.sh`, asegurar que `echo "TARGET_URL=\"$TARGET_URL\"" >> /etc/environment`.
  3. En `kiosk-image/startwm.sh`, leer `/etc/environment` antes de ejecutar Chromium.

---

## 5. Diálogo de "Profile in use / SingletonLock" de Chromium

- **Síntoma:** Chromium no se dibuja o aparece un diálogo emergente de `xmessage` indicando que el perfil ya está en uso por otro proceso.
- **Causa:** El contenedor anterior se detuvo abruptamente y dejó el archivo de bloqueo `SingletonLock` en el volumen de datos del usuario.
- **Solución:**
  En `startwm.sh` y `entrypoint.sh`, se incluye la eliminación preventiva:
  ```bash
  rm -f "$USER_DATA_DIR"/Singleton*
  ```

---

## 6. Error 401 Unauthorized en el Panel Web (`:8080`)

- **Síntoma:** El panel web muestra *"Authentication required or invalid credentials"*.
- **Solución:** Las credenciales básicas por defecto para la API son `admin` / `admin`. Puedes verificar o ajustar los valores mediante las variables de entorno `PORTAL_ADMIN_USER` y `PORTAL_ADMIN_PASSWORD` en tu archivo `.env`.

---

## 7. El Dispositivo Web Destino Aparece "Offline"

- **Diagnóstico:**
  Usa el botón de prueba de conectividad (icono **⚡**) en la fila del quiosco en el panel `:8080` (endpoint `GET /api/kiosks/{id}/test-url`), o prueba un curl directo desde el host:
  ```bash
  curl -sI -m 3 <TARGET_URL>
  ```
- **Solución:**
  - Si devuelve `Connection Refused` o timeout, verificar la IP, máscara de red, enrutamiento en Proxmox/switch y que el servidor web del dispositivo destino esté escuchando en el puerto configurado.

---

## 8. Falla del Portapapeles en JumpServer Luna (`navigator.clipboard api not found`)

- **Síntoma:** Al abrir una sesión de quiosco en JumpServer Luna (`/luna/`), no es posible pegar contraseñas o texto en la consola web remota, o la consola del navegador arroja el error `navigator.clipboard api not found`.
- **Causa:** La especificación W3C para la API `navigator.clipboard` exige estrictamente un **Contexto Seguro (Secure Context)**. Si JumpServer opera sobre HTTP plano (`http://<SERVER_IP>/`), los navegadores modernos (Chrome, Firefox, Edge) bloquean el acceso al portapapeles por seguridad.
- **Solución:**
  1. Habilitar HTTPS en JumpServer (incluso con certificado autofirmado con SAN IP). Consulte el procedimiento detallado en la [Guía de Despliegue](deployment.md#1-requisitos-de-jumpserver-habilitación-de-https-para-portapapeles-en-luna).
  2. Al acceder por `https://<SERVER_IP>/luna/`, autorizar el permiso de lectura y escritura del portapapeles cuando el navegador lo solicite.
  3. En el archivo `.env` de Kiosk Manager, si se apunta internamente a JumpServer por HTTPS con certificado autofirmado, configurar `JMS_VERIFY_SSL=false` para que el backend de Kiosk Manager no falle por `SSLCertVerificationError`.

