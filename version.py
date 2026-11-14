"""
version.py - Versión de la app.

Se muestra en el panel (Sistema → Actualizaciones y pie del menú) y en la
documentación de la API. Cada commit sube la versión (2.A.B, cada cifra de 0
a 9: después de 2.0.9 va 2.1.0) y se etiqueta con `git tag v<versión>`.

Historial resumido:
- 2.1.2 (2026-11-14): contraste AA (4,5:1) en todos los temas: texto oscuro
  en los botones de color de los diálogos y la insignia roja, números de
  línea de logs, días de las tareas, rojo de los botones de peligro y
  colores §0/§1/§4/§5/§8/§9 de Minecraft.
- 2.1.1 (2026-11-14): esquinas concéntricas (radio interior = exterior -
  padding) en segmentados, interruptor de red, menú de Mods, listas de los
  desplegables, cajón del menú en móvil y muestras de tema.
- 2.1.0 (2026-11-14): el prompt de la consola en modo chat usa el icono de
  la pestaña Chat en vez del emoji 💬.
- 2.0.9 (2026-11-14): iconos coherentes: todas las acciones de barra y de
  fila llevan icono (mundos, usuarios, KubeJS, modloader, Forzar parada) y
  «Instalar servidor» usa el mismo icono que su pestaña «Subir un modpack».
- 2.0.8 (2026-11-14): el botón final de Instalar (subir, crear o descargar)
  destaca más: más grande, con icono y halo verde cuando ya se puede pulsar.
- 2.0.7 (2026-11-14): fuera etiquetas repetidas (aria-label igual al texto
  y tooltips repetidos en el menú, y el tooltip de «Más opciones» en Mods).
- 2.0.6 (2026-11-14): fuera insignias de relleno en el buscador de mods
  («Estable», «Más reciente» y el «Instalado» repetido junto al check).
- 2.0.5 (2026-11-13): fuera la paginación en las listas que ya tenían
  scroll (Config de mods, KubeJS, archivos de mundo, modales de mods y
  versiones de un mod): se ven enteras, con el total debajo.
- 2.0.4 (2026-11-12): en vez de juntarlas, las estadísticas enseñan solo las
  del online-mode actual (UUID offline o premium).
- 2.0.3 (2026-11-12): las estadísticas juntan al mismo jugador cuando se
  cambió online-mode con el mundo ya jugado (salía dos veces, una por UUID).
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
APP_VERSION = "2.1.2"
