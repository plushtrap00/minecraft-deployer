"""
routes/modpacks.py - Endpoints de configuración y contenido de modpacks.

Rutas:
- GET/POST  /api/modpacks/{modpack}/server-properties
- GET/POST  /api/modpacks/{modpack}/config-file
- GET       /api/modpacks/{modpack}/configs
- GET/POST  /api/modpacks/{modpack}/kubejs-file
- GET       /api/modpacks/{modpack}/kubejs
- POST      /api/upload-and-extract
- DELETE    /api/modpacks/{modpack}
- GET       /api/modpacks/{modpack}/version
- GET       /api/modpacks/{modpack}/mods
- GET       /api/modpacks/{modpack}/mods/duplicates
- POST      /api/modpacks/{modpack}/mods/upload
- POST      /api/modpacks/{modpack}/mods/upload-bulk
- GET       /api/modpacks/{modpack}/mods/upload-bulk/stream/{job_id}
- POST      /api/modpacks/{modpack}/mods/upload-bulk/confirm
- DELETE    /api/modpacks/{modpack}/mods/{filename}
- POST      /api/modpacks/{modpack}/mods/{filename}/toggle
- POST      /api/modpacks/{modpack}/mods/delete-disabled
- GET       /api/modpacks/{modpack}/mods/client-only
- GET       /api/modpacks/{modpack}/detected-mods
- GET       /api/modpacks/{modpack}/worlds
- POST      /api/modpacks/{modpack}/worlds/activate
- POST      /api/modpacks/{modpack}/worlds/create
- DELETE    /api/modpacks/{modpack}/worlds/{world_name}
- GET       /api/modpacks/{modpack}/world-files
- GET/POST  /api/modpacks/{modpack}/world-file
- GET       /api/modpacks/{modpack}/logs
- GET       /api/modpacks/{modpack}/logs/{filename}
"""
import re
import io
import json
import gzip
import shutil
import secrets
import time
import zipfile
import asyncio
from pathlib import Path
from typing import List
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from config import DEFAULT_SERVERS_PATH, TEMP_DIR
from app_constants import TEMP_DIR_MAX_AGE_SECONDS
from routes.auth import require_admin
from services.utils import get_mod_configs, get_kubejs_files, get_world_files, extract_archive, configure_jvm_ram, invalidate_kubejs_cache
from services.modpack import (
    detect_modpack_version, find_installed_mod_by_id, build_mod_id_index,
    mod_display_name, process_mod_jar, find_possible_duplicate_mods,
    detect_installed_mods, has_mod_keyword,
    parse_server_properties, save_server_property,
    get_worlds, analyze_crash, classify_installed_mods,
    prune_old_logs_and_crashes,
)
from services.players import (
    ensure_global_dir, read_global_file, write_global_file, PLAYER_FILES,
)
from services.busy import BusyGuard, is_busy, busy_reasons
from services import process as proc_module

router = APIRouter(prefix="/api/modpacks", tags=["modpacks"])


# ── server.properties ──────────────────────────────────────────────────────────

@router.get("/{modpack}/server-properties")
async def get_server_properties(modpack: str):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    return JSONResponse({"content": props_file.read_text(encoding="utf-8")})


@router.post("/{modpack}/server-properties")
async def save_server_properties(modpack: str, content: str = Form(...)):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    props_file.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})



@router.post("/{modpack}/server-property")
async def set_server_property(modpack: str, key: str = Form(...), value: str = Form(...)):
    """Actualiza una sola propiedad en server.properties."""
    if not (DEFAULT_SERVERS_PATH / modpack / "server.properties").exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    save_server_property(modpack, key, value)
    return JSONResponse({"success": True, "key": key, "value": value})

# ── Archivos de config ─────────────────────────────────────────────────────────

@router.get("/{modpack}/configs")
async def get_mod_config_list(modpack: str):
    return JSONResponse({"mods": get_mod_configs(modpack)})


@router.get("/{modpack}/config-file")
async def get_config_file(modpack: str, path: str):
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
async def save_config_file(modpack: str, path: str = Form(...), content: str = Form(...)):
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
async def get_kubejs_list(modpack: str):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    exists = kjs_dir.exists()
    return JSONResponse({"exists": exists, "groups": get_kubejs_files(modpack) if exists else {}})


@router.get("/{modpack}/kubejs-file")
async def get_kubejs_file(modpack: str, path: str):
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
async def create_kubejs_file(
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
async def save_kubejs_file(modpack: str, path: str = Form(...), content: str = Form(...)):
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
async def delete_kubejs_file(modpack: str, path: str):
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
async def move_kubejs_file(modpack: str, from_path: str = Form(...), to_path: str = Form(...)):
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

    base = DEFAULT_SERVERS_PATH / modpack
    try:
        base.resolve().relative_to(DEFAULT_SERVERS_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")

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


# ── Upload & extract ───────────────────────────────────────────────────────────

upload_router = APIRouter(tags=["modpacks"])

@upload_router.post("/api/upload-and-extract")
async def upload_and_extract(
    file: UploadFile = File(...),
    folder_name: str = Form(...),
    configure_ram: str = Form("0"),
    ram_min: str = Form(""),
    ram_max: str = Form(""),
):
    if not folder_name.strip():
        raise HTTPException(status_code=400, detail="El nombre de carpeta no puede estar vacío")

    dest = DEFAULT_SERVERS_PATH / folder_name.strip()
    temp_file = TEMP_DIR / file.filename
    busy_guard = BusyGuard(f"importando modpack '{folder_name.strip()}'")
    busy_guard.__enter__()
    try:
        def _write_temp():
            with open(temp_file, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        await asyncio.to_thread(_write_temp)
        file_size_mb = temp_file.stat().st_size / (1024 * 1024)
        result = await asyncio.to_thread(extract_archive, temp_file, dest)

        jvm_configured = None
        if configure_ram == "1" and ram_min and ram_max:
            jvm_path = configure_jvm_ram(dest, ram_min, ram_max)
            if jvm_path:
                jvm_configured = f"-Xms{ram_min} / -Xmx{ram_max}"

        # Sincronizar archivos globales de jugadores al nuevo modpack
        ensure_global_dir()
        synced_player_files = []
        for fname in PLAYER_FILES:
            global_data = read_global_file(fname)
            if global_data:
                dest_file = dest / fname
                dest_file.write_text(
                    json.dumps(global_data, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                synced_player_files.append(fname)

        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "size_mb": round(file_size_mb, 2),
            "destination": str(dest),
            "files_extracted": result["files_extracted"],
            "format": result["format"],
            "jvm_configured": jvm_configured,
            "synced_player_files": synced_player_files,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file.exists():
            temp_file.unlink()
        busy_guard.__exit__(None, None, None)


# ── Borrar modpack completo ────────────────────────────────────────────────────

@router.delete("/{modpack}")
async def delete_modpack(modpack: str):
    """
    Borra la carpeta entera del modpack (mundos, config, kubejs, mods, logs...
    todo). La triple confirmación ("¿seguro? / los mundos y config se pierden /
    última oportunidad") vive en el frontend (manage.js) — acá solo quedan las
    comprobaciones de que sea seguro hacerlo ya mismo, mismo criterio que
    auto_update.restart_now(): ni con el servidor de este modpack en marcha ni
    con una operación en curso (subida/instalación de mods, creación de otro
    servidor...) que pudiera estar tocando esta misma carpeta.
    """
    base = DEFAULT_SERVERS_PATH / modpack
    try:
        base.resolve().relative_to(DEFAULT_SERVERS_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="El modpack no existe")

    with proc_module.mc_process_lock:
        server_running = (
            proc_module.mc_running_modpack == modpack
            and proc_module.mc_process is not None
            and proc_module.mc_process.poll() is None
        )
    if server_running:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede borrar: el servidor de '{modpack}' está en marcha. Detenlo primero.",
        )
    if is_busy():
        raise HTTPException(
            status_code=409,
            detail=f"No se puede borrar: hay una operación en curso ({', '.join(busy_reasons())}).",
        )

    with BusyGuard(f"borrando modpack '{modpack}'"):
        await asyncio.to_thread(shutil.rmtree, base)
    return JSONResponse({"success": True})


# ── Versión y mods ─────────────────────────────────────────────────────────────

@router.get("/{modpack}/version")
async def get_modpack_version(modpack: str):
    return JSONResponse(detect_modpack_version(modpack))


@router.get("/{modpack}/mods")
async def list_mods(modpack: str):
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
        mods.append({"name": mod_display_name(f.name), "filename": f.name, "enabled": not f.name.endswith(".disabled")})
    return JSONResponse({"mods": mods, "exists": True, "count": len(mods)})


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
        server_info = detect_modpack_version(modpack)
        server_mc = server_info.get("mc_version")
        filename = Path(file.filename).name

        result = process_mod_jar(mods_dir, filename, jar_bytes, server_mc)
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

    jars = []
    if len(files) == 1 and files[0].filename.lower().endswith(".zip"):
        zip_bytes = await files[0].read()
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = Path(info.filename).name
                    if name.lower().endswith(".jar"):
                        jars.append((name, zf.read(info)))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="El archivo .zip no es válido")
        if not jars:
            raise HTTPException(status_code=400, detail="El .zip no contiene archivos .jar")
    else:
        for f in files:
            name = Path(f.filename).name
            if name.lower().endswith(".jar"):
                jars.append((name, await f.read()))
        if not jars:
            raise HTTPException(status_code=400, detail="No se encontraron archivos .jar")

    job_id = secrets.token_hex(8)
    job_dir = UPLOAD_JOBS_ROOT / job_id
    job_dir.mkdir(parents=True)
    manifest = []
    for i, (name, jar_bytes) in enumerate(jars):
        stored_name = f"{i:04d}_{name}"
        (job_dir / stored_name).write_bytes(jar_bytes)
        manifest.append({"stored_name": stored_name, "filename": name})
    (job_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return JSONResponse({"success": True, "job_id": job_id, "total": len(jars)})


@router.get("/{modpack}/mods/upload-bulk/stream/{job_id}")
async def stream_mods_bulk(modpack: str, job_id: str):
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
        server_info = detect_modpack_version(modpack)
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
                jar_bytes = (job_dir / item["stored_name"]).read_bytes()
                result = process_mod_jar(mods_dir, filename, jar_bytes, server_mc, mod_index)
                status = result["status"]
                if status == "added":
                    added.append(result)
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
                await asyncio.sleep(0)

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
async def confirm_mods_bulk(modpack: str, body: BulkConfirmBody):
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

    shutil.rmtree(batch_dir, ignore_errors=True)
    return JSONResponse({"success": True, "applied": applied, "skipped": skipped})


@router.delete("/{modpack}/mods/{filename}")
async def delete_mod(modpack: str, filename: str):
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
async def toggle_mod(modpack: str, filename: str):
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
async def delete_disabled_mods(modpack: str, body: DeleteDisabledModsBody):
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


@router.get("/{modpack}/detected-mods")
async def detected_mods(modpack: str):
    names = detect_installed_mods(modpack)
    return JSONResponse({
        "has_biomesoplenty": has_mod_keyword(names, "biomesoplenty") or has_mod_keyword(names, "biomes-o-plenty"),
        "has_create": has_mod_keyword(names, "create"),
        "has_jei": has_mod_keyword(names, "jei"),
        "has_rei": has_mod_keyword(names, "rei"),
        "has_waystones": has_mod_keyword(names, "waystones"),
        "has_spark": has_mod_keyword(names, "spark"),
        "mod_count": len(names),
    })


# ── Mundos ─────────────────────────────────────────────────────────────────────

@router.get("/{modpack}/worlds")
async def list_worlds(modpack: str):
    worlds_info = get_worlds(modpack)
    props = parse_server_properties(modpack)
    return JSONResponse({
        **worlds_info,
        "level_type": props.get("level-type", "minecraft:normal"),
        "seed": props.get("level-seed", ""),
    })


@router.post("/{modpack}/worlds/activate")
async def activate_world(modpack: str, world_name: str = Form(...)):
    base = DEFAULT_SERVERS_PATH / modpack
    if not (base / world_name).exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "active": world_name})


@router.post("/{modpack}/worlds/create")
async def create_world(
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


@router.get("/{modpack}/worlds/{world_name}/download")
async def download_world(modpack: str, world_name: str):
    import shutil, tempfile, os
    from fastapi.responses import StreamingResponse
    base = DEFAULT_SERVERS_PATH / modpack
    world_path = base / world_name
    try:
        world_path.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not world_path.exists():
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
async def get_world_file_list(modpack: str, world_name: str):
    base = DEFAULT_SERVERS_PATH / modpack
    world_dir = base / world_name
    try:
        world_dir.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not world_dir.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    return JSONResponse({"groups": get_world_files(modpack, world_name)})


@router.get("/{modpack}/world-file")
async def get_world_file(modpack: str, world_name: str, path: str):
    base = DEFAULT_SERVERS_PATH / modpack
    world_dir = base / world_name
    try:
        world_dir.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
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
async def save_world_file(modpack: str, world_name: str = Form(...), path: str = Form(...), content: str = Form(...)):
    base = DEFAULT_SERVERS_PATH / modpack
    world_dir = base / world_name
    try:
        world_dir.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
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
    base = DEFAULT_SERVERS_PATH / modpack
    world_path = base / world_name
    try:
        world_path.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not world_path.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    props = parse_server_properties(modpack)
    if world_name == props.get("level-name", "world"):
        raise HTTPException(status_code=400, detail="No puedes borrar el mundo activo. Cambia a otro primero.")
    shutil.rmtree(world_path)
    for suffix in ["_nether", "_the_end"]:
        sibling = base / (world_name + suffix)
        if sibling.exists():
            shutil.rmtree(sibling)
    return JSONResponse({"success": True})


# ── Logs & crash reports ───────────────────────────────────────────────────────

@router.get("/{modpack}/logs")
async def get_log_list(modpack: str):
    base = DEFAULT_SERVERS_PATH / modpack
    await asyncio.to_thread(prune_old_logs_and_crashes, modpack)
    logs = []
    if (base / "logs").exists():
        for f in sorted((base / "logs").iterdir(), reverse=True):
            if f.is_file() and f.suffix in {".log", ".gz", ".txt"}:
                logs.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "log"})
    crashes = []
    if (base / "crash-reports").exists():
        for f in sorted((base / "crash-reports").iterdir(), reverse=True):
            if f.is_file():
                crashes.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "crash"})
    return JSONResponse({"logs": logs[:20], "crashes": crashes[:30]})


@router.get("/{modpack}/logs/{filename}")
async def get_log_file(modpack: str, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=403, detail="Nombre de archivo inválido")
    base = DEFAULT_SERVERS_PATH / modpack
    file_path = next(
        (c for c in [base / "logs" / filename, base / "crash-reports" / filename] if c.exists()),
        None
    )
    if file_path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if filename.endswith(".gz"):
        def _read_gz():
            with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
                return f.read()
        raw = await asyncio.to_thread(_read_gz)
    else:
        raw = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="replace")
    culprits = analyze_crash(raw, modpack)
    return JSONResponse({"content": raw, "culprits": culprits, "filename": filename})


# ── Firewall (ufw) ─────────────────────────────────────────────────────────────

firewall_router = APIRouter(tags=["firewall"])

_UFW_UNAVAILABLE_DETAIL = (
    "ufw no está disponible en este entorno (normal si corres en Docker: el "
    "firewall se gestiona desde el host, no desde dentro del contenedor — "
    "controla el acceso público/LAN con el mapeo de puertos de docker-compose.yml)."
)


@firewall_router.post("/api/firewall/set")
async def set_firewall(request: Request, mode: str = Form(...)):
    """
    Configura ufw para el puerto 25565.
    mode='lan'    → solo red local (192.168.1.0/24)
    mode='public' → acceso desde cualquier IP
    """
    require_admin(request)
    import subprocess

    if mode not in ("lan", "public"):
        raise HTTPException(status_code=400, detail="mode debe ser 'lan' o 'public'")

    async def run(cmd: list) -> tuple[int, str]:
        try:
            r = await asyncio.to_thread(subprocess.run, ["sudo"] + cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise HTTPException(status_code=409, detail=_UFW_UNAVAILABLE_DETAIL)
        return r.returncode, r.stdout + r.stderr

    # Primero limpiar reglas existentes del 25565
    await run(["ufw", "delete", "allow", "25565"])
    await run(["ufw", "delete", "allow", "from", "192.168.1.0/24", "to", "any", "port", "25565"])

    if mode == "public":
        code, out = await run(["ufw", "allow", "25565"])
    else:
        code, out = await run(["ufw", "allow", "from", "192.168.1.0/24", "to", "any", "port", "25565"])

    if code != 0:
        raise HTTPException(status_code=500, detail=f"Error ejecutando ufw: {out}")

    return JSONResponse({"success": True, "mode": mode})


@firewall_router.get("/api/firewall/status")
async def firewall_status(request: Request):
    """
    Devuelve el modo actual del firewall para el puerto 25565, o mode="unavailable"
    si ufw/sudo no existen en este entorno (p. ej. dentro de un contenedor Docker,
    donde además no tendría efecto real sobre el host aunque estuviera instalado).
    """
    require_admin(request)
    import subprocess
    try:
        r = await asyncio.to_thread(subprocess.run, ["sudo", "ufw", "status"], capture_output=True, text=True)
    except FileNotFoundError:
        return JSONResponse({"mode": "unavailable", "ufw_output": ""})
    output = r.stdout

    # Detectar si hay regla pública (ALLOW Anywhere en 25565)
    lines = output.splitlines()
    has_public = any("25565" in l and "Anywhere" in l and "ALLOW" in l for l in lines)
    has_lan    = any("25565" in l and "192.168.1.0/24" in l for l in lines)

    if has_public:
        mode = "public"
    elif has_lan:
        mode = "lan"
    else:
        mode = "unknown"

    return JSONResponse({"mode": mode, "ufw_output": output})
