# Guía de Aprovisionamiento y Ciclo de Vida: JumpServer Kiosk Manager

## 1. Flujo de Aprovisionamiento (Alta de un Activo)

Cuando un administrador registra un nuevo dispositivo desde el panel web (`:8080`) o vía API REST (`POST /api/kiosks`), se ejecuta la siguiente secuencia transaccional con reversión automática (rollback) en caso de error:

```
[Administrador] -> [POST /api/kiosks]
      |
      v
1. Validación de Datos (Nombre, IP, Protocolo, Puerto, URL)
      |
2. Asignación de Puerto RDP libre (rango 33891 - 33920)
      |
3. Creación de Volumen Docker Persistente (kiosk_vol_<nombre>)
      |
4. Creación de Activo en JumpServer (POST /api/v1/assets/hosts/)
      |
5. Creación de Cuenta RDP en JumpServer (POST /api/v1/assets/accounts/)
      |
6. Creación de Permiso de Acceso (POST /api/v1/perms/asset-permissions/)
      |
7. Registro en Base de Datos Local SQLite (kiosk.db)
      |
8. Activación del Listener en el RDP Dispatcher (:puerto)
      v
[Activo Listo para Conectar]
```

---

## 2. Reversión Automática (Rollback Seguro)

Si ocurre algún fallo en cualquiera de los pasos intermedios (por ejemplo, rechazo de permisos en JumpServer o error de red):
- El sistema invoca el método `_rollback()`.
- Elimina los recursos en orden inverso estricto:
  1. Permiso en JumpServer
  2. Cuenta en JumpServer
  3. Activo en JumpServer
  4. Contenedor Docker (si existiese)
  5. Volumen Docker
- **Seguridad garantizada:** Solo se tocan los recursos etiquetados con `managed-by=jumpserver-kiosk-manager`. Ningún recurso preexistente de JumpServer o del host puede ser modificado o eliminado por error.

---

## 3. Edición en Caliente (Hot Update)

Cuando se actualiza un quiosco existente (`PUT /api/kiosks/{id}`):
- Se actualiza el nombre del dispositivo en la base de datos local y en JumpServer.
- Se actualiza la `target_url` y el tipo de dispositivo.
- El contenedor existente es destruido de forma segura (`stop_and_remove_container`).
- En la siguiente conexión que solicite el usuario en JumpServer Luna, el Dispatcher volverá a crear el contenedor con la nueva `TARGET_URL` aplicada automáticamente.

---

## 4. Desaprovisionamiento (Baja de un Activo)

Al eliminar un quiosco (`DELETE /api/kiosks/{id}`):
- Se retira la regla de autorización y permiso en JumpServer.
- Se elimina la cuenta RDP asociada en JumpServer.
- Se elimina el activo host de JumpServer.
- Se destruye el contenedor y se libera el volumen Docker de credenciales.
- Se detiene el listener del Dispatcher en ese puerto TCP.
- El puerto queda inmediatamente disponible para futuros dispositivos.
