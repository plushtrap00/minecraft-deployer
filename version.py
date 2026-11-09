"""
version.py - Versión de la app.

Se muestra en el panel (Sistema → Actualizaciones y pie del menú) y en la
documentación de la API. Subir el número al publicar cambios grandes y
etiquetar el commit con `git tag v<versión>`.

Historial resumido:
- 2.0.0 (2026-11-09): revisión de seguridad (RAM validada en todos los caminos,
  .env/users.json privados, límites de subida, bloqueo de login por IP,
  escrituras atómicas, CSP), cambio de contraseña propia y restablecer la de
  otros usuarios.
- 1.x: todo lo anterior (sin numerar).
"""
APP_VERSION = "2.0.0"
