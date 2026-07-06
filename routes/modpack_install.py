"""
routes/modpack_install.py - Buscar e instalar modpacks completos (Modrinth/CurseForge)
creando un servidor nuevo, incluyendo su RAM asignada.

Endpoints:
- GET /api/modpack-install/search
- GET /api/modpack-install/categories
- GET /api/modpack-install/versions
- GET /api/modpack-install/check-existing
- GET /api/modpack-install/stream   (SSE — GET porque EventSource no soporta POST)
"""
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app_constants import MOD_SEARCH_PAGE_SIZE
from services.mod_search import ModSearchError
from services.server_create import validate_new_server_name
from services.modpack_install import (
    search_modrinth_modpacks, get_modrinth_modpack_versions, install_modrinth_modpack_stream,
    search_curseforge_modpacks, get_curseforge_modpack_versions, install_curseforge_modpack_stream,
    get_modrinth_modpack_categories, get_curseforge_modpack_categories,
    get_modrinth_modpack_files, get_curseforge_modpack_files, find_similar_installed_modpacks,
    ModpackDownloadBlocked,
)
from services.busy import BusyGuard

router = APIRouter(prefix="/api/modpack-install", tags=["modpack-install"])

_SOURCES = {"modrinth", "curseforge"}
SEARCH_PAGE_SIZE = MOD_SEARCH_PAGE_SIZE


@router.get("/search")
async def search(
    source: str, query: str = "", category: str = "", offset: int = 0,
    mc_version: str = "", loader: str = "",
):
    if source not in _SOURCES:
        raise HTTPException(status_code=400, detail="source inválido")
    categories = [c for c in category.split(",") if c] if category else None
    try:
        if source == "modrinth":
            results, total = await asyncio.to_thread(
                search_modrinth_modpacks, query, categories, SEARCH_PAGE_SIZE, offset,
                mc_version=mc_version or None, loader=loader or None,
            )
        else:
            results, total = await asyncio.to_thread(
                search_curseforge_modpacks, query, categories, SEARCH_PAGE_SIZE, offset,
                mc_version=mc_version or None, loader=loader or None,
            )
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse({"results": results, "total": total, "offset": offset, "limit": SEARCH_PAGE_SIZE})


@router.get("/categories")
async def categories_endpoint(source: str):
    if source not in _SOURCES:
        raise HTTPException(status_code=400, detail="source inválido")
    try:
        cats = get_modrinth_modpack_categories() if source == "modrinth" else get_curseforge_modpack_categories()
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse({"categories": cats})


@router.get("/versions")
async def versions(source: str, project_id: str):
    if source not in _SOURCES:
        raise HTTPException(status_code=400, detail="source inválido")
    try:
        if source == "modrinth":
            result = await asyncio.to_thread(get_modrinth_modpack_versions, project_id)
        else:
            result = await asyncio.to_thread(get_curseforge_modpack_versions, project_id)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse({"versions": result})


@router.get("/check-existing")
async def check_existing(source: str, project_id: str, version_id: str):
    """
    Comprueba si esta versión de modpack ya podría estar instalada en algún
    servidor existente, comparando su lista de mods (sin descargarlos) contra
    los mods ya instalados en cada servidor — ver find_similar_installed_modpacks().
    """
    if source not in _SOURCES:
        raise HTTPException(status_code=400, detail="source inválido")
    try:
        if source == "modrinth":
            filenames, mc_version = await asyncio.to_thread(get_modrinth_modpack_files, project_id, version_id)
        else:
            try:
                cf_project_id = int(project_id)
                cf_file_id = int(version_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="ID de CurseForge inválido")
            filenames, mc_version = await asyncio.to_thread(get_curseforge_modpack_files, cf_project_id, cf_file_id)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ModpackDownloadBlocked as e:
        # A diferencia de un mod suelto bloqueado (que solo se salta), esto
        # bloquea el PROPIO archivo del modpack: instalar desde esta app
        # fallaría igual, así que se marca "blocked" para que el frontend
        # impida el botón de instalar en vez de solo avisar.
        return JSONResponse({"matches": [], "checked": False, "blocked": True, "reason": str(e)})
    except RuntimeError as e:
        # Otro motivo por el que no se pudo leer esta versión (p.ej. un ID
        # desactualizado) — no necesariamente impide instalar, así que no
        # bloquea el botón, solo informa de que no se pudo comprobar.
        return JSONResponse({"matches": [], "checked": False, "blocked": False, "reason": str(e)})
    matches = await asyncio.to_thread(find_similar_installed_modpacks, filenames, mc_version)
    return JSONResponse({"matches": matches, "checked": True, "blocked": False})


@router.get("/stream")
async def install_stream(source: str, project_id: str, version_id: str, name: str, ram_min: str, ram_max: str):
    async def event_stream():
        # Igual que routes/create_server.py: la validación previa se manda como
        # evento "error" dentro del stream, porque EventSource no puede leer el
        # body de una respuesta de error HTTP normal.
        try:
            if source not in _SOURCES:
                raise ValueError("source inválido")
            validate_new_server_name(name)
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
            return

        if source == "modrinth":
            generator = install_modrinth_modpack_stream(project_id, version_id, name, ram_min, ram_max)
        else:
            # El id de CurseForge es numérico en la API real; se intenta convertir
            # y si no es válido se informa como error del stream, no un 500.
            try:
                cf_project_id = int(project_id)
                cf_file_id = int(version_id)
            except ValueError:
                yield f"data: {json.dumps({'type': 'error', 'detail': 'ID de CurseForge inválido'})}\n\n"
                return
            generator = install_curseforge_modpack_stream(cf_project_id, cf_file_id, name, ram_min, ram_max)

        with BusyGuard(f"instalando modpack '{name}' desde {source}"):
            async for event in generator:
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
