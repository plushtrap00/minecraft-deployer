"""
routes/modpacks.py - Datos generales de un modpack: server.properties, RAM de la
JVM, versión, importar (subir y descomprimir) y borrar el modpack entero.

Rutas:
- GET/POST  /api/modpacks/{modpack}/server-properties
- POST      /api/modpacks/{modpack}/server-property
- GET/POST  /api/modpacks/{modpack}/ram
- GET       /api/modpacks/{modpack}/version
- DELETE    /api/modpacks/{modpack}
- POST      /api/upload-and-extract
"""
import re
import json
import shutil
import asyncio
import tempfile
from pathlib import Path
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import DEFAULT_SERVERS_PATH, TEMP_DIR
from services.utils import extract_archive, configure_jvm_ram, detect_jvm_ram
from services.modpack import detect_modpack_version, save_server_property
from services.players import ensure_global_dir, read_global_file, PLAYER_FILES
from services.busy import BusyGuard, is_busy, busy_reasons
from services.server_create import validate_new_server_name
from services import process as proc_module

from routes.deps import valid_modpack, modpack_path


router = APIRouter(prefix="/api/modpacks", tags=["modpacks"], dependencies=[Depends(valid_modpack)])


# ── server.properties ──────────────────────────────────────────────────────────

@router.get("/{modpack}/server-properties")
def get_server_properties(modpack: str):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    return JSONResponse({"content": props_file.read_text(encoding="utf-8")})


@router.post("/{modpack}/server-properties")
def save_server_properties(modpack: str, content: str = Form(...)):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    props_file.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})



@router.post("/{modpack}/server-property")
def set_server_property(modpack: str, key: str = Form(...), value: str = Form(...)):
    """Actualiza una sola propiedad en server.properties."""
    if not (DEFAULT_SERVERS_PATH / modpack / "server.properties").exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    save_server_property(modpack, key, value)
    return JSONResponse({"success": True, "key": key, "value": value})


# ── RAM de la JVM ──────────────────────────────────────────────────────────────
# La misma comprobación en tres pasos que ya usaba la importación de modpacks
# (configure_jvm_ram/detect_jvm_ram en services/utils.py), reutilizada aquí
# para poder cambiar la RAM DESPUÉS de creado el servidor, no solo al crearlo.

_RAM_VALUE_RE = re.compile(r'^\d+[MG]$', re.IGNORECASE)


@router.get("/{modpack}/ram")
def get_ram(modpack: str):
    server_dir = DEFAULT_SERVERS_PATH / modpack
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    return JSONResponse(detect_jvm_ram(server_dir))


class RamUpdateBody(BaseModel):
    ram_min: str
    ram_max: str


@router.post("/{modpack}/ram")
async def set_ram(modpack: str, body: RamUpdateBody):
    server_dir = DEFAULT_SERVERS_PATH / modpack
    if not server_dir.exists():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    if not _RAM_VALUE_RE.match(body.ram_min) or not _RAM_VALUE_RE.match(body.ram_max):
        raise HTTPException(status_code=400, detail="Formato de RAM inválido (ej: 4G, 2500M)")

    source = await asyncio.to_thread(configure_jvm_ram, server_dir, body.ram_min, body.ram_max)
    if not source:
        raise HTTPException(
            status_code=409,
            detail=(
                "No se pudo detectar dónde configura este modpack la RAM (no tiene "
                "user_jvm_args.txt, variables.txt, ni -Xms/-Xmx en su script de arranque). "
                "Edítala a mano en la carpeta del servidor."
            ),
        )
    return JSONResponse({"success": True, "source": source})
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
    folder_name = folder_name.strip()
    # Mismo criterio que crear un servidor o instalar un modpack descargado:
    # sin esto, una ruta absoluta o con "../" descomprimía el archivo en
    # cualquier carpeta, y un nombre ya usado mezclaba el contenido nuevo con
    # el de un modpack existente.
    try:
        validate_new_server_name(folder_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if configure_ram == "1" and not (_RAM_VALUE_RE.match(ram_min) and _RAM_VALUE_RE.match(ram_max)):
        raise HTTPException(status_code=400, detail="Formato de RAM inválido (ej: 4G, 2500M)")

    dest = DEFAULT_SERVERS_PATH / folder_name
    # Carpeta temporal propia por subida, y solo el nombre base del archivo
    # (sin las carpetas que pueda traer): el nombre lo decide el cliente.
    tmp_dir = Path(tempfile.mkdtemp(dir=TEMP_DIR))
    temp_file = tmp_dir / (Path(file.filename or "").name or "modpack.zip")
    extracted = False
    busy_guard = BusyGuard(f"importando modpack '{folder_name}'")
    busy_guard.__enter__()
    try:
        def _write_temp():
            with open(temp_file, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        await asyncio.to_thread(_write_temp)
        file_size_mb = temp_file.stat().st_size / (1024 * 1024)
        result = await asyncio.to_thread(extract_archive, temp_file, dest)
        extracted = True

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
        # Si la extracción falló a medias, la carpeta nueva queda incompleta:
        # se borra (solo puede ser nuestra, se comprobó arriba que no existía).
        if not extracted and dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        busy_guard.__exit__(None, None, None)


# ── Borrar modpack completo ────────────────────────────────────────────────────

@router.delete("/{modpack}")
async def delete_modpack(modpack: str):
    """
    Borra la carpeta entera del modpack (mundos, config, kubejs, mods, logs...
    todo). La triple confirmación ("¿seguro? / los mundos y config se pierden /
    última oportunidad") vive en el frontend (manage.js) — aquí solo quedan las
    comprobaciones de que sea seguro hacerlo ya mismo, mismo criterio que
    auto_update.restart_now(): ni con el servidor de este modpack en marcha ni
    con una operación en curso (subida/instalación de mods, creación de otro
    servidor...) que pudiera estar tocando esta misma carpeta.
    """
    base = modpack_path(modpack)
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
def get_modpack_version(modpack: str):
    return JSONResponse(detect_modpack_version(modpack))
