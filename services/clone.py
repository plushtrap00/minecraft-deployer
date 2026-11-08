"""
services/clone.py - Duplicar un modpack (mods, configuración, scripts...)
para probar cambios sin tocar el bueno. El mundo se copia solo si se pide.

No se copian logs, crash reports ni scripts temporales de arranque. La copia
se hace primero en una carpeta oculta (que el panel no lista) y se renombra
al final, así un clon a medias nunca aparece como modpack.
"""
import shutil
import uuid

from fastapi import HTTPException

from config import DEFAULT_SERVERS_PATH
from services.backups import world_folders
from services.busy import BusyGuard
from services.server_create import validate_new_server_name

_SKIP_ROOT = {"logs", "crash-reports", "debug"}


def clone_modpack(source: str, new_name: str, include_world: bool) -> dict:
    from services.server_control import world_frozen

    new_name = (new_name or "").strip()
    try:
        validate_new_server_name(new_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    source_dir = DEFAULT_SERVERS_PATH / source
    if not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    target = DEFAULT_SERVERS_PATH / new_name

    worlds = set(world_folders(source_dir))

    def ignore(directory, names):
        skipped = {"session.lock"} & set(names)
        if directory == str(source_dir):
            skipped |= _SKIP_ROOT & set(names)
            skipped |= {n for n in names if n.startswith("tmp") and n.endswith(".sh")}
            if not include_world:
                skipped |= worlds & set(names)
        return skipped

    staging = DEFAULT_SERVERS_PATH / f".clone-{uuid.uuid4().hex[:8]}"
    try:
        with BusyGuard(f"clonando {source}"):
            if include_world:
                with world_frozen(source):
                    shutil.copytree(source_dir, staging, ignore=ignore, symlinks=True)
            else:
                shutil.copytree(source_dir, staging, ignore=ignore, symlinks=True)
            if target.exists():
                raise HTTPException(status_code=409, detail=f"Ya existe un modpack llamado «{new_name}»")
            staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {"name": new_name, "world_copied": include_world and bool(worlds)}
