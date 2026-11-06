"""
routes/mod_files.py - Editor de archivos de configuración de mods (config/) y
de scripts de KubeJS (kubejs/).

Rutas:
- GET       /api/modpacks/{modpack}/configs
- GET/POST  /api/modpacks/{modpack}/config-file
- GET       /api/modpacks/{modpack}/kubejs
- GET/POST/DELETE /api/modpacks/{modpack}/kubejs-file
- POST      /api/modpacks/{modpack}/kubejs-new
- POST      /api/modpacks/{modpack}/kubejs-move
- GET       /api/modpacks/{modpack}/kubejs/download
"""
import re
import shutil
import asyncio
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import DEFAULT_SERVERS_PATH
from services.utils import get_mod_configs, get_kubejs_files, invalidate_kubejs_cache

from routes.deps import valid_modpack, modpack_path


router = APIRouter(prefix="/api/modpacks", tags=["mod-files"], dependencies=[Depends(valid_modpack)])


# ── Archivos de config ─────────────────────────────────────────────────────────

@router.get("/{modpack}/configs")
def get_mod_config_list(modpack: str):
    return JSONResponse({"mods": get_mod_configs(modpack)})


@router.get("/{modpack}/config-file")
def get_config_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "config").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"content": full_path.read_text(encoding="utf-8", errors="replace"), "path": path})


@router.post("/{modpack}/config-file")
def save_config_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "config").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})


# ── KubeJS ─────────────────────────────────────────────────────────────────────

@router.get("/{modpack}/kubejs")
def get_kubejs_list(modpack: str):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    exists = kjs_dir.exists()
    return JSONResponse({"exists": exists, "groups": get_kubejs_files(modpack) if exists else {}})


@router.get("/{modpack}/kubejs-file")
def get_kubejs_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"content": full_path.read_text(encoding="utf-8", errors="replace"), "path": path})


@router.post("/{modpack}/kubejs-new")
def create_kubejs_file(
    modpack: str,
    subfolder: str = Form(...),
    filename: str = Form(...),
):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    if not kjs_dir.exists():
        raise HTTPException(status_code=404, detail="Este modpack no tiene carpeta kubejs/")
    if not re.match(r'^[\w.\-]+$', filename):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido (solo letras, números, _, -, .)")
    if subfolder == '__root__':
        rel_path = filename
    else:
        if not re.match(r'^[\w\-/]+$', subfolder):
            raise HTTPException(status_code=400, detail="Ruta de carpeta inválida")
        rel_path = subfolder.strip('/') + '/' + filename
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / rel_path
    base = (DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if full_path.exists():
        raise HTTPException(status_code=400, detail=f"{filename} ya existe en esa carpeta")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text('', encoding='utf-8')
    invalidate_kubejs_cache(modpack)
    return JSONResponse({"success": True, "path": rel_path.replace('\\', '/')})


@router.post("/{modpack}/kubejs-file")
def save_kubejs_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})


@router.delete("/{modpack}/kubejs-file")
def delete_kubejs_file(modpack: str, path: str):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    if not kjs_dir.exists():
        raise HTTPException(status_code=404, detail="Este modpack no tiene carpeta kubejs/")
    base = kjs_dir.resolve()
    full_path = kjs_dir / path
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.unlink()
    invalidate_kubejs_cache(modpack)
    return JSONResponse({"success": True})


@router.post("/{modpack}/kubejs-move")
def move_kubejs_file(modpack: str, from_path: str = Form(...), to_path: str = Form(...)):
    """Mueve y/o renombra un archivo dentro de kubejs/ (mismo endpoint para ambos: un
    renombrado es solo un move con la misma carpeta y otro nombre de archivo)."""
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    if not kjs_dir.exists():
        raise HTTPException(status_code=404, detail="Este modpack no tiene carpeta kubejs/")
    base = kjs_dir.resolve()

    src = kjs_dir / from_path
    dest = kjs_dir / to_path
    try:
        src.resolve().relative_to(base)
        dest.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")

    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail="Archivo de origen no encontrado")
    if not re.match(r'^[\w.\-]+$', dest.name):
        raise HTTPException(status_code=400, detail="Nombre de archivo destino inválido (solo letras, números, _, -, .)")
    if dest.exists():
        raise HTTPException(status_code=400, detail=f"Ya existe un archivo en {to_path}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    invalidate_kubejs_cache(modpack)
    return JSONResponse({"success": True, "path": str(dest.relative_to(kjs_dir)).replace('\\', '/')})


@router.get("/{modpack}/kubejs/download")
async def download_kubejs(modpack: str):
    import os
    import tempfile

    base = modpack_path(modpack)

    kjs_dir = base / "kubejs"
    if not kjs_dir.exists():
        raise HTTPException(status_code=404, detail="Este modpack no tiene carpeta kubejs/")

    # Carpeta temporal única por request (tempfile.mkdtemp): nunca colisiona con
    # otra descarga concurrente y se borra entera en el finally de abajo, así
    # que no quedan zips viejos acumulándose en /tmp. Mismo patrón que ya usa
    # la descarga de mundos (worlds/{world_name}/download).
    tmp_dir = tempfile.mkdtemp()
    try:
        archive_base = os.path.join(tmp_dir, "kubejs")
        archive_path = await asyncio.to_thread(
            lambda: shutil.make_archive(archive_base, "zip", root_dir=str(base), base_dir="kubejs")
        )
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))

    def iter_and_cleanup():
        try:
            with open(archive_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(
        iter_and_cleanup(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{modpack}-kubejs.zip"'},
    )
