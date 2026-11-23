"""
routes/modpack_update.py - Actualizar un servidor a otra versión de su modpack
(services/modpack_update.py).

Rutas:
- GET    /api/modpacks/{modpack}/pack-update         → modpack vinculado y sus versiones
- POST   /api/modpacks/{modpack}/pack-source         → vincular a mano {source, project_id, title}
- DELETE /api/modpacks/{modpack}/pack-source         → desvincular
- GET    /api/modpacks/{modpack}/pack-update/running → si hay una actualización en marcha
- GET    /api/modpacks/{modpack}/pack-update/stream  → actualizar a ?version_id=... o seguir
  la que está en marcha (?attach=1); la actualización sigue aunque se corte (SSE)
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from routes.deps import valid_modpack
from services import modpack_update
from services.mod_search import ModSearchError

router = APIRouter(prefix="/api/modpacks", tags=["modpack-update"], dependencies=[Depends(valid_modpack)])


@router.get("/{modpack}/pack-update")
async def pack_update_info(modpack: str):
    try:
        return JSONResponse(await asyncio.to_thread(modpack_update.list_versions, modpack))
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))


class SourceBody(BaseModel):
    source: str
    project_id: str
    title: str | None = None


@router.post("/{modpack}/pack-source")
def link_pack_source(modpack: str, body: SourceBody):
    try:
        data = modpack_update.link_source(modpack, body.source, body.project_id, (body.title or "")[:200] or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"success": True, "source": data})


@router.delete("/{modpack}/pack-source")
def unlink_pack_source(modpack: str):
    modpack_update.unlink_source(modpack)
    return JSONResponse({"success": True})


@router.get("/{modpack}/pack-update/running")
def pack_update_running(modpack: str):
    job = modpack_update.running_update(modpack)
    return JSONResponse({"running": bool(job), "version_id": job["version_id"] if job else None})


@router.get("/{modpack}/pack-update/stream")
async def pack_update_stream(request: Request, modpack: str, version_id: str = "", attach: bool = False):
    """Empieza la actualización (o, con attach, solo sigue la que ya está en marcha)."""
    job = modpack_update.running_update(modpack)
    request.state.activity_skip = bool(job) or attach
    if not job and not attach:
        job = modpack_update.start_update(modpack, version_id)

    async def event_stream():
        if not job:
            event = {"type": "done", "success": False, "detail": "No hay ninguna actualización en marcha"}
            yield f"data: {json.dumps(event)}\n\n"
            return
        async for event in modpack_update.follow(job):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
