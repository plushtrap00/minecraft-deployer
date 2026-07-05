"""
routes/modloader.py - Cambio de versión del modloader de un modpack.

Rutas:
- GET  /api/modpacks/{modpack}/modloader/versions       → loader/MC actuales + versiones disponibles
- POST /api/modpacks/{modpack}/modloader/check          → mods que dejarían de ser compatibles
- GET  /api/modpacks/{modpack}/modloader/install/stream → SSE: descarga e instala la versión elegida

Solo se puede cambiar entre versiones del MISMO tipo de loader detectado y la
MISMA versión de Minecraft del modpack — nunca de tipo de loader ni de MC.
"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import DEFAULT_SERVERS_PATH
from services.modpack import detect_modpack_version
from services.modloader import (
    loader_key_from_display, get_available_versions, check_mod_compatibility,
    install_loader_stream, LOADER_DISPLAY_NAMES,
)
from services import process as proc_module
from services.busy import BusyGuard

router = APIRouter(prefix="/api/modpacks", tags=["modloader"])


def _current_loader(modpack: str) -> tuple:
    info = detect_modpack_version(modpack)
    loader_key = loader_key_from_display(info.get("modloader"))
    if not loader_key:
        raise HTTPException(
            status_code=400,
            detail=f"No se detectó un modloader soportado (Forge/NeoForge/Fabric/Quilt) en este modpack."
        )
    mc_version = info.get("mc_version")
    if not mc_version:
        raise HTTPException(status_code=400, detail="No se pudo detectar la versión de Minecraft de este modpack.")
    return loader_key, mc_version, info.get("modloader_version")


@router.get("/{modpack}/modloader/versions")
async def modloader_versions(modpack: str):
    loader_key, mc_version, current_version = _current_loader(modpack)
    try:
        available = get_available_versions(loader_key, mc_version)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar las versiones de {LOADER_DISPLAY_NAMES.get(loader_key, loader_key)}: {e}")

    return JSONResponse({
        "loader": loader_key,
        "loader_display": LOADER_DISPLAY_NAMES.get(loader_key, loader_key),
        "mc_version": mc_version,
        "current_version": current_version,
        "available": [v for v in available if v != current_version],
    })


class ModloaderCheckBody(BaseModel):
    version: str


@router.post("/{modpack}/modloader/check")
async def modloader_check(modpack: str, body: ModloaderCheckBody):
    loader_key, mc_version, current_version = _current_loader(modpack)
    incompatible = check_mod_compatibility(modpack, loader_key, body.version)
    return JSONResponse({
        "success": True,
        "compatible": not incompatible,
        "incompatible_mods": incompatible,
    })


@router.get("/{modpack}/modloader/install/stream")
async def modloader_install_stream(modpack: str, version: str):
    """
    Antes de instalar, revalida todo lo que ya validó /check (por si cambió algo
    entre medio, p.ej. se agregó un mod). Como EventSource no puede leer el body
    de una respuesta de error, estas validaciones se emiten como evento SSE
    "error" en vez de HTTPException, para que el motivo llegue al usuario.
    """
    async def event_stream():
        try:
            loader_key, mc_version, current_version = _current_loader(modpack)

            with proc_module.mc_process_lock:
                server_running = proc_module.mc_process is not None and proc_module.mc_process.poll() is None
            if server_running:
                yield "data: " + json.dumps({"type": "error", "detail": "Para el servidor antes de cambiar la versión del modloader."}) + "\n\n"
                return

            try:
                available = get_available_versions(loader_key, mc_version)
            except Exception as e:
                yield "data: " + json.dumps({"type": "error", "detail": f"No se pudo consultar las versiones disponibles: {e}"}) + "\n\n"
                return
            if version not in available:
                yield "data: " + json.dumps({
                    "type": "error",
                    "detail": f"{version} no es una versión de {LOADER_DISPLAY_NAMES.get(loader_key, loader_key)} válida para MC {mc_version}.",
                }) + "\n\n"
                return

            incompatible = check_mod_compatibility(modpack, loader_key, version)
            if incompatible:
                names = ", ".join(m["display_name"] for m in incompatible)
                yield "data: " + json.dumps({
                    "type": "error",
                    "detail": f"No se puede cambiar a la versión {version}: dejarían de ser compatibles: {names}.",
                }) + "\n\n"
                return

            with BusyGuard(f"instalando {LOADER_DISPLAY_NAMES.get(loader_key, loader_key)} {version} en '{modpack}'"):
                async for event in install_loader_stream(modpack, loader_key, mc_version, version):
                    yield "data: " + json.dumps(event) + "\n\n"
        except HTTPException as e:
            yield "data: " + json.dumps({"type": "error", "detail": e.detail}) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "detail": str(e)}) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
