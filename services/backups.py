"""
services/backups.py - Copias de seguridad del mundo de cada modpack.

Se guardan en SERVERS_PATH/.global/backups/<modpack>/ (fuera de la carpeta
del modpack: así no se copian al clonarlo y no desaparecen si se borra el
modpack por error). Cada copia es un .zip con el mundo activo y, si existen,
sus carpetas _nether y _the_end (formato Bukkit/Paper).

El nombre del archivo dice cuándo y por qué se hizo:
    <mundo>__<AAAAmmdd-HHMMSS>__<motivo>.zip
con motivo: manual, auto (automática), task (tarea programada) o
safety (la que se hace sola antes de restaurar otra). Solo las automáticas y
las de tareas se borran solas al pasar del límite «conservar»; las manuales y
las de seguridad se quedan hasta que alguien las borre.
"""
import re
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from config import DEFAULT_SERVERS_PATH
from services.busy import BusyGuard
from services.modpack import parse_server_properties, save_server_property

BACKUPS_DIR = DEFAULT_SERVERS_PATH / ".global" / "backups"
REASONS = {"manual": "Manual", "auto": "Automática", "task": "Tarea programada", "safety": "Antes de restaurar"}
_NAME_RE = re.compile(r"^(?P<world>[^/\\]+?)__(?P<stamp>\d{8}-\d{6})__(?P<reason>[a-z]+)\.zip$")
_SKIP_FILES = {"session.lock"}

_locks: dict = {}
_locks_guard = threading.Lock()


def _modpack_lock(modpack: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(modpack, threading.Lock())


def backup_dir(modpack: str) -> Path:
    return BACKUPS_DIR / modpack


def active_world(server_dir: Path) -> str:
    return parse_server_properties(server_dir.name).get("level-name", "world") or "world"


def world_folders(server_dir: Path, world: str | None = None) -> list:
    """El mundo activo y sus dimensiones aparte, si existen."""
    world = world or active_world(server_dir)
    return [name for name in (world, world + "_nether", world + "_the_end") if (server_dir / name).is_dir()]


def _parse_name(name: str) -> dict | None:
    match = _NAME_RE.match(name)
    if not match:
        return None
    try:
        created = datetime.strptime(match["stamp"], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return {"world": match["world"], "created": created, "reason": match["reason"]}


def list_backups(modpack: str) -> list:
    folder = backup_dir(modpack)
    if not folder.is_dir():
        return []
    items = []
    for path in folder.glob("*.zip"):
        info = _parse_name(path.name)
        if not info:
            continue
        items.append({
            "name": path.name,
            "world": info["world"],
            "reason": info["reason"],
            "reason_label": REASONS.get(info["reason"], info["reason"]),
            "created": info["created"].isoformat(timespec="seconds"),
            "size": path.stat().st_size,
        })
    items.sort(key=lambda item: item["created"], reverse=True)
    return items


def backup_file(modpack: str, name: str) -> Path:
    """Ruta de una copia existente; 400/404 si el nombre no es válido o no existe."""
    if not _parse_name(name):
        raise HTTPException(status_code=400, detail="Nombre de copia no válido")
    path = backup_dir(modpack) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="La copia no existe")
    return path


def last_backup_time(modpack: str, reasons=("auto", "task", "manual")) -> float | None:
    times = [
        datetime.fromisoformat(item["created"]).timestamp()
        for item in list_backups(modpack) if item["reason"] in reasons
    ]
    return max(times) if times else None


def _zip_folders(server_dir: Path, folders: list, target: Path) -> int:
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for folder in folders:
            base = server_dir / folder
            zf.write(base, folder)
            for path in sorted(base.rglob("*")):
                if path.name in _SKIP_FILES:
                    continue
                arcname = path.relative_to(server_dir).as_posix()
                try:
                    zf.write(path, arcname)
                except (FileNotFoundError, PermissionError):
                    continue  # archivo temporal que desapareció mientras se copiaba
                count += 1
    return count


def create_backup(modpack: str, reason: str = "manual", keep: int | None = None) -> dict:
    """
    Hace una copia del mundo activo. Si el servidor de ese modpack está
    encendido, congela el guardado mientras copia (ver world_frozen).
    keep: para automáticas y tareas, cuántas de ese tipo conservar.
    """
    from services.server_control import world_frozen

    if reason not in REASONS:
        raise ValueError("Motivo de copia desconocido")
    server_dir = DEFAULT_SERVERS_PATH / modpack
    if not server_dir.is_dir():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    world = active_world(server_dir)
    folders = world_folders(server_dir, world)
    if not folders:
        raise HTTPException(status_code=400, detail=f"Este modpack todavía no tiene mundo («{world}»)")

    lock = _modpack_lock(modpack)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya se está haciendo una copia de este modpack")
    try:
        with BusyGuard(f"copia de seguridad de {modpack}"):
            folder = backup_dir(modpack)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"{world}__{stamp}__{reason}.zip"
            target = folder / name
            if target.exists():
                time.sleep(1)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                name = f"{world}__{stamp}__{reason}.zip"
                target = folder / name
            partial = folder / (name + ".part")
            started = time.monotonic()
            try:
                with world_frozen(modpack):
                    files = _zip_folders(server_dir, folders, partial)
                partial.replace(target)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            if keep and reason in ("auto", "task"):
                prune(modpack, keep)
            return {
                "name": name,
                "files": files,
                "size": target.stat().st_size,
                "seconds": round(time.monotonic() - started, 1),
            }
    finally:
        lock.release()


def prune(modpack: str, keep: int) -> int:
    """Borra las automáticas y de tareas más antiguas por encima de `keep`."""
    removable = [item for item in list_backups(modpack) if item["reason"] in ("auto", "task")]
    removed = 0
    for item in removable[keep:]:
        try:
            (backup_dir(modpack) / item["name"]).unlink()
            removed += 1
        except OSError:
            pass
    return removed


def delete_backup(modpack: str, name: str) -> None:
    backup_file(modpack, name).unlink()


def _zip_top_folders(zf: zipfile.ZipFile) -> set:
    tops = set()
    for entry in zf.namelist():
        parts = entry.replace("\\", "/").split("/")
        if parts[0] and len(parts) > 1:
            tops.add(parts[0])
    return tops


def restore_backup(modpack: str, name: str) -> dict:
    """
    Sustituye el mundo por el de la copia. Solo con el servidor de ese modpack
    parado. Antes guarda una copia de seguridad del mundo actual (motivo
    «safety»), por si se restaura la que no era.
    """
    from services.server_control import running_modpack

    if running_modpack() == modpack:
        raise HTTPException(status_code=409, detail="Para el servidor antes de restaurar una copia")
    path = backup_file(modpack, name)
    server_dir = DEFAULT_SERVERS_PATH / modpack

    with zipfile.ZipFile(path) as zf:
        tops = _zip_top_folders(zf)
        bad = [t for t in tops if t.startswith(".") or t in ("mods", "config", "libraries")]
        if not tops or bad:
            raise HTTPException(status_code=400, detail="La copia no tiene el formato esperado")
        main_world = next((t for t in sorted(tops) if not t.endswith(("_nether", "_the_end"))), None)
        if not main_world:
            raise HTTPException(status_code=400, detail="La copia no contiene ningún mundo")

        safety = None
        if world_folders(server_dir):
            safety = create_backup(modpack, "safety")["name"]

        lock = _modpack_lock(modpack)
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Hay una copia de este modpack en curso")
        try:
            with BusyGuard(f"restaurando copia de {modpack}"):
                staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=server_dir))
                try:
                    zf.extractall(staging)
                    for top in tops:
                        current = server_dir / top
                        if current.exists():
                            shutil.rmtree(current)
                        shutil.move(str(staging / top), str(current))
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
        finally:
            lock.release()

    if active_world(server_dir) != main_world:
        save_server_property(modpack, "level-name", main_world)
    return {"world": main_world, "safety_backup": safety}
