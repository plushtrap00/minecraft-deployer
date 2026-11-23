"""
routes/mod_updates.py - Actualizaciones de los mods instalados (services/mod_updates.py).

Rutas:
- POST /api/modpacks/{modpack}/mods/updates/check → empieza a comprobar (en segundo plano)
- GET  /api/modpacks/{modpack}/mods/updates       → progreso y resultado de la comprobación
- POST /api/modpacks/{modpack}/mods/updates/apply → actualiza un mod {filename}
- POST /api/modpacks/{modpack}/mods/updates/undo  → deshace un lote {batch}
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routes.deps import valid_modpack
from services import mod_updates
from services.mod_search import ModSearchError

router = APIRouter(prefix="/api/modpacks", tags=["mod-updates"], dependencies=[Depends(valid_modpack)])


def _public(job: dict | None) -> dict:
    if not job:
        return {"state": "idle"}
    result = job.get("result")
    if result:
        # La URL de descarga se queda en el servidor: el panel solo manda el nombre.
        result = {**result, "updates": [{k: v for k, v in u.items() if k not in ("download_url", "file_key")}
                                         | {"downloadable": bool(u.get("download_url"))}
                                         for u in result["updates"]]}
    return {**{k: job[k] for k in ("state", "stage", "done", "total", "error")}, "result": result}


@router.post("/{modpack}/mods/updates/check")
def check_mod_updates(modpack: str):
    return JSONResponse(_public(mod_updates.start_check(modpack)))


@router.get("/{modpack}/mods/updates")
def mod_updates_status(modpack: str):
    return JSONResponse(_public(mod_updates.job_status(modpack)))


class ApplyBody(BaseModel):
    filename: str


@router.post("/{modpack}/mods/updates/apply")
def apply_mod_update(request: Request, modpack: str, body: ApplyBody):
    request.state.activity_detail = body.filename
    try:
        return JSONResponse({"success": True, **mod_updates.apply_one(modpack, body.filename)})
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo cambiar el archivo: {e}")


class UndoBody(BaseModel):
    batch: str


@router.post("/{modpack}/mods/updates/undo")
def undo_mod_updates(modpack: str, body: UndoBody):
    try:
        return JSONResponse({"success": True, **mod_updates.undo_batch(modpack, body.batch)})
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
