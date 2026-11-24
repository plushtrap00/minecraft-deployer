# Server Deployer for Minecraft

**Español** · [English](README.en.md)

Panel web (FastAPI + JavaScript sin frameworks) para crear y gestionar servidores de Minecraft modded: instalar modpacks completos desde Modrinth/CurseForge, buscar y actualizar mods, gestionar jugadores (ops/whitelist/bans), mundos, consola en vivo con chat, métricas e historial, firewall, copias de seguridad, reinicio automático si el servidor se cae, tareas programadas y avisos por Telegram o Discord. Pensado para autoalojarse en tu propio servidor o VPS Linux.

El panel está en **español de España y en inglés**: cada cuenta elige el suyo (ver [Idiomas](#idiomas)).

Y como gestionar un servidor de Minecraft no tiene por qué ser aburrido: cuatro temas con su propio fondo pixelado, una escena que pasa de noche a día cuando el servidor arranca, cabezas de los jugadores, celebraciones y más de treinta logros por desbloquear (algunos secretos).

**Versión actual: 3.0.0** (se ve en **Sistema → Actualizaciones de la app**). Novedades en [Versiones](#versiones).

## Requisitos

- Linux (nativo, o Docker sobre cualquier sistema operativo).
- Acceso `sudo` para la instalación nativa (crea un servicio `systemd`).
- Docker + Docker Compose para la instalación en contenedor.

Hace falta Python 3.10 o posterior (Ubuntu 22.04 o Debian 12 en adelante ya lo traen). Python y Java se instalan solos si faltan (en instalación nativa y en modo "Contenedor" de `install.sh`); en la imagen Docker ya vienen incluidos.

## Instalación en Linux nativo (recomendada)

Instala la app como servicio `systemd`: arranca con el sistema y se reinicia sola si se cae.

```bash
git clone https://github.com/plushtrap00/minecraft-deployer
cd minecraft-deployer
bash install.sh
```

El instalador te va preguntando:

- **Idioma** (español o inglés): el del propio instalador y el idioma por defecto del panel.
- **Modo de instalación** → elige `2) Nativo`.
- Carpeta donde instalar la app.
- Usuario y contraseña para entrar al panel.
- Puerto de la interfaz web (por defecto `8000`) y puerto de Minecraft (`25565`).
- Dominio público (opcional — para que los jugadores se conecten con un nombre en vez de una IP).
- Clave de API de CurseForge (opcional — **Modrinth funciona sin ella**; se consigue gratis en [console.curseforge.com](https://console.curseforge.com/#/api-keys)).
- Auto-actualización (opcional — la app comprueba sola si hay una versión nueva en GitHub).
- Avisos por Telegram (opcional — ver [Avisos por Telegram y Discord](#avisos-por-telegram-y-discord)).
- Versión de Java (`17` o `21`, según qué versiones de Minecraft vayas a alojar).
- Dónde se guardan los modpacks/servidores en disco.

Al terminar, la app queda accesible en `http://<IP-del-servidor>:<puerto>` y corriendo como servicio `minecraft-deployer`.

Volver a ejecutar `bash install.sh` más adelante actualiza el código (si hay commits nuevos en GitHub) y reinicia el servicio, sin volver a pedirte la configuración.

Comandos útiles:

```bash
sudo journalctl -u minecraft-deployer -f   # ver logs en vivo
sudo systemctl stop minecraft-deployer     # parar
sudo systemctl start minecraft-deployer    # arrancar
bash ~/minecraft-deployer/install.sh       # actualizar / reconfigurar
```

## Instalación con Docker

### Opción A — `docker compose` (recomendada)

```bash
git clone https://github.com/plushtrap00/minecraft-deployer
cd minecraft-deployer
```

Genera la configuración con el asistente interactivo `setup.py`: te pregunta el idioma (español o inglés, también el idioma por defecto del panel), usuario y contraseña de administrador, puertos, versión de Java, dónde guardar los modpacks (volumen Docker o una carpeta del host) y demás opciones, y genera tanto `.env` como un `docker-compose.yml` ya ajustado a tus respuestas (no hace falta editarlo a mano).

Si no tienes Python instalado en el host, hazlo dentro de un contenedor temporal para no instalar nada fuera de Docker:

```bash
docker run --rm -it -v "$PWD":/app -w /app python:3.12-slim bash -c "pip install -q bcrypt && python setup.py"
```

(si ya tienes Python 3 con `bcrypt` disponible, basta con `python3 setup.py`)

Construye y arranca:

```bash
docker compose build
docker compose up -d
```

La app queda accesible en `http://<IP-del-host>:<puerto-que-elegiste>`.

Comandos útiles:

```bash
docker compose logs -f        # ver logs en vivo
docker compose restart        # reiniciar
docker compose down           # parar (los datos persisten en el volumen/carpeta elegidos)
docker compose up -d --build  # reconstruir tras actualizar el código (git pull)
```

Para cambiar cualquier cosa más adelante (el puerto, la contraseña, la versión de Java...), vuelve a ejecutar `python3 setup.py`: detecta la configuración ya existente y usa cada valor actual como valor por defecto, así que basta con pulsar Enter en todo salvo lo que quieras cambiar (la contraseña también se puede dejar en blanco para mantenerla). Después, reconstruye y reinicia:

```bash
docker compose up -d --build
```

Si solo quieres cambiar el usuario/contraseña, `python3 set_password.py` es la versión rápida (sin las demás preguntas).

`docker-compose.yml` no está en git (lo genera `setup.py`, y cada instalación lo personaliza — versionarlo haría que un `git pull` chocara en cuanto alguien cambiara, por ejemplo, el puerto). Si prefieres no ejecutar el asistente, `docker-compose.example.yml` es la plantilla de referencia: cópiala como `docker-compose.yml` y ajusta lo que necesites a mano.

### Opción B — `install.sh` dentro de un contenedor ya en marcha

Si ya tienes una shell dentro de un contenedor Docker (por ejemplo, uno que te da un panel de hosting) y prefieres no tocar el `Dockerfile`, puedes usar el mismo instalador que en Linux nativo:

```bash
bash install.sh
```

Elige `1) Contenedor` cuando te lo pregunte. Hace exactamente lo mismo que el modo nativo (entorno virtual, dependencias, `.env`...) pero sin crear un servicio `systemd` — al terminar, arranca la app directamente en primer plano dentro del contenedor.

## Actualizar

Hay tres formas, según cómo lo tengas instalado:

- **Desde el propio panel**: si activaste la auto-actualización, el panel comprueba cada cierto tiempo si hay una versión nueva en GitHub y lo avisa en **Sistema**. Se aplica con el botón **Actualizar ahora**, solo cuando no hay ningún servidor de Minecraft encendido ni otra operación en curso, y el panel se reinicia solo. Si la versión nueva sale mal (no carga, no arranca o no responde), el panel vuelve solo a la anterior y lo avisa ahí mismo; y si hay archivos de la app cambiados a mano, no actualiza para no pisarlos.
- **Linux nativo**: `bash install.sh` de nuevo (descarga lo nuevo y reinicia el servicio). Si prefieres hacer `git pull` a mano, **reinicia después el servicio** (`sudo systemctl restart minecraft-deployer`): hasta entonces sigue funcionando la versión anterior, que ya estaba cargada en memoria.
- **Docker**: `git pull` y `docker compose up -d --build`.

No hace falta vaciar la caché del navegador: cada archivo del panel lleva su propia versión en la URL y el navegador pide el nuevo en cuanto cambia.

## Después de instalar

- **Primer acceso**: con el usuario y la contraseña que configuraste durante la instalación (en cualquiera de las opciones).
- **CurseForge**: si no añadiste la clave de API durante la instalación, puedes añadirla luego desde **Configuración** dentro de la propia app (solo administrador), sin tocar nada por consola.
- **Tutorial dentro de la app**: pestaña **Ayuda**, con una explicación de cada sección del panel.
- **Sesión**: el inicio de sesión se guarda en una cookie del navegador (HttpOnly). Al cambiar la contraseña de una cuenta o borrarla, sus sesiones abiertas dejan de valer.
- **Cuándo se juega** (página **Jugadores**): racha de días seguidos con alguien jugando, resumen de los últimos 7 días y mapa de calor por día y hora. Las partidas se apuntan al entrar y salir los jugadores, en `SERVERS_PATH/.global/sessions.jsonl` (se guarda algo más de un año).
- **Roles**: cada cuenta (menos el administrador) es completa —todo menos cuentas, firewall y configuración— o **limitada**: lo ve todo, pero solo puede encender, parar y reiniciar el servidor y gestionar la lista blanca. Las descargas (salvo el paquete para jugadores) y la contraseña de RCON tampoco le llegan. El rol se cambia en **Usuarios** y vale al momento.
- **Contraseñas**: cada usuario cambia la suya con el botón del candado de la barra superior. El administrador puede poner una nueva a cualquier otro usuario desde **Usuarios** (por si la olvida).
- **Verificación en dos pasos** (opcional, por cuenta): desde el mismo botón del candado. Pide un código de 6 cifras de una app (Google Authenticator, Aegis, 2FAS, Bitwarden...) además de la contraseña, y da 8 códigos de recuperación de un solo uso. Si alguien pierde el móvil y los códigos, el administrador se la quita desde **Usuarios**; la del administrador se quita con `python3 set_password.py`. Se guarda en `SERVERS_PATH/.global/two_factor.json` (permisos `600`).
- **Actividad** (página **Usuarios**, solo administrador): quién ha hecho qué y cuándo, con su IP, y lo que el panel hace solo (copias automáticas, reinicios tras una caída, tareas). Se guarda en `SERVERS_PATH/.global/activity.jsonl` (las últimas 5000 acciones).
- **Intentos fallidos**: tras varios seguidos, la cuenta queda bloqueada unos minutos desde esa IP; el bloqueo se guarda en disco y sobrevive a un reinicio del panel.
- **Límites de subida**: por defecto, 8 GB por archivo y 32 GB descomprimido. Se cambian en **Configuración → Constantes → Subidas**.
- **Apariencia**: botón **Apariencia** de la barra superior. Ahí se elige el idioma, el tema (Amatista, Superficie, Nether o End), se activan los sonidos (apagados por defecto) y se ve la lista de logros. El idioma y los logros se guardan en tu cuenta (los ves igual entres desde donde entres); el tema y los sonidos, en cada navegador.

## Idiomas

El panel está en español de España y en inglés, entero: páginas, mensajes, errores del servidor, la Ayuda y los logros.

- **Cada cuenta tiene su idioma**: se elige en **Apariencia** y se aplica al entrar, desde cualquier dispositivo. Una cuenta que aún no ha elegido se queda con el de la pantalla de entrada.
- **Idioma por defecto** (`APP_LANGUAGE` en el `.env`): el de la pantalla de entrada y el de las cuentas que no han elegido. Lo pregunta el instalador y se cambia en **Configuración → Variables de entorno**.
- **Avisos de Telegram y Discord**: el administrador elige su idioma en **Configuración → Avisos** (`NOTIFY_LANGUAGE`), sea cual sea el de cada cuenta. Los avisos de reinicio que ven los jugadores en el chat del juego van en el idioma por defecto.

## Copias, automatización y avisos

- **Copias de seguridad**: en **Modpacks → Copias**, del mundo o completas (mods, configuración, scripts, listas de jugadores y mundo; sin `libraries/` ni logs, que se regeneran). Se pueden hacer con el servidor encendido (el panel pausa el guardado mientras copia), descargar y restaurar (con el servidor parado; antes se guarda una copia del estado actual). Se guardan en `SERVERS_PATH/.global/backups/<modpack>/`; si no caben en el disco no se empiezan, y el panel avisa cuando queda poco espacio. En **Automatización** se puede elegir un **destino secundario** (otro disco, un NAS o una carpeta de red montada; en Docker, montada como volumen) donde se duplica cada copia: si el disco principal falla, siguen saliendo en la lista y se restauran desde allí.
- **Automatización**: sección **Automatización** del panel. Reinicio automático si el servidor se cae (con límite de intentos), copias automáticas cada N horas guardando las últimas, y tareas programadas (reiniciar, parar, encender, comando o copia) con aviso previo a los jugadores o solo si no hay nadie conectado (esperando a que se vayan), y apagado del servidor cuando lleva un rato vacío. Los ajustes van en `SERVERS_PATH/.global/automation.json` y funcionan aunque nadie tenga el panel abierto.
- **Actualizar un modpack** a otra versión (botón **Actualizar modpack** al gestionarlo): copia completa antes, instalación limpia de la versión nueva en una carpeta aparte y fusión sin tocar el mundo, `server.properties` ni las listas de jugadores; se conservan los mods que añadiste tú. El origen se guarda en `<modpack>/.pack_source.json` al instalar desde Modrinth/CurseForge (los instalados antes se vinculan buscándolos una vez). Corre en el servidor aunque se cierre el navegador.
- **Actualizar mods**: en **Modpacks → Mods → Buscar actualizaciones**. Cada jar se reconoce por su hash en Modrinth (y en CurseForge con `CURSEFORGE_API_KEY`), se propone la última versión para la versión de Minecraft y el modloader del servidor (sin pasar de estable a beta) y se actualizan los que elijas, comprobando el hash de lo descargado. Los jars antiguos quedan en `<modpack>/.mods-replaced/` (los 3 últimos lotes) y se pueden volver a poner con «Deshacer».
- **Paquete para jugadores** (botón en la cabecera del modpack y en la de **Servidor** mientras está encendido): genera el modpack del servidor para instalarlo en el ordenador con los mismos mods y versiones, en formato CurseForge (`.zip`: app de CurseForge, Prism, ATLauncher) o Modrinth (`.mrpack`: Modrinth App, Prism). Los mods que la plataforma conoce solo se referencian (los baja el launcher); los demás van dentro. Si el servidor está vinculado a su modpack original, incluye también sus mods solo de cliente, resource packs, shaders y configuraciones; las del servidor no se meten nunca. En el `.mrpack` no van dentro los mods cuyo autor no permite repartirlos fuera de CurseForge (cada jugador los baja de allí). Es para tus jugadores, no para publicarlo. Las cuentas limitadas también pueden prepararlo y descargarlo.
- **Pregenerar el mundo** (botón **Pregenerar** en la cabecera del servidor): genera de antemano el terreno alrededor del spawn con el mod [Chunky](https://modrinth.com/plugin/chunky) (GPL-3.0), para que explorar no obligue al servidor a crearlo sobre la marcha. El panel solo lo instala si se lo pides (desde Modrinth, con el mod que necesite, p. ej. Fabric API, y comprobando el hash), lo deja fuera del paquete para jugadores y de las actualizaciones del modpack, y lo quita cuando quieras. Antes de empezar calcula los chunks y el espacio con lo que ocupan los de tu propio mundo, y no empieza si no queda margen en el disco. Opcionalmente solo con el servidor vacío (se pausa al entrar alguien); sigue sola tras un reinicio y avisa al terminar.
- **Clonar** un modpack, **estadísticas** de jugadores (de los archivos del mundo), **gráficas de rendimiento** de 24 h / 7 días (`.global/history/`) y vista de **chat** en la consola.

### Avisos por Telegram y Discord

Opcionales. El panel puede escribirte cuando el servidor está listo, se para, se cae, entra o sale alguien, falla una copia, termina una instalación o se ejecuta una tarea programada, y los lunes te manda el resumen de la semana: quién ha jugado, cuántas horas, caras nuevas y la racha de días seguidos (eliges cuáles).

Cada instalación usa **su propio bot**, así que los avisos solo le llegan a quien lo configura:

1. En Telegram, abre **@BotFather**, escríbele `/newbot` y elige un nombre. Te dará un token.
2. Abre tu bot nuevo y escríbele cualquier cosa (por ejemplo `/start`).
3. Pega el token en **Configuración → Avisos** y pulsa **Detectar**: el panel encuentra tu chat solo. Guarda y usa **Enviar prueba**.

El instalador (`install.sh` / `setup.py`) también lo pregunta, y se puede dejar en blanco. Para Discord basta la URL de un webhook del canal (ajustes del canal → Integraciones → Webhooks). El idioma de los mensajes se elige en esa misma pestaña. Todo se guarda en el `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `NOTIFY_EVENTS`, `NOTIFY_LANGUAGE`), pero se aplica al momento, sin reiniciar el panel.

## Versiones

### 3.0.0 (noviembre de 2026)

El panel, en inglés:

- **Todo traducido**: páginas, diálogos, mensajes, fechas y números, errores y progreso del servidor, la Ayuda, los logros y las frases de la pantalla de entrada. El español sigue siendo el original.
- **Cada cuenta con su idioma**, guardado en la cuenta y no en el navegador.
- **Idioma de los avisos** de Telegram y Discord, a elección del administrador.
- **Instaladores bilingües**: `install.sh` y `setup.py` preguntan primero el idioma y lo dejan como idioma por defecto del panel.
- Los números con decimales usan la coma en español (1,5 GB).

Entre la 2.0 y la 3.0 llegaron también las copias de seguridad, la automatización (reinicio tras caídas, copias y tareas programadas), los avisos por Telegram y Discord, las estadísticas de jugadores, las gráficas de rendimiento y el chat de la consola. El historial completo está en el propio panel (**Sistema → Actualizaciones de la app**).

### 2.0.0 (noviembre de 2026)

Revisión de seguridad y retoques:

- **RAM validada en todos los caminos**: al crear un servidor o instalar un modpack, la RAM se escribía sin comprobar en `run.sh`, y con un valor manipulado se podían colar comandos. Ahora solo se acepta un número con `M` o `G`.
- **`.env` y `users.json` privados**: el panel los deja con permisos `600` al arrancar (y el instalador al crearlos). Llevan el secreto de las sesiones y los hashes de las contraseñas.
- **Límites de subida** configurables, que también frenan los «zip bomb»: se mira cuánto ocupará un archivo descomprimido antes de extraerlo, y si cabe en el disco.
- **Login más difícil de forzar**: bloqueo también por IP (con cualquier usuario) y la misma espera tanto si el usuario existe como si no, para que no se pueda averiguar qué usuarios hay.
- **Cambiar la contraseña** propia desde el panel, y restablecer la de otros usuarios (admin). Cambiar la del admin desde Configuración ya no espera al reinicio.
- **Actualizar ahora** solo para administradores.
- **Content-Security-Policy** estricta: el navegador solo ejecuta los scripts del propio panel.
- **Escrituras atómicas** de `server.properties`, configs, scripts de KubeJS, archivos de mundo y `users.json`: si algo falla a mitad, el archivo anterior sigue intacto.
- Nombres de descarga con comillas o tildes bien codificados; limpieza de importaciones fallidas fuera del bucle principal; barra superior que ya no se corta en pantallas medianas.

### 1.x

Todo lo anterior, sin numerar.

## Desarrollo y pruebas

Las pruebas usan solo la biblioteca estándar y no tocan tus servidores (apuntan `SERVERS_PATH` a una carpeta temporal). Desde la raíz del repositorio, con las dependencias de `requirements.txt` instaladas:

```bash
python -m unittest discover -s tests -t .
```

Cubren la validación de rutas y nombres, la extracción segura de archivos, las sesiones, el parseo del firewall, la RAM de la JVM, los UUID de los jugadores, que la página se monte completa y que los scripts de `static/js` no se pisen nombres globales entre sí.

### Estructura del back

- `main.py` crea la app, el middleware de sesión y registra los routers; antes de arrancar, `services/startup_cleanup.py` libera puertos y para servidores huérfanos de una ejecución anterior.
- `routes/` tiene un archivo por grupo de rutas de la API (`server.py`, `mods.py`, `backups.py`, `automation.py`...) y solo valida y traduce peticiones; la lógica está en `services/`.
- En `services/`, lo de los modpacks está repartido por tema: `modpack.py` (versión, `server.properties`, mundos, logs), `mod_metadata.py` (leer un `.jar` y comparar versiones), `mod_checks.py` (mods de solo cliente, duplicados, qué hacer con cada `.jar` subido), `pending_mods.py` (mods que instalar a mano) y `crash_analysis.py`. El servidor en marcha va en `process.py` (proceso y consola) y `server_control.py` (arrancar, parar, reinicio tras caída); la automatización en `automation.py` (ajustes) y `scheduler.py` (el hilo que ejecuta tareas, copias y muestras del historial).

### Estructura del front

- `static/index.html` es solo el esqueleto: estilos, scripts y una línea `<!-- include: ... -->` por cada trozo.
- `static/partials/` contiene un HTML por página (`pages/`), por pestaña de Modpacks (`manage/`), por grupo de modales (`modals/`) y los bloques compartidos (por ejemplo `ram-fields.html`, que acepta parámetros). `services/frontend.py` los une al servir `/`, así que el navegador sigue recibiendo una sola página.
- `static/js/` tiene un archivo por sección o pestaña (`server_props.js`, `jvm_ram.js`, `file_editor.js`, `kubejs.js`...), todos en el ámbito global y cargados en el orden de `index.html`.
- Los colores viven como tokens en `static/css/base.css`; `themes.css` define los temas (Amatista, Superficie, Nether y End) cambiando esos tokens y el fondo de página de cada uno (`--bg-pattern`, texturas pixeladas en SVG, y `--bg-extra`, un degradado encima), y `scene.css` la escena pixelada de la cabecera de Servidor y del login, las barras segmentadas y las celebraciones. Las barras de scroll también salen de los tokens (al final de `base.css`), y `search.css` viste los dos buscadores de Modrinth/CurseForge: tarjetas con el icono en una casilla de inventario, el halo del color del icono y el brillo de encantamiento en el modpack elegido. `static/js/appearance.js` guarda el tema en el navegador, `sounds.js` los sonidos (apagados por defecto), `achievements.js` los logros y `pixel_art.js` dibuja los logos, las cabezas de repuesto y los estados vacíos. Un logro nuevo es una entrada en `ACHIEVEMENTS` (en `achievements.js`) (con `secret: true` si debe salir como «???» hasta conseguirlo), su icono pixelado de 10x10 en `achievement_icons.js` (un test comprueba que no falte) y una llamada a `unlockAchievement('id')` donde ocurra. Los sonidos están en `SOUNDS`, y lo que suena al pulsar algo depende de lo que hace (`soundForControl`): cambiar de sección, iniciar, borrar, cerrar, encender o apagar, elegir tema... Un botón puede elegir el suyo con `data-sound`.
- **Traducciones**: todo el texto se escribe en español y `static/i18n/en.json` es un mapa de frases enteras («frase en español» → «English phrase»), con huecos `{nombre}` para los datos. El HTML se traduce al servirlo (`services/i18n.py`), el JavaScript usa `t('Frase', {dato})` (`static/js/i18n.js`) y los mensajes del backend se traducen en `services/i18n_middleware.py` (campos `detail`, `message`, `reason`… de las respuestas JSON y de los eventos SSE; las frases con datos funcionan como plantillas). Los tests fallan si una frase nueva del HTML, un `t('…')`, un logro o un mensaje del backend se queda sin traducción.
- Al servir `/`, cada `/static/...` recibe `?v=` con la fecha de modificación de ese archivo, y esas respuestas se marcan como inmutables: el navegador las guarda indefinidamente y solo descarga las que cambian.
- Las cabezas de los jugadores se piden a mc-heads.net a través de `/api/players/head/{nombre}` y se guardan unos días en `.global/heads/`. El logo de un modpack es su `server-icon.png` o, si se instaló desde Modrinth o CurseForge, el de la tienda (`.mcdeployer/icon.*` dentro de su carpeta). Sin internet, el panel dibuja una cara o un bloque con los colores del nombre.

## Aviso legal

- **No es un producto oficial de Minecraft.** No está aprobado por Mojang ni por Microsoft, ni asociado con ellos. «Minecraft» es una marca de Mojang Synergies AB.
- **La EULA de Minecraft la aceptas tú.** El panel no la acepta nunca por su cuenta: antes de arrancar por primera vez cada servidor, la muestra con su enlace ([aka.ms/MinecraftEULA](https://aka.ms/MinecraftEULA)) y pide aceptarla. Al hacerlo, la aceptas como responsable de ese servidor; queda anotado en su `eula.txt` y en **Actividad**.
- **Mods y modpacks**: el panel los descarga desde Modrinth y CurseForge en cada instalación, y cada uno tiene su licencia y su autor. Este repositorio no incluye ninguno. Si el autor de un mod no permite que lo descarguen aplicaciones de terceros, el panel lo respeta y te avisa para que lo instales a mano. El **paquete para jugadores** es para pasárselo a tus jugadores, no para publicarlo.
- **APIs**: cada instalación usa su propia clave de la API de CurseForge, y su uso está sujeto a sus condiciones y a las de Modrinth.
- **Sin telemetría**: el panel no envía nada a quien lo desarrolla. Solo se conecta a las APIs de mods y modloaders, a Mojang, a GitHub (para buscar actualizaciones), a mc-heads.net (cabezas de los jugadores) y a Telegram/Discord si configuras los avisos.
- **Contenido de terceros incluido**: iconos [Lucide](https://lucide.dev) (licencia ISC, `static/LICENSE-lucide.txt`) y fuentes IBM Plex y Pixelify Sans (SIL Open Font License 1.1, `static/fonts/`). Los dibujos pixelados y los sonidos son propios (generados por código).

## Licencia

El código de Server Deployer for Minecraft es software libre con licencia [MIT](LICENSE): puedes usarlo, modificarlo y repartirlo, también en otros proyectos, siempre que conserves el aviso de copyright y la licencia. Se ofrece tal cual, sin garantías. Los mods, modpacks, iconos y fuentes de terceros mantienen sus propias licencias (ver **Aviso legal**).
