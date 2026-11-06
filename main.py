"""
main.py - Punto de entrada de Minecraft Server Deployer.

Crea la app FastAPI, registra todos los routers, y en __main__
ejecuta las tareas de limpieza antes de arrancar uvicorn.
"""
import mimetypes
import os
import re
import time
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent / ".env"
if not _ENV_PATH.exists():
    print(f"⚠️  AVISO: No se encontró .env en {_ENV_PATH}")
    print("   Ejecuta: python3 set_password.py")
load_dotenv(_ENV_PATH, override=True)

from routes.system import router as system_router
from routes.modpacks import router as modpacks_router, upload_router
from routes.mod_files import router as mod_files_router
from routes.mods import router as mods_router
from routes.worlds import router as worlds_router
from routes.logs import router as logs_router
from routes.firewall import router as firewall_router
from routes.modloader import router as modloader_router
from routes.create_server import router as create_server_router
from routes.modpack_install import router as modpack_install_router
from routes.mod_search import router as mod_search_router
from routes.players import router as players_router
from routes.server import router as server_router
from routes.auth import router as auth_router, verify_token, token_from_request
from routes.users import router as users_router
from routes.config_admin import router as config_admin_router
from services.lifecycle import shutdown_event
from services.process import notify_app_shutdown
from services import auto_update

# ── Middleware de autenticación ────────────────────────────────────────────────

PUBLIC_PATHS = {"/", "/api/auth/login", "/api/auth/logout", "/api/auth/verify"}

# Cabeceras que el navegador aplica a todo: el panel no se puede meter en un
# <iframe> de otra web (clickjacking), no adivina tipos de archivo y no manda
# la URL del panel a las webs de mods que se abren desde él.
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await self._authorize(request, call_next)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    async def _authorize(self, request: Request, call_next):
        path = request.url.path

        # Dejar pasar rutas públicas y archivos estáticos (CSS/JS/iconos)
        if path in PUBLIC_PATHS or path.startswith("/static/") or path.startswith("/icon/"):
            return await call_next(request)

        # La sesión llega en la cookie (también en EventSource y descargas,
        # que el navegador manda solas) o en una cabecera Authorization.
        token = token_from_request(request)
        user_info = verify_token(token) if token else None
        if not user_info:
            return JSONResponse({"detail": "No autorizado"}, status_code=401)

        request.state.user = user_info["sub"]
        request.state.role = user_info["role"]

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    auto_update.start()
    yield
    # Uvicorn llega aquí DESPUÉS de esperar a que las conexiones se cierren
    # solas (ver timeout_graceful_shutdown más abajo): para entonces los
    # streams SSE de consola/sysmon ya se cortaron por esa espera (o fueron
    # cancelados a la fuerza al agotarse el timeout). Esto solo limpia el
    # estado en memoria antes de que el proceso termine.
    shutdown_event.set()
    notify_app_shutdown()


app = FastAPI(title="Minecraft Server Deployer", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(AuthMiddleware)
# Las fuentes de static/fonts/: sin esto algunos sistemas las sirven como
# application/octet-stream.
mimetypes.add_type("font/woff2", ".woff2")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/icon", StaticFiles(directory=Path(__file__).parent / "icon"), name="icon")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(config_admin_router)
app.include_router(system_router)
app.include_router(modpacks_router)
app.include_router(mod_files_router)
app.include_router(mods_router)
app.include_router(worlds_router)
app.include_router(logs_router)
app.include_router(modloader_router)
app.include_router(create_server_router)
app.include_router(modpack_install_router)
app.include_router(mod_search_router)
app.include_router(upload_router)
app.include_router(firewall_router)
app.include_router(players_router)
app.include_router(server_router)


# ── Limpieza al arrancar ───────────────────────────────────────────────────────

_APP_DIR = Path(__file__).resolve().parent


def _proc_cwd(pid) -> Path | None:
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    except (OSError, ValueError):
        return None


def _proc_cmdline(pid) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _is_under(path: Path | None, base: Path) -> bool:
    if path is None:
        return False
    try:
        path.relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _is_previous_panel(pid) -> bool:
    """Otra instancia de este mismo panel (python .../main.py desde esta carpeta)."""
    cmdline = _proc_cmdline(pid)
    return "main.py" in cmdline and (_proc_cwd(pid) == _APP_DIR or str(_APP_DIR) in cmdline)


def _is_our_minecraft(pid) -> bool:
    """Un proceso lanzado dentro de la carpeta de servidores del panel."""
    from config import DEFAULT_SERVERS_PATH
    return _is_under(_proc_cwd(pid), DEFAULT_SERVERS_PATH)


def _pids_on_port(port: int) -> list:
    pids = []
    try:
        result = subprocess.run(["ss", "-tlnp", "sport", "=", f":{port}"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if str(port) in line:
                pids.extend(int(p) for p in re.findall(r'pid=(\d+)', line))
    except (OSError, ValueError):
        pass
    if not pids:
        try:
            result = subprocess.run(["fuser", f"{port}/tcp"], capture_output=True, text=True)
            pids.extend(int(p) for p in result.stdout.split() if p.strip().isdigit())
        except OSError:
            pass
    return sorted(set(pid for pid in pids if pid != os.getpid()))


def kill_port(port: int, is_ours) -> tuple[list, list]:
    """
    Libera el puerto TCP matando los procesos que lo ocupan, pero SOLO los que
    is_ours(pid) reconoce como propios. Antes se mataba cualquier cosa que
    estuviera en el puerto (otra aplicación, o un servidor de Minecraft que no
    había lanzado el panel). Devuelve (matados, ajenos que se dejaron vivos).
    """
    killed, foreign = [], []
    for pid in _pids_on_port(port):
        if not is_ours(pid):
            foreign.append(pid)
            continue
        try:
            os.kill(pid, 9)
            killed.append(pid)
        except OSError:
            pass
    return killed, foreign


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except (ValueError, TypeError):
        return False


def _graceful_stop_orphan(pid: str) -> bool:
    """
    Intenta un apagado limpio (save-all + stop por RCON) de un proceso Java
    huérfano antes de recurrir a SIGKILL. Al arrancar el panel de cero no hay
    ningún Popen vivo con stdin propio para este PID (pertenecía al proceso
    anterior), así que la única vía de apagado ordenado disponible es RCON —
    para eso hay que averiguar de qué modpack es este proceso resolviendo su
    directorio de trabajo real (/proc/<pid>/cwd, Linux) y leyendo su propio
    server.properties. Devuelve True si se confirma que paró solo a tiempo.
    """
    from config import DEFAULT_SERVERS_PATH
    from app_constants import GRACEFUL_STOP_TIMEOUT_SECONDS
    from services.modpack import parse_server_properties
    from services.rcon import RconConnection, RconError

    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return False

    server_dir = Path(cwd)
    try:
        server_dir.resolve().relative_to(DEFAULT_SERVERS_PATH.resolve())
    except ValueError:
        return False  # no es una carpeta de modpack conocida, no arriesgarse

    props = parse_server_properties(server_dir.name)
    if props.get("enable-rcon") != "true":
        return False

    port_str = props.get("rcon.port", "").strip()
    password = props.get("rcon.password", "").strip()
    if not port_str.isdigit() or not password:
        return False

    host = props.get("server-ip", "").strip() or "127.0.0.1"
    conn = RconConnection(host, int(port_str), password)
    try:
        conn.command("save-all")
        conn.command("stop")
    except (RconError, OSError):
        return False
    finally:
        conn.close()

    deadline = time.time() + GRACEFUL_STOP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.5)
    return False


def kill_orphan_servers() -> list:
    """
    Limpia procesos Java residuales de ejecuciones anteriores del servidor
    Minecraft. Solo toca los que corren DENTRO de la carpeta de servidores del
    panel: antes bastaba con que la línea de comandos mencionara "minecraft"
    o "forge", y se llevaba por delante cualquier otro servidor del equipo.
    Antes de matarlos con SIGKILL, intenta un apagado limpio por RCON
    (save-all + stop) para no arriesgar el mundo en cada reinicio del panel.
    """
    killed = []
    try:
        result = subprocess.run(["pgrep", "-x", "java"], capture_output=True, text=True)
    except OSError:
        return killed
    for pid in result.stdout.split():
        if not pid.isdigit() or not _is_our_minecraft(pid):
            continue
        stopped_gracefully = _graceful_stop_orphan(pid)
        if not stopped_gracefully and _pid_alive(pid):
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass
        tag = "apagado limpio" if stopped_gracefully else "SIGKILL"
        killed.append(f"{pid} ({_proc_cmdline(pid)[:60]}) [{tag}]")
    return killed


def clean_orphan_locks() -> list:
    """Elimina archivos session.lock abandonados por servidores que crashearon."""
    from config import DEFAULT_SERVERS_PATH
    cleaned = []
    try:
        if not DEFAULT_SERVERS_PATH.exists():
            return cleaned
        for modpack_dir in DEFAULT_SERVERS_PATH.iterdir():
            if not modpack_dir.is_dir() or modpack_dir.name.startswith("."):
                continue
            for lock in modpack_dir.rglob("session.lock"):
                try:
                    lock.unlink()
                    cleaned.append(str(lock.relative_to(DEFAULT_SERVERS_PATH)))
                except Exception:
                    pass
    except Exception:
        pass
    return cleaned


if __name__ == "__main__":
    import uvicorn
    from config import DEFAULT_SERVERS_PATH, WEB_PORT

    print("Minecraft Server Deployer arrancando...")

    print(f"Liberando puerto {WEB_PORT} si lo ocupa una instancia anterior del panel...")
    web_killed, web_foreign = kill_port(WEB_PORT, _is_previous_panel)
    if web_killed:
        print(f"  Eliminados {len(web_killed)} proceso(s) en el puerto {WEB_PORT}: {web_killed}")
        time.sleep(1)
    if web_foreign:
        print(f"  ⚠️  El puerto {WEB_PORT} lo usa otro programa (PID {web_foreign}); no se toca. "
              "Cambia WEB_PORT en .env si el panel no puede arrancar.")
    if not web_killed and not web_foreign:
        print(f"  Puerto {WEB_PORT} libre.")

    # Antes del kill duro por puerto: intenta un apagado limpio (save-all +
    # stop por RCON) de cualquier server huérfano, para no arriesgar el mundo
    # en cada simple reinicio del panel. El kill por puerto de abajo queda
    # como red de seguridad final para lo que no haya podido pararse solo.
    print("Buscando procesos huérfanos de servidores anteriores...")
    killed = kill_orphan_servers()
    if killed:
        print(f"  Procesados {len(killed)} proceso(s) huérfano(s):")
        for k in killed:
            print(f"    - {k}")
    else:
        print("  No se encontraron procesos huérfanos.")

    print("Liberando puerto 25565 si lo ocupa un servidor del panel...")
    port_killed, port_foreign = kill_port(25565, _is_our_minecraft)
    if port_killed:
        print(f"  Eliminados {len(port_killed)} proceso(s) en el puerto 25565: {port_killed}")
        time.sleep(1)
    if port_foreign:
        print(f"  ⚠️  El puerto 25565 lo usa un programa ajeno al panel (PID {port_foreign}); no se toca.")
    if not port_killed and not port_foreign:
        print("  Puerto 25565 libre.")

    print("Limpiando session.lock abandonados...")
    locks = clean_orphan_locks()
    if locks:
        print(f"  Eliminados {len(locks)} session.lock abandonado(s):")
        for l in locks:
            print(f"    - {l}")
    else:
        print("  No se encontraron session.lock abandonados.")

    print(f"Carpeta por defecto: {DEFAULT_SERVERS_PATH}")
    print(f"Accede desde tu red local en: http://<IP-DE-ESTE-EQUIPO>:{WEB_PORT}")

    # Los streams SSE de consola y del panel de sistema son bucles que nunca
    # terminan por sí solos: sin este límite bajo, `systemctl restart` (SIGTERM)
    # se queda esperando a que esas conexiones se cierren solas ANTES de que
    # el proceso llegue siquiera a enterarse del apagado (uvicorn espera esto
    # primero y recién después dispara el evento "shutdown" de la app — para
    # entonces ya es tarde para acortar la espera desde aquí). Pasado este
    # tiempo, uvicorn cancela las conexiones que sigan abiertas a la fuerza.
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, reload=False, timeout_graceful_shutdown=3)
