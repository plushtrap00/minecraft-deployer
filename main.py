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
from routes.players import router as players_router
from routes.server import router as server_router
from routes.auth import router as auth_router, verify_token
from routes.users import router as users_router
from services.lifecycle import shutdown_event
from services.process import notify_app_shutdown

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
app.include_router(upload_router)
app.include_router(firewall_router)
app.include_router(players_router)
app.include_router(server_router)


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


def kill_orphan_servers() -> list:
    """Mata procesos Java residuales de ejecuciones anteriores del servidor Minecraft."""
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
                try:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    killed.append(f"{pid} ({cmdline[:60]})")
                except Exception:
                    pass
    except FileNotFoundError:
        try:
            result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
            for line in result.stdout.split("\n"):
                if "java" not in line.lower():
                    continue
                if any(k.lower() in line.lower() for k in mc_keywords):
                    pid = line.split()[1]
                    try:
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                        killed.append(pid)
                    except Exception:
                        pass
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
    from config import DEFAULT_SERVERS_PATH

    print("Minecraft Server Deployer arrancando...")

    print("Liberando puerto 8000 si está ocupado...")
    web_killed = kill_port(8000)
    if web_killed:
        print(f"  Eliminados {len(web_killed)} proceso(s) en el puerto 8000: {web_killed}")
        time.sleep(1)
    else:
        print("  Puerto 8000 libre.")

    print("Liberando puerto 25565 si está ocupado...")
    port_killed = kill_port_25565()
    if port_killed:
        print(f"  Eliminados {len(port_killed)} proceso(s) en el puerto 25565: {port_killed}")
        time.sleep(1)
    else:
        print("  Puerto 25565 libre.")

    print("Buscando procesos huérfanos de servidores anteriores...")
    killed = kill_orphan_servers()
    if killed:
        print(f"  Eliminados {len(killed)} proceso(s) huérfano(s):")
        for k in killed:
            print(f"    - {k}")
    else:
        print("  No se encontraron procesos huérfanos.")

    print("Limpiando session.lock abandonados...")
    locks = clean_orphan_locks()
    if locks:
        print(f"  Eliminados {len(locks)} session.lock abandonado(s):")
        for l in locks:
            print(f"    - {l}")
    else:
        print("  No se encontraron session.lock abandonados.")

    print(f"Carpeta por defecto: {DEFAULT_SERVERS_PATH}")
    print("Accede desde tu red local en: http://<IP-DE-ESTE-EQUIPO>:8000")

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, timeout_graceful_shutdown=5)
