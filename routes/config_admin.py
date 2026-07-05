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
    return JSONResponse({key: values.get(key, "") for key in _ENV_EDITABLE_KEYS})


class EnvUpdateBody(BaseModel):
    values: dict
    new_password: str = ""


@router.post("/env")
async def update_env(request: Request, body: EnvUpdateBody):
    _require_admin(request)

    if body.new_password:
        if len(body.new_password) < 8:
            raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
        password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
        await asyncio.to_thread(set_key, str(_ENV_PATH), "APP_PASSWORD_HASH", password_hash, quote_mode="never")

    for key, value in body.values.items():
        if key not in _ENV_EDITABLE_KEYS:
            continue
        await asyncio.to_thread(set_key, str(_ENV_PATH), key, str(value), quote_mode="never")

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
