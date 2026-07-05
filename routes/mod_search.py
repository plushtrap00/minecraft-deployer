"""
routes/mod_search.py - Búsqueda e instalación de mods desde Modrinth/CurseForge.

Rutas:
- GET  /api/modpacks/{modpack}/mods/search                          → buscar por nombre
- GET  /api/modpacks/{modpack}/mods/search/{source}/{project_id}/files → archivos/versiones de un mod
- POST /api/modpacks/{modpack}/mods/search/install                  → descarga e instala el archivo elegido

La instalación reusa process_mod_jar(), la misma función que usa la subida
manual (routes/modpacks.py), así que pasa por las mismas validaciones de
compatibilidad de MC y de mod ya instalado / versión más antigua.
"""
import json
import secrets
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import DEFAULT_SERVERS_PATH
from services.modpack import detect_modpack_version, process_mod_jar
from services.modloader import loader_key_from_display
from services.mod_search import (
    ModSearchError, search_modrinth, search_curseforge,
    get_modrinth_versions, get_curseforge_files, download_bytes,
)
from routes.modpacks import BATCH_ROOT

router = APIRouter(prefix="/api/modpacks", tags=["mod-search"])

VALID_SOURCES = {"modrinth", "curseforge"}


def _server_context(modpack: str) -> tuple:
    info = detect_modpack_version(modpack)
    return info.get("mc_version"), loader_key_from_display(info.get("modloader"))


@router.get("/{modpack}/mods/search")
async def search_mods(modpack: str, query: str, source: str = "modrinth"):
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser 'modrinth' o 'curseforge'")
    query = query.strip()
    if not query:
        return JSONResponse({"results": []})

    mc_version, loader = _server_context(modpack)
    try:
        if source == "modrinth":
            results = search_modrinth(query, mc_version, loader)
        else:
            results = search_curseforge(query, mc_version, loader)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return JSONResponse({"results": results, "mc_version": mc_version, "loader": loader})


@router.get("/{modpack}/mods/search/{source}/{project_id}/files")
async def search_mod_files(modpack: str, source: str, project_id: str):
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser 'modrinth' o 'curseforge'")

    mc_version, loader = _server_context(modpack)
    try:
        if source == "modrinth":
            files = get_modrinth_versions(project_id, mc_version, loader)
        else:
            files = get_curseforge_files(project_id, mc_version, loader)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return JSONResponse({"files": files})


class InstallBody(BaseModel):
    source: str
    download_url: str | None = None
    filename: str


@router.post("/{modpack}/mods/search/install")
async def install_searched_mod(modpack: str, body: InstallBody):
    if body.source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser 'modrinth' o 'curseforge'")
    if not body.download_url:
        raise HTTPException(
            status_code=400,
            detail="Este mod no tiene descarga directa disponible (el autor la deshabilitó para terceros)."
        )

    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")

    try:
        jar_bytes = download_bytes(body.download_url)
    except ModSearchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    server_info = detect_modpack_version(modpack)
    server_mc = server_info.get("mc_version")
    filename = body.filename

    # Mismo flujo (y mismas formas de respuesta) que /mods/upload, para que el
    # frontend pueda reusar exactamente la misma lógica de resultado.
    result = process_mod_jar(mods_dir, filename, jar_bytes, server_mc)
    if result["status"] in ("incompatible", "invalid"):
        raise HTTPException(status_code=409 if result["status"] == "incompatible" else 400, detail=result["detail"])
    if result["status"] == "already_installed":
        raise HTTPException(status_code=409, detail=result["detail"] + f" en {result['existing_filename']}.")
    if result["status"] == "needs_confirmation":
        batch_id = secrets.token_hex(8)
        batch_dir = BATCH_ROOT / batch_id
        batch_dir.mkdir(parents=True)
        (batch_dir / result["filename"]).write_bytes(jar_bytes)
        (batch_dir / "manifest.json").write_text(json.dumps([result]), encoding="utf-8")
        return JSONResponse({
            "success": True,
            "batch_id": batch_id,
            "added": [],
            "already_installed": [],
            "needs_confirmation": [result],
            "errors": [],
            "total": 1,
        })

    return JSONResponse({
        "success": True,
        "filename": result["filename"],
        "mod_id": result.get("mod_id"),
        "mod_version": result.get("mod_version"),
        "server_mc": server_mc,
        "size_kb": round(len(jar_bytes) / 1024, 1),
        "replaced_filename": result.get("replaced_filename"),
        "previous_version": result.get("previous_version"),
    })
