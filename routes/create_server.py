"""
routes/create_server.py - Crear un servidor nuevo desde cero (sin importar un modpack existente).

Endpoints:
- GET  /api/create-server/mc-versions
- GET  /api/create-server/loader-versions
- GET  /api/create-server/stream   (SSE — GET porque EventSource no soporta POST)
"""
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services.server_create import get_vanilla_mc_versions, validate_new_server_name, create_server_stream
from services.modloader import get_available_versions, LOADER_DISPLAY_NAMES
from services.busy import BusyGuard

router = APIRouter(prefix="/api/create-server", tags=["create-server"])

_LOADER_KEYS = {"vanilla", "neoforge", "forge", "fabric", "quilt"}


@router.get("/mc-versions")
async def mc_versions():
    try:
        versions = await asyncio.to_thread(get_vanilla_mc_versions)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar la API de Mojang: {e}")
    return JSONResponse({"versions": versions})


@router.get("/loader-versions")
async def loader_versions(loader: str, mc_version: str):
    if loader not in _LOADER_KEYS or loader == "vanilla":
        raise HTTPException(status_code=400, detail="Loader inválido")
    try:
        versions = await asyncio.to_thread(get_available_versions, loader, mc_version)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar versiones de {LOADER_DISPLAY_NAMES.get(loader, loader)}: {e}")
    return JSONResponse({"loader_display": LOADER_DISPLAY_NAMES.get(loader, loader), "versions": versions})


@router.get("/stream")
async def create_server_sse(
    name: str, mc_version: str, ram_min: str, ram_max: str,
    loader: str = "vanilla", loader_version: str = "",
):
    async def event_stream():
        # Validación previa fuera del generador de services/: un EventSource no
        # puede leer el body de una respuesta de error HTTP normal, así que
        # cualquier problema detectado ANTES de tocar disco se manda como un
        # evento "error" dentro del propio stream (mismo patrón que ya usa
        # routes/modloader.py para su instalación por SSE).
        try:
            validate_new_server_name(name)
            if loader not in _LOADER_KEYS:
                raise ValueError("Loader inválido")
            if loader != "vanilla" and not loader_version:
                raise ValueError("Falta la versión del modloader")
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
            return

        loader_key = None if loader == "vanilla" else loader
        version = loader_version if loader_key else ""
        with BusyGuard(f"creando servidor '{name}'"):
            async for event in create_server_stream(name, mc_version, loader_key, version, ram_min, ram_max):
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
