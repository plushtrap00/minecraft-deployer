"""
main.py - Punto de entrada de Minecraft Server Deployer.

Crea la app FastAPI, registra todos los routers, y en __main__
ejecuta las tareas de limpieza antes de arrancar uvicorn.
"""
import mimetypes
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
from routes.automation import router as automation_router
from routes.backups import router as backups_router
from services.lifecycle import shutdown_event
from services.process import notify_app_shutdown
from services import auto_update, scheduler
from services.startup_cleanup import run_startup_cleanup

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
        # index.html pide el CSS/JS con ?v=<arranque> (routes/system.py), que
        # cambia en cada reinicio o actualización: con esa versión el
        # navegador puede guardarlos sin volver a preguntar, y una versión
        # nueva se pide sola porque la URL ya es otra.
        if (request.url.path.startswith("/static/") and "v" in request.query_params
                and response.status_code == 200):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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
    scheduler.start()
    yield
    scheduler.stop()
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
app.include_router(automation_router)
app.include_router(backups_router)


if __name__ == "__main__":
    import uvicorn
    from config import DEFAULT_SERVERS_PATH, WEB_PORT

    print("Minecraft Server Deployer arrancando...")

    run_startup_cleanup(WEB_PORT)

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
