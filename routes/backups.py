"""
routes/backups.py - Copias de seguridad, clonado y estadísticas de jugadores
de un modpack.

Rutas:
- GET    /api/modpacks/{modpack}/backups                  → lista de copias
- POST   /api/modpacks/{modpack}/backups                  → hacer una copia ahora
- GET    /api/modpacks/{modpack}/backups/{name}/download  → descargar una copia
- POST   /api/modpacks/{modpack}/backups/{name}/restore   → restaurarla (servidor parado)
- DELETE /api/modpacks/{modpack}/backups/{name}           → borrarla
- POST   /api/modpacks/{modpack}/clone                    → duplicar el modpack
- GET    /api/modpacks/{modpack}/player-stats             → estadísticas de sus jugadores
"""
import asyncio

from fastapi import APIRouter, Depends, Form
from fastapi.responses import FileResponse, JSONResponse

from services import backups
from services.clone import clone_modpack
from services.player_stats import player_stats
from routes.deps import valid_modpack, modpack_path

router = APIRouter(prefix="/api/modpacks", tags=["backups"], dependencies=[Depends(valid_modpack)])


@router.get("/{modpack}/backups")
def list_backups(modpack: str):
    server_dir = modpack_path(modpack)
    return JSONResponse({
        "backups": backups.list_backups(modpack),
        "world": backups.active_world(server_dir),
        "has_world": bool(backups.world_folders(server_dir)),
    })


@router.post("/{modpack}/backups")
async def create_backup(modpack: str):
    modpack_path(modpack)
    result = await asyncio.to_thread(backups.create_backup, modpack, "manual")
    return JSONResponse({"success": True, **result})


@router.get("/{modpack}/backups/{name}/download")
def download_backup(modpack: str, name: str):
    path = backups.backup_file(modpack, name)
    return FileResponse(path, media_type="application/zip", filename=f"{modpack}-{name}")


@router.post("/{modpack}/backups/{name}/restore")
async def restore_backup(modpack: str, name: str):
    result = await asyncio.to_thread(backups.restore_backup, modpack, name)
    return JSONResponse({"success": True, **result})


@router.delete("/{modpack}/backups/{name}")
def delete_backup(modpack: str, name: str):
    backups.delete_backup(modpack, name)
    return JSONResponse({"success": True})


@router.post("/{modpack}/clone")
async def clone(modpack: str, new_name: str = Form(...), include_world: str = Form("0")):
    modpack_path(modpack)
    result = await asyncio.to_thread(clone_modpack, modpack, new_name, include_world == "1")
    return JSONResponse({"success": True, **result})


@router.get("/{modpack}/player-stats")
def get_player_stats(modpack: str):
    modpack_path(modpack)
    return JSONResponse(player_stats(modpack))
