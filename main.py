"""
main.py - Punto de entrada de Minecraft Server Deployer.

Crea la app FastAPI, registra todos los routers, y en __main__
ejecuta las tareas de limpieza antes de arrancar uvicorn.
"""
import os
import re
import time
import subprocess
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
from routes.modpacks import router as modpacks_router, upload_router, firewall_router
from routes.modloader import router as modloader_router
from routes.create_server import router as create_server_router
from routes.modpack_install import router as modpack_install_router
from routes.mod_search import router as mod_search_router
from routes.players import router as players_router
from routes.server import router as server_router
from routes.auth import router as auth_router, verify_token
from routes.users import router as users_router
from services.lifecycle import shutdown_event
from services.process import notify_app_shutdown
from services import auto_update

# ── Middleware de autenticación ────────────────────────────────────────────────

PUBLIC_PATHS = {"/", "/api/auth/login"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Dejar pasar rutas públicas y archivos estáticos (CSS/JS/iconos)
        if path in PUBLIC_PATHS or path.startswith("/static/") or path.startswith("/icon/"):
            return await call_next(request)

        # Dejar pasar OPTIONS (preflight CORS)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Verificar token — acepta header Authorization o query param ?token= (para SSE)
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if not token:
            token = request.query_params.get("token", "")

        user_info = verify_token(token) if token else None
        if not user_info:
            return JSONResponse({"detail": "No autorizado"}, status_code=401)

        request.state.user = user_info["sub"]
        request.state.role = user_info["role"]

        return await call_next(request)


app = FastAPI(title="Minecraft Server Deployer")
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/icon", StaticFiles(directory=Path(__file__).parent / "icon"), name="icon")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(system_router)
app.include_router(modpacks_router)
app.include_router(modloader_router)
app.include_router(create_server_router)
app.include_router(modpack_install_router)
app.include_router(mod_search_router)
app.include_router(upload_router)
app.include_router(firewall_router)
app.include_router(players_router)
app.include_router(server_router)


@app.on_event("startup")
async def _on_startup():
    auto_update.start()


@app.on_event("shutdown")
async def _on_shutdown():
    """
    Corta los streams SSE (consola, panel de sistema) en cuanto systemd manda
    la señal de parada, para que `systemctl restart` no tenga que esperar a que
    salte el timeout y fuerce un SIGKILL.
    """
    shutdown_event.set()
    notify_app_shutdown()


# ── Limpieza al arrancar ───────────────────────────────────────────────────────

def kill_port(port: int) -> list:
    """Mata cualquier proceso que ocupe el puerto TCP indicado."""
    killed = []
    try:
        result = subprocess.run(
            ["ss", "-tlnp", "sport", "=", f":{port}"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if str(port) in line and "pid=" in line:
                for pid_str in re.findall(r'pid=(\d+)', line):
                    try:
                        os.kill(int(pid_str), 9)
                        killed.append(int(pid_str))
                    except Exception:
                        pass
    except Exception:
        pass
    # Fallback con fuser
    if not killed:
        try:
            result = subprocess.run(
                ["fuser", f"{port}/tcp"],
                capture_output=True, text=True,
            )
            for pid_str in result.stdout.split():
                try:
                    os.kill(int(pid_str.strip()), 9)
                    killed.append(int(pid_str.strip()))
                except Exception:
                    pass
        except Exception:
            pass
    return killed


def kill_port_25565() -> list:
    return kill_port(25565)


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
    from config import DEFAULT_SERVERS_PATH, GRACEFUL_STOP_TIMEOUT_SECONDS
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
    Minecraft. Antes de matarlos con SIGKILL, intenta un apagado limpio por
    RCON (save-all + stop) — sin esto, cada simple reinicio del panel
    (systemctl restart, redeploy, etc.) mataba en frío cualquier partida en
    curso, con riesgo real de corromper el mundo.
    """
    killed = []
    mc_keywords = ["forge", "neoforge", "fabric", "quilt", "minecraft", "server.jar", "startserver", "ServerStarterJar"]
    try:
        result = subprocess.run(["pgrep", "-f", "-l", "java"], capture_output=True, text=True)
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, cmdline = parts[0], parts[1]
            if any(k.lower() in cmdline.lower() for k in mc_keywords):
                stopped_gracefully = _graceful_stop_orphan(pid)
                if not stopped_gracefully and _pid_alive(pid):
                    try:
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                    except Exception:
                        pass
                tag = "apagado limpio" if stopped_gracefully else "SIGKILL"
                killed.append(f"{pid} ({cmdline[:60]}) [{tag}]")
    except FileNotFoundError:
        try:
            result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
            for line in result.stdout.split("\n"):
                if "java" not in line.lower():
                    continue
                if any(k.lower() in line.lower() for k in mc_keywords):
                    pid = line.split()[1]
                    stopped_gracefully = _graceful_stop_orphan(pid)
                    if not stopped_gracefully and _pid_alive(pid):
                        try:
                            subprocess.run(["kill", "-9", pid], capture_output=True)
                        except Exception:
                            pass
                    tag = "apagado limpio" if stopped_gracefully else "SIGKILL"
                    killed.append(f"{pid} [{tag}]")
        except Exception:
            pass
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

    print(f"Liberando puerto {WEB_PORT} si está ocupado...")
    web_killed = kill_port(WEB_PORT)
    if web_killed:
        print(f"  Eliminados {len(web_killed)} proceso(s) en el puerto {WEB_PORT}: {web_killed}")
        time.sleep(1)
    else:
        print(f"  Puerto {WEB_PORT} libre.")

    # Antes del kill duro por puerto: intenta un apagado limpio (save-all +
    # stop por RCON) de cualquier server huérfano, para no arriesgar el mundo
    # en cada simple reinicio del panel. kill_port_25565 de abajo queda como
    # red de seguridad final para lo que no haya podido pararse solo.
    print("Buscando procesos huérfanos de servidores anteriores...")
    killed = kill_orphan_servers()
    if killed:
        print(f"  Procesados {len(killed)} proceso(s) huérfano(s):")
        for k in killed:
            print(f"    - {k}")
    else:
        print("  No se encontraron procesos huérfanos.")

    print("Liberando puerto 25565 si está ocupado...")
    port_killed = kill_port_25565()
    if port_killed:
        print(f"  Eliminados {len(port_killed)} proceso(s) en el puerto 25565: {port_killed}")
        time.sleep(1)
    else:
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

    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, reload=False, timeout_graceful_shutdown=5)
