"""
routes/modpack_install.py - Buscar e instalar modpacks completos (Modrinth/CurseForge)
creando un servidor nuevo, incluyendo su RAM asignada.

Endpoints:
- GET /api/modpack-install/search
- GET /api/modpack-install/versions
- GET /api/modpack-install/stream   (SSE — GET porque EventSource no soporta POST)
"""
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services.mod_search import ModSearchError
from services.server_create import validate_new_server_name
from services.modpack_install import (
    search_modrinth_modpacks, get_modrinth_modpack_versions, install_modrinth_modpack_stream,
    search_curseforge_modpacks, get_curseforge_modpack_versions, install_curseforge_modpack_stream,
)

router = APIRouter(prefix="/api/modpack-install", tags=["modpack-install"])

_SOURCES = {"modrinth", "curseforge"}


@router.get("/search")
async def search(source: str, query: str = "", limit: int = 20, offset: int = 0):
    if source not in _SOURCES:
        raise HTTPException(status_code=400, detail="source inválido")
    try:
        if source == "modrinth":
            results, total = await asyncio.to_thread(search_modrinth_modpacks, query, limit, offset)
        else:
            results, total = await asyncio.to_thread(search_curseforge_modpacks, query, limit, offset)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return JSONResponse({"results": results, "total": total})


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

        async for event in generator:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
