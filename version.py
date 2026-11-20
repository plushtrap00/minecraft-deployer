"""
version.py - Versión de la app.

Se muestra en el panel (Sistema → Actualizaciones y pie del menú) y en la
documentación de la API. Cada commit sube la versión (2.A.B, cada cifra de 0
a 9: después de 2.0.9 va 2.1.0) y se etiqueta con `git tag v<versión>`.

Historial resumido:
- 3.0.1 (2026-11-20): las descripciones de Configuración → Constantes y su
  error de validación también salen en inglés.
- 3.0.0 (2026-11-20): traducciones terminadas: el panel entero en inglés, cada
  cuenta con su idioma y el de los avisos a elección del administrador. Los
  instaladores (install.sh y setup.py) preguntan primero el idioma, y el README
  tiene su versión en inglés.
- 2.2.7 (2026-11-20): los logros y las frases de la pantalla de entrada también
  en inglés, y los números con decimales usan la coma en español (1,5 GB).
- 2.2.6 (2026-11-20): los errores y mensajes del servidor salen en el idioma
  de cada cuenta, también el progreso de las instalaciones. En Configuración →
  Avisos se elige el idioma de los mensajes de Telegram y Discord.
- 2.2.5 (2026-11-20): cada cuenta tiene su propio idioma. Se aplica al
  entrar, desde cualquier dispositivo, y al cerrar sesión la pantalla de
  entrada vuelve al idioma por defecto.
- 2.2.4 (2026-11-20): en inglés ya sale también todo lo de gestionar
  modpacks: mods, búsqueda e instalación, dependencias, mundos, logs, KubeJS,
  RAM, modloader y el editor de archivos.
- 2.2.3 (2026-11-20): en inglés ya salen también los mensajes que aparecen
  al usar el panel: avisos, confirmaciones, estados del servidor, Sistema,
  Jugadores, Copias, Automatización, Usuarios y Configuración. Las fechas,
  los días de la semana y los números siguen el idioma elegido. Lo de
  gestionar modpacks llegará en la siguiente versión.
- 2.2.2 (2026-11-20): todo el texto fijo del panel ya sale en inglés si lo
  eliges: páginas, pestañas, formularios, ventanas y la Ayuda. Los mensajes
  que aparecen al usar el panel (avisos, estados, listas) llegarán en la
  siguiente versión.
- 2.2.1 (2026-11-20): primer paso para tener el panel en inglés. En
  Apariencia se elige el idioma (también desde la pantalla de entrada) y en
  Configuración el idioma por defecto. De momento están traducidos la
  entrada, el menú y Apariencia; el resto llegará en las próximas versiones.
- 2.2.0 (2026-11-20): los secretos ya no salen nunca hacia el navegador.
  JWT_SECRET, la API key de CurseForge, el token de Telegram y el webhook de
  Discord aparecen como «Guardado»: dejarlos vacíos conserva el que hay,
  escribir uno nuevo lo cambia y el botón «Quitar» lo borra.
- 2.1.9 (2026-11-20): el panel se ve bien en el móvil: Logs pone la lista
  encima del visor, el buscador de Mods ocupa su propia fila, la barra de
  disco de Instalar ya no desaparece, el título de Jugadores no se estruja y
  el botón del ojo es más fácil de pulsar. JWT_SECRET y la API key de
  CurseForge salen tapados en Configuración (con el ojo para verlos).
  Además: puntos suspensivos y comillas «» en los textos, y un único color
  de tema para las sombras.
- 2.1.8 (2026-11-20): antes de actualizar, Sistema → Actualizaciones enseña
  qué trae la nueva versión: las novedades de cada versión pendiente (sacadas
  de este historial) y, por su asunto, los commits que no tienen entrada.
- 2.1.7 (2026-11-20): animaciones más fluidas (barras de progreso,
  interruptores y el sol/luna de la escena se mueven con transform, no con
  width/left), iconos ocultos a los lectores de pantalla, los botones se
  hunden 1px al pulsarlos y nada se sale por los lados (overflow-x: clip,
  sin 100vw).
- 2.1.6 (2026-11-14): respuestas animadas: el campo que falta tiembla y se
  marca (sin diálogo modal), lo recién añadido destella en su lista y los
  botones de guardar confirman con «Guardado».
- 2.1.5 (2026-11-14): estado de carga en todos los botones que esperan al
  servidor (spinner, sin doble clic): jugadores, mundos, mods, KubeJS,
  editor, server.properties, usuarios, copias, tareas y Forzar parada.
- 2.1.4 (2026-11-14): saltos de línea equilibrados en títulos y textos
  centrados (text-wrap: balance) y sin palabras huérfanas en párrafos y
  pistas (text-wrap: pretty).
- 2.1.3 (2026-11-14): cifras tabulares en todo el panel; las métricas (TPS,
  MSPT, jugadores, RAM) ya no cambian de ancho al contar en la fuente de
  bloque.
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
APP_VERSION = "3.0.1"
