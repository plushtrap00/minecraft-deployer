"""
routes/worlds.py - Mundos de un modpack: listar, activar, crear, subir,
descargar, borrar y editar sus archivos de datos.

Rutas:
- GET       /api/modpacks/{modpack}/detected-mods
- GET       /api/modpacks/{modpack}/worlds
- POST      /api/modpacks/{modpack}/worlds/activate
- POST      /api/modpacks/{modpack}/worlds/create
- POST      /api/modpacks/{modpack}/worlds/upload
- GET       /api/modpacks/{modpack}/worlds/{world_name}/download
- DELETE    /api/modpacks/{modpack}/worlds/{world_name}
- GET       /api/modpacks/{modpack}/world-files
- GET/POST  /api/modpacks/{modpack}/world-file
"""
import re
import shutil
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import DEFAULT_SERVERS_PATH
from services.utils import get_world_files, extract_archive
from services.modpack import (
    detect_installed_mods, has_mod_keyword, parse_server_properties,
    save_server_property, get_worlds,
)
from services.busy import BusyGuard

from routes.deps import valid_modpack, modpack_path, world_path


router = APIRouter(prefix="/api/modpacks", tags=["worlds"], dependencies=[Depends(valid_modpack)])


@router.get("/{modpack}/detected-mods")
def detected_mods(modpack: str):
    names = detect_installed_mods(modpack)
    return JSONResponse({
        "has_biomesoplenty": has_mod_keyword(names, "biomesoplenty") or has_mod_keyword(names, "biomes-o-plenty"),
        "has_terraforged": has_mod_keyword(names, "terraforged"),
        "has_skyblockbuilder": has_mod_keyword(names, "skyblockbuilder") or has_mod_keyword(names, "skyblock-builder"),
        "has_create": has_mod_keyword(names, "create"),
        "has_jei": has_mod_keyword(names, "jei"),
        "has_rei": has_mod_keyword(names, "rei"),
        "has_waystones": has_mod_keyword(names, "waystones"),
        "has_spark": has_mod_keyword(names, "spark"),
        "mod_count": len(names),
    })
# ── Mundos ─────────────────────────────────────────────────────────────────────

@router.get("/{modpack}/worlds")
def list_worlds(modpack: str):
    worlds_info = get_worlds(modpack)
    props = parse_server_properties(modpack)
    return JSONResponse({
        **worlds_info,
        "level_type": props.get("level-type", "minecraft:normal"),
        "seed": props.get("level-seed", ""),
    })


@router.post("/{modpack}/worlds/activate")
def activate_world(modpack: str, world_name: str = Form(...)):
    if not world_path(modpack_path(modpack), world_name).is_dir():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "active": world_name})


@router.post("/{modpack}/worlds/create")
def create_world(
    modpack: str,
    world_name: str = Form(...),
    level_type: str = Form("minecraft:normal"),
    seed: str = Form(""),
    activate: str = Form("1"),
):
    if not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
        raise HTTPException(status_code=400, detail="Nombre de mundo inválido (solo letras, números, _ y -)")
    base = DEFAULT_SERVERS_PATH / modpack
    if (base / world_name).exists():
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre")
    save_server_property(modpack, "level-type", level_type)
    save_server_property(modpack, "level-seed", seed)
    if activate == "1":
        save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "world_name": world_name, "message": "Mundo configurado. Se generará al iniciar el servidor."})


@router.post("/{modpack}/worlds/upload")
async def upload_world(
    modpack: str,
    file: UploadFile = File(...),
    world_name: str = Form(...),
    activate: str = Form("1"),
):
    """
    Sube un mundo ya existente (partida de un jugador, backup de otro
    servidor...) empaquetado en .zip/.tar.gz/.tar.bz2/.tar/.rar y lo registra
    como carpeta de mundo de este modpack. Reutiliza extract_archive (mismos
    formatos que /api/upload-and-extract) y detecta si el archivo trae el
    mundo envuelto en una carpeta propia (ej. al comprimir la carpeta del
    mundo directamente) o con level.dat ya en la raíz del zip (ej. al
    comprimir *el contenido* de la carpeta).
    """
    import tempfile

    if not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
        raise HTTPException(status_code=400, detail="Nombre de mundo inválido (solo letras, números, _ y -)")
    base = DEFAULT_SERVERS_PATH / modpack
    if not base.exists():
        raise HTTPException(status_code=404, detail="Modpack no encontrado")
    dest = base / world_name
    if dest.exists():
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre")

    with BusyGuard(f"subiendo mundo a '{modpack}'"):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            archive_name = Path(file.filename).name if file.filename else "world.zip"
            temp_archive = tmp_dir / archive_name

            def _write_temp():
                with open(temp_archive, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

            await asyncio.to_thread(_write_temp)

            extract_dir = tmp_dir / "extracted"
            result = await asyncio.to_thread(extract_archive, temp_archive, extract_dir)

            def _is_world_dir(d: Path) -> bool:
                return (d / "level.dat").exists() or (d / "region").exists()

            def _find_world_root_or_error() -> Path:
                entries = list(extract_dir.iterdir())
                if not entries:
                    raise HTTPException(
                        status_code=400,
                        detail="Subida errónea: el archivo está vacío, no se pudo extraer ningún contenido.",
                    )
                if _is_world_dir(extract_dir):
                    return extract_dir

                subdirs = [d for d in entries if d.is_dir()]
                if len(subdirs) == 1 and _is_world_dir(subdirs[0]):
                    return subdirs[0]

                names = ", ".join(sorted(e.name for e in entries)[:10])
                if len(subdirs) > 1:
                    detail = (
                        "Subida errónea: el archivo contiene varias carpetas de nivel superior "
                        f"({names}) y ninguna es una carpeta de mundo válida (falta level.dat o region/ "
                        "dentro de ella). Comprime solo la carpeta del mundo, o su contenido directamente."
                    )
                else:
                    detail = (
                        "Subida errónea: no se encontró un mundo de Minecraft válido en el archivo "
                        f"(falta level.dat o region/). Contenido detectado en la raíz: {names}."
                    )
                raise HTTPException(status_code=400, detail=detail)

            world_root = await asyncio.to_thread(_find_world_root_or_error)

            await asyncio.to_thread(shutil.move, str(world_root), str(dest))

            size_mb = await asyncio.to_thread(
                lambda: sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / (1024 * 1024)
            )

            if activate == "1":
                save_server_property(modpack, "level-name", world_name)

            return JSONResponse({
                "success": True,
                "world_name": world_name,
                "size_mb": round(size_mb, 1),
                "files_extracted": result["files_extracted"],
                "activated": activate == "1",
            })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/{modpack}/worlds/{world_name}/download")
async def download_world(modpack: str, world_name: str):
    import shutil, tempfile, os
    from fastapi.responses import StreamingResponse
    base = modpack_path(modpack)
    world_dir = world_path(base, world_name)
    if not world_dir.is_dir():
        raise HTTPException(status_code=404, detail="El mundo no existe")

    tmp_dir = tempfile.mkdtemp()
    try:
        archive_base = os.path.join(tmp_dir, world_name)
        archive_path = await asyncio.to_thread(
            lambda: shutil.make_archive(archive_base, "zip", root_dir=str(base), base_dir=world_name)
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
        headers={"Content-Disposition": f'attachment; filename="{world_name}.zip"'},
    )


@router.get("/{modpack}/world-files")
def get_world_file_list(modpack: str, world_name: str):
    base = modpack_path(modpack)
    world_dir = world_path(base, world_name)
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    return JSONResponse({"groups": get_world_files(modpack, world_name)})


@router.get("/{modpack}/world-file")
def get_world_file(modpack: str, world_name: str, path: str):
    base = modpack_path(modpack)
    world_dir = world_path(base, world_name)
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    full_path = world_dir / path
    try:
        full_path.resolve().relative_to(world_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"content": full_path.read_text(encoding="utf-8", errors="replace"), "path": path})


@router.post("/{modpack}/world-file")
def save_world_file(modpack: str, world_name: str = Form(...), path: str = Form(...), content: str = Form(...)):
    base = modpack_path(modpack)
    world_dir = world_path(base, world_name)
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    full_path = world_dir / path
    try:
        full_path.resolve().relative_to(world_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})


@router.delete("/{modpack}/worlds/{world_name}")
async def delete_world(modpack: str, world_name: str):
    base = modpack_path(modpack)
    world_dir = world_path(base, world_name)
    if not world_dir.is_dir():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    # Solo carpetas que de verdad son un mundo: sin esto, "mods", "config" o
    # "libraries" también se podían borrar por esta vía.
    if not ((world_dir / "level.dat").exists() or (world_dir / "region").is_dir()):
        raise HTTPException(status_code=400, detail=f"«{world_name}» no es una carpeta de mundo")
    props = parse_server_properties(modpack)
    if world_name == props.get("level-name", "world"):
        raise HTTPException(status_code=400, detail="No puedes borrar el mundo activo. Cambia a otro primero.")

    def _delete():
        shutil.rmtree(world_dir)
        for suffix in ["_nether", "_the_end"]:
            sibling = base / (world_name + suffix)
            if sibling.is_dir():
                shutil.rmtree(sibling)

    await asyncio.to_thread(_delete)
    return JSONResponse({"success": True})
