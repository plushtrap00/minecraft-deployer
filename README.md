# Minecraft Server Deployer

Panel web (FastAPI + JavaScript sin frameworks) para crear y gestionar servidores de Minecraft modded: instalar modpacks completos desde Modrinth/CurseForge, buscar y actualizar mods, gestionar jugadores (ops/whitelist/bans), mundos, consola en vivo, métricas, firewall y copias de seguridad. Pensado para autoalojarse en tu propio servidor o VPS Linux.

Y como gestionar un servidor de Minecraft no tiene por qué ser aburrido: cuatro temas con su propio fondo pixelado, una escena que pasa de noche a día cuando el servidor arranca, cabezas de los jugadores, celebraciones y más de veinte logros por desbloquear (algunos secretos).

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

- **Modo de instalación** → elige `2) Nativo`.
- Carpeta donde instalar la app.
- Usuario y contraseña para entrar al panel.
- Puerto de la interfaz web (por defecto `8000`) y puerto de Minecraft (`25565`).
- Dominio público (opcional — para que los jugadores se conecten con un nombre en vez de una IP).
- Clave de API de CurseForge (opcional — **Modrinth funciona sin ella**; se consigue gratis en [console.curseforge.com](https://console.curseforge.com/#/api-keys)).
- Auto-actualización (opcional — la app comprueba sola si hay una versión nueva en GitHub).
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

Genera la configuración con el asistente interactivo `setup.py`: te pregunta usuario y contraseña de administrador, puertos, versión de Java, dónde guardar los modpacks (volumen Docker o una carpeta del host) y demás opciones, y genera tanto `.env` como un `docker-compose.yml` ya ajustado a tus respuestas (no hace falta editarlo a mano).

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

- **Desde el propio panel**: si activaste la auto-actualización, el panel comprueba cada cierto tiempo si hay una versión nueva en GitHub y lo avisa en **Sistema**. Se aplica con el botón **Actualizar ahora**, solo cuando no hay ningún servidor de Minecraft encendido ni otra operación en curso, y el panel se reinicia solo.
- **Linux nativo**: `bash install.sh` de nuevo (descarga lo nuevo y reinicia el servicio). Si prefieres hacer `git pull` a mano, **reinicia después el servicio** (`sudo systemctl restart minecraft-deployer`): hasta entonces sigue funcionando la versión anterior, que ya estaba cargada en memoria.
- **Docker**: `git pull` y `docker compose up -d --build`.

No hace falta vaciar la caché del navegador: cada archivo del panel lleva su propia versión en la URL y el navegador pide el nuevo en cuanto cambia.

## Después de instalar

- **Primer acceso**: con el usuario y la contraseña que configuraste durante la instalación (en cualquiera de las opciones).
- **CurseForge**: si no añadiste la clave de API durante la instalación, puedes añadirla luego desde **Configuración** dentro de la propia app (solo administrador), sin tocar nada por consola.
- **Tutorial dentro de la app**: pestaña **Ayuda**, con una explicación de cada sección del panel.
- **Sesión**: el inicio de sesión se guarda en una cookie del navegador (HttpOnly). Al cambiar la contraseña de una cuenta o borrarla, sus sesiones abiertas dejan de valer.
- **Apariencia**: botón **Apariencia** de la barra superior. Ahí se elige el tema (Amatista, Superficie, Nether o End), se activan los sonidos (apagados por defecto) y se ve la lista de logros. Todo esto se guarda en cada navegador, no en el servidor: si entras desde otro equipo, empiezas de cero.

## Desarrollo y pruebas

Las pruebas usan solo la biblioteca estándar y no tocan tus servidores (apuntan `SERVERS_PATH` a una carpeta temporal). Desde la raíz del repositorio, con las dependencias de `requirements.txt` instaladas:

```bash
python -m unittest discover -s tests -t .
```

Cubren la validación de rutas y nombres, la extracción segura de archivos, las sesiones, el parseo del firewall, la RAM de la JVM, los UUID de los jugadores, que la página se monte completa y que los scripts de `static/js` no se pisen nombres globales entre sí.

### Estructura del front

- `static/index.html` es solo el esqueleto: estilos, scripts y una línea `<!-- include: ... -->` por cada trozo.
- `static/partials/` contiene un HTML por página (`pages/`), por pestaña de Modpacks (`manage/`), por grupo de modales (`modals/`) y los bloques compartidos (por ejemplo `ram-fields.html`, que acepta parámetros). `services/frontend.py` los une al servir `/`, así que el navegador sigue recibiendo una sola página.
- `static/js/` tiene un archivo por sección o pestaña (`server_props.js`, `jvm_ram.js`, `file_editor.js`, `kubejs.js`...), todos en el ámbito global y cargados en el orden de `index.html`.
- Los colores viven como tokens en `static/css/base.css`; `themes.css` define los temas (Amatista, Superficie, Nether y End) cambiando esos tokens y el fondo de página de cada uno (`--bg-pattern`, texturas pixeladas en SVG, y `--bg-extra`, un degradado encima), y `scene.css` la escena pixelada de la cabecera de Servidor y del login, las barras segmentadas y las celebraciones. `static/js/appearance.js` guarda el tema, los sonidos (apagados por defecto) y los logros en el navegador, y dibuja los logos y cabezas de repuesto. Un logro nuevo es una entrada en `ACHIEVEMENTS` (con `secret: true` si debe salir como «???» hasta conseguirlo), su icono pixelado de 10x10 en `achievement_icons.js` (un test comprueba que no falte) y una llamada a `unlockAchievement('id')` donde ocurra. Los sonidos están en `SOUNDS`, y lo que suena al pulsar algo depende de lo que hace (`soundForControl`): cambiar de sección, iniciar, borrar, cerrar, encender o apagar, elegir tema... Un botón puede elegir el suyo con `data-sound`.
- Al servir `/`, cada `/static/...` recibe `?v=` con la fecha de modificación de ese archivo, y esas respuestas se marcan como inmutables: el navegador las guarda indefinidamente y solo descarga las que cambian.
- Las cabezas de los jugadores se piden a mc-heads.net a través de `/api/players/head/{nombre}` y se guardan unos días en `.global/heads/`. El logo de un modpack es su `server-icon.png` o, si se instaló desde Modrinth o CurseForge, el de la tienda (`.mcdeployer/icon.*` dentro de su carpeta). Sin internet, el panel dibuja una cara o un bloque con los colores del nombre.
