"""
version.py - Versión de la app.

Se muestra en el panel (Sistema → Actualizaciones y pie del menú) y en la
documentación de la API. Cada commit sube la versión (2.A.B, cada cifra de 0
a 9: después de 2.0.9 va 2.1.0) y se etiqueta con `git tag v<versión>`.

Historial resumido:
- 3.2.8 (2026-11-25): parar el servidor con «stop» desde la consola o desde
  el juego ya no puede dejarlo colgado para siempre a medio cerrar («Waited N
  seconds attempting force stop!»): el panel deja de pedirle métricas en cuanto
  empieza a apagarse, que era lo que lo bloqueaba, y si aun así Minecraft no
  termina de cerrarse en el plazo de apagado, fuerza el cierre igual que el
  botón Detener.
- 3.2.7 (2026-11-25): los servidores cuyo script de arranque se reinicia solo
  («Restarting automatically in 10 seconds», como All the Mods 9 y 10) ya no
  vuelven a encenderse al pararlos con «stop» desde la consola o desde el
  juego. Si quieres que se levante tras una caída, usa el reinicio automático
  del panel.
- 3.2.6 (2026-11-24): la pregeneración se ve también en la página Servidor:
  con el servidor encendido y Chunky instalado aparece una tarjeta con el
  progreso (porcentaje, chunks, velocidad y tiempo restante) que se actualiza
  sola, sin cambiar de pestaña. Sin Chunky no aparece.
- 3.2.5 (2026-11-24): arreglo de la pregeneración. Si instalas Chunky con el
  servidor encendido, el panel avisa de que no funcionará hasta reiniciarlo y
  la tarea espera a ese reinicio, en vez de mandar a la consola comandos que
  Minecraft aún no conoce. Una pregeneración que se quedó así a medias vuelve
  a empezar sola tras el reinicio en vez de quedarse colgada.
- 3.2.4 (2026-11-24): el botón Pregenerar pasa a la cabecera de cada
  servidor, junto a Paquete para jugadores, y se ve desde cualquier pestaña
  (antes estaba escondido en Propiedades, junto a los mundos instalados).
- 3.2.3 (2026-11-24): repaso de la interfaz por dentro. Si un archivo de
  configuración ya no existe, el editor lo dice en vez de abrirlo con
  «undefined» dentro (y ya no se puede guardar ese texto encima); un fallo al
  buscar mods duplicados o solo de cliente ya no aparece como «todo en orden»,
  ni uno al sincronizar jugadores como «Sincronizado». Los lectores de
  pantalla anuncian el título de cada ventana y el nombre de los buscadores y
  filtros. El CSS está ordenado por secciones, sin cambios visibles.
- 3.2.2 (2026-11-24): arreglos. En la pantalla de entrada ya no se borra
  sola la contraseña que estás escribiendo (ni el aviso de error) cada 30
  segundos. Las listas de configuración, KubeJS y archivos del mundo ya
  muestran lo que el servidor crea en subcarpetas (p. ej. las estadísticas
  de un jugador nuevo) sin reiniciar el panel. Un log comprimido dañado
  dice que está dañado y se puede descargar, en vez de dar un error.
- 3.2.1 (2026-11-24): el código del panel pasa a tener licencia MIT
  (archivo LICENSE): software libre que cualquiera puede usar, modificar y
  repartir. Sin cambios en el funcionamiento.
- 3.2.0 (2026-11-24): pregenerar el mundo con Chunky, desde Propiedades. El
  panel solo lo instala si se lo pides (y lo deja fuera del paquete para
  jugadores), te dice antes cuánto ocupará según tu propio mundo, no empieza
  si no cabe en el disco, puede pausarse mientras haya jugadores y sigue sola
  tras un reinicio. Los servidores creados desde cero tampoco aceptan ya la
  EULA por su cuenta.
- 3.1.9 (2026-11-24): la app pasa a llamarse «Server Deployer for Minecraft».
  La EULA de Minecraft ya no se acepta sola: la primera vez que inicias cada
  servidor el panel te la enseña y la aceptas tú (queda en Actividad). El
  .mrpack del paquete para jugadores ya no mete los mods cuyo autor no
  permite repartirlos fuera de CurseForge. Nueva sección «Aviso legal» en la
  Ayuda.
- 3.1.8 (2026-11-24): «Paquete para jugadores» (en la cabecera del modpack y
  en la de Servidor mientras está encendido): el modpack del servidor listo
  para instalarlo en tu ordenador con los mismos mods y versiones, en formato
  CurseForge (.zip) o Modrinth (.mrpack). Si el servidor está vinculado a su
  modpack original, lleva también sus mods solo de cliente, resource packs,
  shaders y configuraciones. Las cuentas limitadas también pueden bajarlo.
- 3.1.7 (2026-11-24): por dentro: la huella de CurseForge con la que se
  reconocen los mods se calcula en un solo sitio, y la búsqueda de
  dependencias que faltan la calcula algo más rápido. Sin cambios para ti.
- 3.1.6 (2026-11-24): por dentro: las pruebas automáticas se ejecutan en
  GitHub cada vez que se publica un cambio (con Python 3.10 y 3.14), sin
  cambios para ti.
- 3.1.5 (2026-11-23): más pruebas automáticas: lectura de mods (Fabric,
  NeoForge, Quilt), versiones compatibles, duplicados, análisis de caídas,
  lectura de la consola y que ninguna ruta del panel pueda salirse de la
  carpeta del servidor. Arreglado: el análisis de una caída ahora también
  señala los mods cuyo paquete Java lleva guiones bajos.
- 3.1.4 (2026-11-23): por dentro: la instalación de modpacks se ha repartido
  en módulos más pequeños (Modrinth, CurseForge, piezas comunes y aviso de
  duplicados), sin cambios para ti. Textos: «añadir» en vez de «agregar».
- 3.1.3 (2026-11-23): «Cuándo se juega» en la página Jugadores: racha de días
  seguidos con alguien jugando, resumen de los últimos 7 días y mapa de calor
  por día y hora. Los lunes llega el resumen de la semana por Telegram o
  Discord. Logro nuevo: «En racha».
- 3.1.2 (2026-11-23): cuentas limitadas: lo ven todo, pero solo pueden
  encender, parar y reiniciar el servidor y gestionar la lista blanca (sin
  mods, mundos, copias, consola, descargas ni contraseña de RCON). Se eligen
  al crear la cuenta o desde la lista de Usuarios, y el cambio vale al
  momento. Arreglado: las cuentas que no son de administrador ya no reciben un
  error al ver el estado del firewall.
- 3.1.1 (2026-11-23): los reinicios y paradas programados pueden hacerse solo
  si no hay nadie conectado (si hay gente, esperan a que se vaya, hasta el
  máximo que elijas), y el servidor se puede apagar solo cuando lleva un rato
  vacío. Arreglado: el formulario de tareas enseñaba campos que no tocaban
  (Comando, Qué servidor).
- 3.1.0 (2026-11-23): registro de actividad en la página Usuarios (solo
  administrador): quién ha hecho qué y cuándo, con su IP (encender y parar,
  comandos de la consola, mods, copias, cambios de configuración, entradas al
  panel e intentos fallidos), y lo que el panel hace solo, como las copias
  automáticas o los reinicios tras una caída. Se filtra por persona y por
  tipo.
- 3.0.9 (2026-11-23): botón «Actualizar modpack» al gestionar un servidor: lo
  pasa a otra versión de su modpack de Modrinth o CurseForge haciendo antes
  una copia completa, sin tocar el mundo, server.properties ni las listas de
  jugadores, y conservando los mods que añadiste tú. Sigue en el servidor
  aunque se cierre el navegador. Los servidores instalados antes se vinculan a
  su modpack buscándolo una vez. Nuevo logro: Nueva temporada.
- 3.0.8 (2026-11-23): botón «Buscar actualizaciones» en la pestaña Mods:
  reconoce cada mod por su hash en Modrinth (y en CurseForge si hay clave de
  API), enseña los que tienen una versión más nueva para tu versión de
  Minecraft y modloader (sin pasar de estable a beta) y actualiza los que
  elijas comprobando lo descargado. Los archivos antiguos se guardan y se
  pueden volver a poner con «Deshacer». Nuevo logro: Puesta a punto.
- 3.0.7 (2026-11-23): verificación en dos pasos opcional para cada cuenta
  (botón del candado → Configurar): al entrar se pide también un código de 6
  cifras de una app del móvil, con 8 códigos de recuperación por si se pierde.
  El administrador puede quitársela a otra cuenta desde Usuarios, y la suya
  con set_password.py. Además, el bloqueo tras varios intentos fallidos ya no
  se borra al reiniciar el panel. Nuevo logro: Doble cerradura.
- 3.0.6 (2026-11-23): copias completas y destino secundario. En Modpacks →
  Copias, además de la copia del mundo hay una «Copia completa» con mods,
  configuración, scripts y listas de jugadores: al restaurarla, el servidor
  queda tal como estaba (también se puede elegir para las automáticas). En
  Automatización se puede elegir un destino secundario (otro disco, un NAS)
  donde se duplica cada copia; si se pierde la del disco principal, se
  restaura desde allí. Una copia que no cabe en el disco ya no se empieza, y
  el panel avisa cuando queda poco espacio. Nuevo logro: Cápsula del tiempo.
- 3.0.5 (2026-11-23): las actualizaciones de la app se deshacen solas si salen
  mal: antes de reiniciar se comprueba que la versión nueva carga (e instala
  sus librerías nuevas si las necesita), y si después no llega a arrancar o a
  responder, el panel vuelve solo a la versión anterior y lo avisa en Sistema
  → Actualizaciones. Tampoco se actualiza si hay archivos de la app cambiados
  a mano.
- 3.0.4 (2026-11-23): repaso del castellano: fuera las expresiones
  latinoamericanas que quedaban en textos, comentarios, instaladores y
  documentación (p. ej. «Último chequeo» pasa a ser «Última comprobación»).
- 3.0.3 (2026-11-23): los logros van con la cuenta, no con el navegador: se
  ven igual entres desde el dispositivo que entres. Los que ya tenías en un
  navegador se suben solos a tu cuenta la primera vez que entras con él.
- 3.0.2 (2026-11-20): las novedades de cada versión (Sistema → Actualizaciones)
  salen en el idioma de cada cuenta. Las traducciones van en un archivo por
  idioma, static/i18n/changelog/<idioma>.json.
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
APP_VERSION = "3.2.8"
