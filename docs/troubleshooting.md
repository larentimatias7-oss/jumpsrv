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
- **Solución:** El loop de sondeo en `backend/app/dispatcher/service.py` debe tener al menos 100 intentos (10 segundos) para tolerar arranques fríos de contenedores en hosts con carga.

---

## 2. Pantalla Blanca o Mensaje "This page is blocked"

### Causa: Variable TARGET_URL no heredada o about:blank bloqueado
- **Síntoma:** La sesión RDP conecta pero la pantalla muestra *"This page is blocked. Your organization doesn't allow you to view this site"*.
- **Diagnóstico:**
  La sesión PAM de XRDP no heredaba la variable `TARGET_URL` y abría `about:blank`, el cual estaba en la lista negra de `kiosk_policy.json`.
- **Solución:**
  1. En `kiosk-image/kiosk_policy.json`, remover `"about:blank"` de `URLBlocklist`.
  2. En `kiosk-image/entrypoint.sh`, asegurar que `echo "TARGET_URL=\"$TARGET_URL\"" >> /etc/environment`.
  3. En `kiosk-image/startwm.sh`, leer `/etc/environment` antes de ejecutar Chromium.

---

## 3. Diálogo de "Profile in use / SingletonLock" de Chromium

- **Síntoma:** Chromium no se dibuja o aparece un diálogo emergente de `xmessage` indicando que el perfil ya está en uso por otro proceso.
- **Causa:** El contenedor anterior se detuvo abruptamente y dejó el archivo de bloqueo `SingletonLock` en el volumen de datos del usuario.
- **Solución:**
  En `startwm.sh` y `entrypoint.sh`, incluir la eliminación preventiva:
  ```bash
  rm -f "$USER_DATA_DIR"/Singleton*
  ```

---

## 4. Error 401 Unauthorized en el Panel Web (`:8080`)

- **Síntoma:** El panel web muestra *"Authentication required or invalid credentials"*.
- **Solución:** Las credenciales básicas por defecto para la API son `admin` / `admin`. Puedes verificar o ajustar los valores en `backend/app/auth/basic_auth.py` o en las variables de entorno `KIOSK_ADMIN_USER` y `KIOSK_ADMIN_PASS`.

---

## 5. El Dispositivo Web Destino Aparece "Offline"

- **Diagnóstico:**
  Usa el botón de prueba de conectividad (icono **⚡**) en la fila del quiosco en el panel `:8080`, o prueba un curl directo desde el host:
  ```bash
  curl -sI -m 3 <TARGET_URL>
  ```
- **Solución:**
  - Si devuelve `Connection Refused` o timeout, verificar la IP, máscara de red, enrutamiento en Proxmox y que el servidor web del dispositivo destino esté escuchando en el puerto configurado.
