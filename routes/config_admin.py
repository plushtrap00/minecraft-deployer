"""
routes/config_admin.py - Panel de administración: editar .env y .APP_CONSTANTS.

Solo accesible para el rol admin (mismo criterio que gestión de usuarios y
firewall: acciones de infraestructura, no de uso normal del panel). Los
cambios no se aplican en caliente — hace falta reiniciar la app, para lo
cual este mismo panel ofrece un botón que reusa el mecanismo ya existente de
services/auto_update.py (mismo aviso de seguridad: no reinicia si hay un
servidor de Minecraft corriendo o una operación en curso).

Rutas:
- GET  /api/admin/env        → variables de .env conocidas (sin hashes de contraseña)
- POST /api/admin/env        → guarda cambios; una nueva contraseña (opcional) se hashea acá
- GET  /api/admin/constants  → valores + descripciones de .APP_CONSTANTS
- POST /api/admin/constants  → guarda cambios
- POST /api/admin/restart    → reinicia la app para aplicar lo anterior
"""
import asyncio
import bcrypt
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import dotenv_values, set_key

import app_constants
from services import auto_update
from routes.auth import require_admin as _require_admin

router = APIRouter(prefix="/api/admin", tags=["admin-config"])

_ENV_PATH = Path(__file__).parent.parent / ".env"

# Claves de .env que expone el formulario. APP_PASSWORD_HASH/PABLO_PASSWORD_HASH
# quedan afuera a propósito: no tiene sentido pegar un hash bcrypt a mano — el
# cambio de contraseña usa su propio campo de texto plano (ver new_password),
# que se hashea acá mismo antes de guardarlo.
_ENV_EDITABLE_KEYS = [
    "APP_USERNAME", "JWT_SECRET", "WEB_PORT", "SERVERS_PATH", "MC_DOMAIN",
    "CURSEFORGE_API_KEY", "AUTO_UPDATE_ENABLED", "AUTO_UPDATE_INTERVAL_SECONDS",
]


@router.get("/env")
async def get_env(request: Request):
    _require_admin(request)
    values = dotenv_values(_ENV_PATH) if _ENV_PATH.exists() else {}
    result = {key: values.get(key, "") for key in _ENV_EDITABLE_KEYS}
    # WEB_PORT/SERVERS_PATH en Docker los controla docker-compose.yml (mapeo de
    # puertos y volumen/carpeta), no este .env — el frontend usa esto para
    # avisar en vez de dejar que el usuario cambie un campo sin efecto real (y
    # que además falla al guardar si el .env está montado de solo lectura,
    # como en el docker-compose.yml que genera setup.py).
    result["in_docker"] = auto_update.running_in_docker()
    return JSONResponse(result)


class EnvUpdateBody(BaseModel):
    values: dict
    new_password: str = ""


@router.post("/env")
async def update_env(request: Request, body: EnvUpdateBody):
    _require_admin(request)

    try:
        if body.new_password:
            if len(body.new_password) < 8:
                raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
            password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
            await asyncio.to_thread(set_key, str(_ENV_PATH), "APP_PASSWORD_HASH", password_hash, quote_mode="never")

        for key, value in body.values.items():
            if key not in _ENV_EDITABLE_KEYS:
                continue
            await asyncio.to_thread(set_key, str(_ENV_PATH), key, str(value), quote_mode="never")
    except HTTPException:
        raise
    except OSError as e:
        # dotenv.set_key() escribe de forma atómica (archivo temporal + os.replace);
        # si .env no se puede escribir (p.ej. montado ":ro" en Docker), esto lanza
        # sin que quede rastro en ningún lado si no se captura explícitamente acá.
        print(f"[config-admin] No se pudo escribir {_ENV_PATH}: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar .env: el archivo no se puede escribir. Si usas Docker, "
                "comprueba que docker-compose.yml no monte el .env como solo lectura (sin "
                "\":ro\" en esa línea) — puede que necesites volver a ejecutar "
                "'python3 setup.py' para regenerarlo tras una actualización."
            ),
        )
    except Exception as e:
        print(f"[config-admin] Error inesperado guardando .env: {e!r}", flush=True)
        raise HTTPException(status_code=500, detail=f"Error inesperado al guardar .env: {e}")

    return JSONResponse({"success": True})


@router.get("/constants")
async def get_constants(request: Request):
    _require_admin(request)
    return JSONResponse(app_constants.get_all())


class ConstantsUpdateBody(BaseModel):
    values: dict


@router.post("/constants")
async def update_constants(request: Request, body: ConstantsUpdateBody):
    _require_admin(request)
    try:
        await asyncio.to_thread(app_constants.save, body.values)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"success": True})


@router.post("/restart")
async def restart_app(request: Request):
    _require_admin(request)
    try:
        await asyncio.to_thread(auto_update.restart_now)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    auto_update.schedule_restart()
    return JSONResponse({"success": True, "message": "Reiniciando la app..."})
