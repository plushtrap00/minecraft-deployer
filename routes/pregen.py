"""
routes/pregen.py - Pregenerar el mundo con Chunky (services/pregen.py).

Rutas:
- GET  /api/modpacks/{modpack}/pregen                  → Chunky, estado de la tarea, servidor
- GET  /api/modpacks/{modpack}/pregen/available        → versión de Chunky que se instalaría
- GET  /api/modpacks/{modpack}/pregen/estimate         → chunks y disco para un radio
- POST /api/modpacks/{modpack}/pregen/install          → instalar Chunky (lo pide una persona)
- POST /api/modpacks/{modpack}/pregen/uninstall        → quitar el Chunky que puso el panel
- POST /api/modpacks/{modpack}/pregen/start            → empezar (radio, dimensiones, solo vacío)
- POST /api/modpacks/{modpack}/pregen/cancel           → cancelar
"""
import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from routes.deps import valid_modpack
from services import pregen
from services.mod_search import ModSearchError

router = APIRouter(prefix="/api/modpacks", tags=["pregen"], dependencies=[Depends(valid_modpack)])


def _dimensions(raw: str) -> list:
    dims = [d for d in (raw or "").split(",") if d]
    if not dims or any(d not in pregen.DIMENSIONS for d in dims):
        raise HTTPException(status_code=400, detail="Dimensiones no válidas")
    return dims


@router.get("/{modpack}/pregen")
def pregen_status(modpack: str):
    return JSONResponse(pregen.status(modpack))


@router.get("/{modpack}/pregen/available")
async def pregen_available(modpack: str):
    try:
        return JSONResponse(await asyncio.to_thread(pregen.available_version, modpack))
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Modrinth: {e}")


@router.get("/{modpack}/pregen/estimate")
async def pregen_estimate(modpack: str, radius: int, dimensions: str):
    if not pregen.MIN_RADIUS <= radius <= pregen.MAX_RADIUS:
        raise HTTPException(status_code=400, detail="Radio no válido")
    return JSONResponse(await asyncio.to_thread(pregen.estimate, modpack, radius, _dimensions(dimensions)))


@router.post("/{modpack}/pregen/install")
async def pregen_install(modpack: str):
    try:
        return JSONResponse(await asyncio.to_thread(pregen.install, modpack))
    except pregen.PregenError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo descargar Chunky: {e}")


@router.post("/{modpack}/pregen/uninstall")
def pregen_uninstall(modpack: str):
    try:
        pregen.uninstall(modpack)
    except pregen.PregenError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"success": True})


@router.post("/{modpack}/pregen/start")
async def pregen_start(request: Request, modpack: str, radius: int = Form(...),
                       dimensions: str = Form(...), only_when_empty: str = Form("1")):
    request.state.activity_params = {"radius": radius}
    try:
        state = await asyncio.to_thread(pregen.start, modpack, radius, _dimensions(dimensions),
                                        only_when_empty == "1", getattr(request.state, "user", None))
    except pregen.PregenError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(state)


@router.post("/{modpack}/pregen/cancel")
def pregen_cancel(modpack: str):
    try:
        pregen.cancel(modpack)
    except pregen.PregenError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"success": True})
