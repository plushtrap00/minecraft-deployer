# Minecraft Server Deployer

Panel web (FastAPI + JavaScript sin frameworks) para crear y gestionar servidores de Minecraft modded: instalar modpacks completos desde Modrinth/CurseForge, buscar y actualizar mods, gestionar jugadores (ops/whitelist/bans), mundos, consola en vivo, métricas, firewall y copias de seguridad. Pensado para autoalojarse en tu propio servidor o VPS Linux.

## Requisitos

- Linux (nativo, o Docker sobre cualquier sistema operativo).
- Acceso `sudo` para la instalación nativa (crea un servicio `systemd`).
- Docker + Docker Compose para la instalación en contenedor.

Python y Java se instalan solos si faltan (en instalación nativa y en modo "Contenedor" de `install.sh`); en la imagen Docker ya vienen incluidos.

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

Para cambiar solo el usuario/contraseña más adelante sin rehacer toda la configuración, usa `python3 set_password.py` y reinicia el contenedor.

`docker-compose.yml` no está en git (lo genera `setup.py`, y cada instalación lo personaliza — versionarlo haría que un `git pull` chocara en cuanto alguien cambiara, por ejemplo, el puerto). Puedes editarlo a mano cuando quieras (p. ej. para cambiar el puerto expuesto) sin miedo a conflictos en la próxima actualización. Si prefieres no ejecutar el asistente, `docker-compose.example.yml` es la plantilla de referencia: cópiala como `docker-compose.yml` y ajusta lo que necesites.

### Opción B — `install.sh` dentro de un contenedor ya en marcha

Si ya tienes una shell dentro de un contenedor Docker (por ejemplo, uno que te da un panel de hosting) y prefieres no tocar el `Dockerfile`, puedes usar el mismo instalador que en Linux nativo:

```bash
bash install.sh
```

Elige `1) Contenedor` cuando te lo pregunte. Hace exactamente lo mismo que el modo nativo (entorno virtual, dependencias, `.env`...) pero sin crear un servicio `systemd` — al terminar, arranca la app directamente en primer plano dentro del contenedor.

## Después de instalar

- **Primer acceso**: con el usuario y la contraseña que configuraste durante la instalación (en cualquiera de las opciones).
- **CurseForge**: si no añadiste la clave de API durante la instalación, puedes añadirla luego desde **⚙️ Configuración** dentro de la propia app (solo administrador), sin tocar nada por consola.
- **Tutorial dentro de la app**: pestaña **❓ Ayuda**, con una explicación de cada sección del panel.
