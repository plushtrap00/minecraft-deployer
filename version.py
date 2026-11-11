"""
version.py - Versión de la app.

Se muestra en el panel (Sistema → Actualizaciones y pie del menú) y en la
documentación de la API. Cada commit sube la versión (2.A.B, cada cifra de 0
a 9: después de 2.0.9 va 2.1.0) y se etiqueta con `git tag v<versión>`.

Historial resumido:
- 2.0.2 (2026-11-11): las métricas de la página Servidor se refrescan cada
  10 s con datos recién pedidos y las gráficas de Rendimiento cada minuto.
- 2.0.1 (2026-11-11): ops, whitelist y bans se adaptan al online-mode actual
  al arrancar (cambiarlo después de instalar dejaba sin op a los jugadores).
  Incluye también lo de ese día sin numerar: ver los mods de un modpack antes
  de instalarlo, listas sacadas del Server Pack de CurseForge, variables.txt
  de ServerPackCreator respetado y scripts colgados en «Press any key».
- 2.0.0 (2026-11-09): revisión de seguridad (RAM validada en todos los caminos,
  .env/users.json privados, límites de subida, bloqueo de login por IP,
  escrituras atómicas, CSP), cambio de contraseña propia y restablecer la de
  otros usuarios.
- 1.x: todo lo anterior (sin numerar).
"""
APP_VERSION = "2.0.2"
