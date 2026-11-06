"""
routes/mods.py - Mods instalados de un modpack: listar, subir (uno o en lote),
activar/desactivar, borrar, dependencias, duplicados, solo-cliente y mods
pendientes de instalar.

Rutas:
- GET       /api/modpacks/{modpack}/pending-mods
- GET       /api/modpacks/{modpack}/pending-mods/stream
- GET       /api/modpacks/{modpack}/mods
- GET       /api/modpacks/{modpack}/mods/download
- GET       /api/modpacks/{modpack}/mods/dependencies
- GET       /api/modpacks/{modpack}/mods/dependencies/install/stream
- GET       /api/modpacks/{modpack}/mods/duplicates
- GET       /api/modpacks/{modpack}/mods/client-only
- POST      /api/modpacks/{modpack}/mods/upload
- POST      /api/modpacks/{modpack}/mods/upload-bulk
- GET       /api/modpacks/{modpack}/mods/upload-bulk/stream/{job_id}
- POST      /api/modpacks/{modpack}/mods/upload-bulk/confirm
- DELETE    /api/modpacks/{modpack}/mods/{filename}
- POST      /api/modpacks/{modpack}/mods/{filename}/toggle
- POST      /api/modpacks/{modpack}/mods/delete-disabled
"""
import re
import json
import shutil
import secrets
import time
import zipfile
import asyncio
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import DEFAULT_SERVERS_PATH, TEMP_DIR
from app_constants import TEMP_DIR_MAX_AGE_SECONDS
from services.modpack import (
    detect_modpack_version, find_installed_mod_by_id, build_mod_id_index,
    mod_display_name, process_mod_jar, find_possible_duplicate_mods,
    classify_installed_mods, get_pending_mods, resolve_pending_mods,
    check_pending_mods_stream
)
from services.mod_dependencies import find_missing_dependencies, install_missing_dependencies
from services.busy import BusyGuard

from routes.deps import valid_modpack, modpack_path


router = APIRouter(prefix="/api/modpacks", tags=["mods"], dependencies=[Depends(valid_modpack)])


@router.get("/{modpack}/pending-mods")
def get_pending_mods_route(modpack: str):
    """Mods que quedaron sin descargar al instalar (ver services/modpack.get_pending_mods) — lectura rápida, sin abrir jars. Usado por el aviso de la pestaña Mods y como primer chequeo antes de iniciar el servidor."""
    return JSONResponse({"pending_mods": get_pending_mods(modpack)})


@router.get("/{modpack}/pending-mods/stream")
def get_pending_mods_stream(modpack: str):
    """
    Re-chequeo completo con progreso (ver services/modpack.check_pending_mods_stream):
    abre cada mod instalado para comparar su mod_id/versión real contra lo
    pendiente, por si se resolvió por una vía que el panel no ve directamente
    (copiado a mano por SFTP). El botón "Iniciar servidor" solo llama a esto
    cuando /pending-mods ya dijo que queda algo — si no hay nada pendiente, se
    salta este paso entero y arranca directo.
    """
    async def event_stream():
        # Cada paso abre jars del disco: se avanza el generador en un hilo
        # para no congelar el resto del panel mientras tanto.
        events = check_pending_mods_stream(modpack)
        while True:
            event = await asyncio.to_thread(next, events, None)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{modpack}/mods")
def list_mods(modpack: str):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return JSONResponse({"mods": [], "exists": False, "count": 0})
    mods = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".zip") or low.endswith(".jar.disabled")):
            continue
        mods.append({
            "name": mod_display_name(f.name), "filename": f.name,
            "enabled": not f.name.endswith(".disabled"), "size": f.stat().st_size,
        })
    return JSONResponse({"mods": mods, "exists": True, "count": len(mods)})


@router.get("/{modpack}/mods/download")
async def download_mods(modpack: str, include_disabled: int = 0):
    import os
    import tempfile

    base = modpack_path(modpack)

    mods_dir = base / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Este modpack no tiene carpeta mods/")

    # Mismo filtro que list_mods(). Los deshabilitados conservan su ".disabled"
    # dentro del zip: así el modloader los sigue ignorando si se copian tal cual.
    files = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith(".jar.disabled"):
            if include_disabled:
                files.append(f)
        elif low.endswith(".jar") or low.endswith(".zip"):
            files.append(f)
    if not files:
        raise HTTPException(status_code=404, detail="No hay mods que descargar")

    # Mismo patrón temporal que download_kubejs(). ZIP_STORED: los .jar ya van
    # comprimidos, recomprimirlos solo gasta CPU sin ahorrar apenas espacio.
    tmp_dir = tempfile.mkdtemp()
    archive_path = os.path.join(tmp_dir, "mods.zip")

    def build():
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as zf:
            for f in files:
                zf.write(f, arcname="mods/" + f.name)

    try:
        await asyncio.to_thread(build)
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
        headers={"Content-Disposition": f'attachment; filename="{modpack}-mods.zip"'},
    )


@router.get("/{modpack}/mods/dependencies")
async def mods_missing_dependencies(modpack: str):
    """Dependencias obligatorias que ningún mod habilitado aporta (solo lee disco, sin red). Ver services/mod_dependencies.py."""
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    missing = await asyncio.to_thread(find_missing_dependencies, mods_dir)
    return JSONResponse({"missing": missing})


@router.get("/{modpack}/mods/dependencies/install/stream")
def mods_install_dependencies_stream(modpack: str):
    """
    Busca e instala las dependencias que faltan, con progreso por SSE. Cada
    paso del generador (lecturas de jars, peticiones a Modrinth/CurseForge,
    descargas) corre en un hilo para no bloquear el resto del panel.
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")

    async def event_stream():
        busy_guard = BusyGuard(f"instalando dependencias en '{modpack}'")
        busy_guard.__enter__()
        try:
            events = install_missing_dependencies(modpack)
            while True:
                event = await asyncio.to_thread(next, events, None)
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        finally:
            busy_guard.__exit__(None, None, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{modpack}/mods/duplicates")
async def mods_duplicates(modpack: str):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    groups = await asyncio.to_thread(find_possible_duplicate_mods, mods_dir)
    return JSONResponse({"groups": groups})


@router.get("/{modpack}/mods/client-only")
async def mods_client_only(modpack: str):
    """
    Categoriza los mods instalados en server / client_only / unknown según su
    metadata de side/environment (ver classify_mod_side en services/modpack.py).
    Los "client_only" no se instalan del lado servidor A PROPÓSITO, no es un error.
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    result = await asyncio.to_thread(classify_installed_mods, mods_dir)
    return JSONResponse(result)


@router.post("/{modpack}/mods/upload")
async def upload_mod(modpack: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".jar"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .jar")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")

    with BusyGuard(f"subiendo mod a '{modpack}'"):
        jar_bytes = await file.read()
        server_info = await asyncio.to_thread(detect_modpack_version, modpack)
        server_mc = server_info.get("mc_version")
        filename = Path(file.filename).name

        result = await asyncio.to_thread(process_mod_jar, mods_dir, filename, jar_bytes, server_mc)
        if result["status"] in ("incompatible", "invalid"):
            raise HTTPException(status_code=409 if result["status"] == "incompatible" else 400, detail=result["detail"])
        if result["status"] == "already_installed":
            raise HTTPException(status_code=409, detail=result["detail"] + f" en {result['existing_filename']}.")
        if result["status"] == "needs_confirmation":
            # Versión más antigua que la instalada: no se rechaza directamente, se
            # arma un lote de un solo mod para que el usuario decida (mismo flujo
            # de confirmación que la subida masiva).
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

        resolve_pending_mods(modpack, result["filename"], result.get("mod_id"), result.get("mod_version"))

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


# ── Subida masiva de mods (zip / carpeta) ──────────────────────────────────────
#
# Flujo en dos pasos para poder reportar progreso "mod i de N" mientras se procesa:
# 1. POST /upload-bulk sube los archivos (o extrae el .zip) y los guarda en un
#    directorio de trabajo temporal, devolviendo un job_id sin procesar nada aún.
# 2. GET /upload-bulk/stream/{job_id} (SSE) procesa cada .jar uno a uno, emitiendo
#    un evento de progreso por mod y un evento final con el resultado categorizado.

BATCH_ROOT = TEMP_DIR / "mod-batches"
BATCH_ROOT.mkdir(parents=True, exist_ok=True)
UPLOAD_JOBS_ROOT = TEMP_DIR / "mod-upload-jobs"
UPLOAD_JOBS_ROOT.mkdir(parents=True, exist_ok=True)
_TEMP_DIR_MAX_AGE_SECONDS = TEMP_DIR_MAX_AGE_SECONDS
_BATCH_ID_RE = re.compile(r'^[0-9a-f]{8,64}$')
_JOB_ID_RE = re.compile(r'^[0-9a-f]{8,64}$')


def _cleanup_stale_dirs(root: Path):
    now = time.time()
    for d in root.iterdir():
        if d.is_dir() and now - d.stat().st_mtime > _TEMP_DIR_MAX_AGE_SECONDS:
            shutil.rmtree(d, ignore_errors=True)


class BulkConfirmBody(BaseModel):
    batch_id: str
    accept: List[str] = []


@router.post("/{modpack}/mods/upload-bulk")
async def prepare_mods_bulk(modpack: str, files: List[UploadFile] = File(...)):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")

    _cleanup_stale_dirs(BATCH_ROOT)
    _cleanup_stale_dirs(UPLOAD_JOBS_ROOT)

    job_id = secrets.token_hex(8)
    job_dir = UPLOAD_JOBS_ROOT / job_id
    job_dir.mkdir(parents=True)

    # Todo se copia a disco a trozos (copyfileobj) en vez de leerlo entero en
    # memoria: un .zip con un modpack completo podía ocupar cientos de MB de
    # RAM, más otra copia por cada .jar extraído.
    def _store_uploads() -> list:
        manifest = []

        def add(name: str, source) -> None:
            stored_name = f"{len(manifest):04d}_{name}"
            with open(job_dir / stored_name, "wb") as out:
                shutil.copyfileobj(source, out)
            manifest.append({"stored_name": stored_name, "filename": name})

        if len(files) == 1 and (files[0].filename or "").lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(files[0].file) as zf:
                    for info in zf.infolist():
                        name = Path(info.filename).name
                        if not info.is_dir() and name.lower().endswith(".jar"):
                            with zf.open(info) as member:
                                add(name, member)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="El archivo .zip no es válido")
            if not manifest:
                raise HTTPException(status_code=400, detail="El .zip no contiene archivos .jar")
        else:
            for f in files:
                name = Path(f.filename or "").name
                if name.lower().endswith(".jar"):
                    add(name, f.file)
            if not manifest:
                raise HTTPException(status_code=400, detail="No se encontraron archivos .jar")
        return manifest

    try:
        manifest = await asyncio.to_thread(_store_uploads)
    except BaseException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    (job_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return JSONResponse({"success": True, "job_id": job_id, "total": len(manifest)})


@router.get("/{modpack}/mods/upload-bulk/stream/{job_id}")
def stream_mods_bulk(modpack: str, job_id: str):
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="job_id inválido")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    job_dir = UPLOAD_JOBS_ROOT / job_id
    try:
        job_dir.resolve().relative_to(UPLOAD_JOBS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="La subida ya no existe o expiró")

    manifest_path = job_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []

    async def event_stream():
        server_info = await asyncio.to_thread(detect_modpack_version, modpack)
        server_mc = server_info.get("mc_version")
        total = len(manifest)
        added, already_installed, needs_confirmation, errors = [], [], [], []
        pending_bytes = {}

        busy_guard = BusyGuard(f"subiendo {total} mod(s) a '{modpack}'")
        busy_guard.__enter__()
        try:
            # Se arma una sola vez el índice mod_id -> (Path, meta) de lo ya
            # instalado; si no, process_mod_jar tendría que releer y reparsear
            # todos los mods instalados en CADA iteración (O(N×M)).
            mod_index = await asyncio.to_thread(build_mod_id_index, mods_dir)

            for i, item in enumerate(manifest, start=1):
                filename = item["filename"]
                jar_bytes = await asyncio.to_thread((job_dir / item["stored_name"]).read_bytes)
                result = await asyncio.to_thread(process_mod_jar, mods_dir, filename, jar_bytes, server_mc, mod_index)
                status = result["status"]
                if status == "added":
                    added.append(result)
                    await asyncio.to_thread(resolve_pending_mods, modpack, result["filename"], result.get("mod_id"), result.get("mod_version"))
                elif status == "already_installed":
                    already_installed.append(result)
                elif status == "needs_confirmation":
                    needs_confirmation.append(result)
                    pending_bytes[filename] = jar_bytes
                else:
                    errors.append(result)

                yield "data: " + json.dumps({
                    "type": "progress", "current": i, "total": total,
                    "filename": filename, "display_name": result.get("display_name"),
                }) + "\n\n"

            batch_id = None
            if needs_confirmation:
                batch_id = secrets.token_hex(8)
                batch_dir = BATCH_ROOT / batch_id
                batch_dir.mkdir(parents=True)
                for it in needs_confirmation:
                    (batch_dir / it["filename"]).write_bytes(pending_bytes[it["filename"]])
                (batch_dir / "manifest.json").write_text(json.dumps(needs_confirmation), encoding="utf-8")

            yield "data: " + json.dumps({
                "type": "done", "success": True, "batch_id": batch_id,
                "added": added, "already_installed": already_installed,
                "needs_confirmation": needs_confirmation, "errors": errors,
                "total": total,
            }) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "detail": str(e)}) + "\n\n"
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            busy_guard.__exit__(None, None, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{modpack}/mods/upload-bulk/confirm")
def confirm_mods_bulk(modpack: str, body: BulkConfirmBody):
    if not _BATCH_ID_RE.match(body.batch_id):
        raise HTTPException(status_code=400, detail="batch_id inválido")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    batch_dir = BATCH_ROOT / body.batch_id
    try:
        batch_dir.resolve().relative_to(BATCH_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="El lote ya no existe o expiró")

    manifest_path = batch_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    accept_set = set(body.accept)

    applied, skipped = [], []
    for item in manifest:
        filename = item["filename"]
        jar_path = batch_dir / filename
        if filename not in accept_set or not jar_path.exists():
            skipped.append(item)
            continue
        jar_bytes = jar_path.read_bytes()
        existing_path, existing_meta = find_installed_mod_by_id(mods_dir, item.get("mod_id"))
        if existing_path:
            was_disabled = existing_path.name.endswith(".disabled")
            existing_path.unlink()
            dest = mods_dir / (filename + ".disabled" if was_disabled else filename)
        else:
            dest = mods_dir / filename
        dest.write_bytes(jar_bytes)
        applied.append({**item, "filename": dest.name})
        resolve_pending_mods(modpack, dest.name, item.get("mod_id"), item.get("mod_version"))

    shutil.rmtree(batch_dir, ignore_errors=True)
    return JSONResponse({"success": True, "applied": applied, "skipped": skipped})


@router.delete("/{modpack}/mods/{filename}")
def delete_mod(modpack: str, filename: str):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    mod_path = mods_dir / filename
    try:
        mod_path.resolve().relative_to(mods_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not mod_path.exists() or not mod_path.is_file():
        raise HTTPException(status_code=404, detail="El mod no existe")
    mod_path.unlink()
    return JSONResponse({"success": True, "filename": filename})


@router.post("/{modpack}/mods/{filename}/toggle")
def toggle_mod(modpack: str, filename: str):
    """
    Deshabilita/habilita un mod renombrando el .jar con/sin el sufijo
    ".disabled" — no es una convención propia de Forge/NeoForge/Fabric/Quilt,
    funciona igual en los 4 porque el loader simplemente ignora cualquier
    archivo que no termine en .jar dentro de mods/.
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    mod_path = mods_dir / filename
    try:
        mod_path.resolve().relative_to(mods_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not mod_path.exists() or not mod_path.is_file():
        raise HTTPException(status_code=404, detail="El mod no existe")

    if filename.endswith(".disabled"):
        new_path = mods_dir / filename[: -len(".disabled")]
        new_enabled = True
    else:
        new_path = mods_dir / (filename + ".disabled")
        new_enabled = False

    if new_path.exists():
        raise HTTPException(status_code=400, detail=f"Ya existe un archivo en {new_path.name}")

    mod_path.rename(new_path)
    return JSONResponse({"success": True, "filename": new_path.name, "enabled": new_enabled})


class DeleteDisabledModsBody(BaseModel):
    filenames: List[str]


@router.post("/{modpack}/mods/delete-disabled")
def delete_disabled_mods(modpack: str, body: DeleteDisabledModsBody):
    """Borra en lote los mods deshabilitados que el usuario seleccionó a mano en el modal."""
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    deleted = []
    errors = []
    for filename in body.filenames:
        if not filename.endswith(".disabled"):
            errors.append({"filename": filename, "detail": "Solo se pueden borrar mods deshabilitados con este endpoint"})
            continue
        mod_path = mods_dir / filename
        try:
            mod_path.resolve().relative_to(mods_dir.resolve())
        except ValueError:
            errors.append({"filename": filename, "detail": "Ruta no permitida"})
            continue
        if not mod_path.exists() or not mod_path.is_file():
            errors.append({"filename": filename, "detail": "No encontrado"})
            continue
        mod_path.unlink()
        deleted.append(filename)
    return JSONResponse({"success": True, "deleted": deleted, "errors": errors})
