"""
services/backups.py - Copias de seguridad de cada modpack.

Se guardan en SERVERS_PATH/.global/backups/<modpack>/ (fuera de la carpeta
del modpack: así no se copian al clonarlo y no desaparecen si se borra el
modpack por error). Hay dos tipos:

- del mundo: el mundo activo y, si existen, sus carpetas _nether y _the_end
  (formato Bukkit/Paper).
- completa: todo el servidor (mods, configuración, scripts, server.properties,
  listas de ops y whitelist y el mundo) menos lo que se regenera solo o no
  hace falta para volver a jugar (FULL_SKIP: librerías del modloader, logs,
  informes de caídas...). Al restaurarla, el servidor queda como estaba.

El nombre del archivo dice cuándo, por qué y de qué tipo es:
    <mundo>__<AAAAmmdd-HHMMSS>__<motivo>[__full].zip
con motivo: manual, auto (automática), task (tarea programada) o
safety (la que se hace sola antes de restaurar otra). Solo las automáticas y
las de tareas se borran solas al pasar del límite «conservar»; las manuales y
las de seguridad se quedan hasta que alguien las borre.

Destino secundario (opcional, Automatización → Copias): una carpeta en otro
disco (un NAS, un disco USB, una carpeta de red montada). Cada copia se
duplica allí en segundo plano y, si la del disco principal se pierde, la del
destino secundario sigue saliendo en la lista y se puede descargar o
restaurar. Al borrar una copia (a mano o por el límite) se borra de los dos.
"""
import os
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
REASONS = {"manual": "Manual", "auto": "Automática", "task": "Tarea programada", "safety": "Antes de restaurar",
           "packupdate": "Antes de actualizar el modpack"}
KINDS = {"world": "Mundo", "full": "Completa"}
_NAME_RE = re.compile(r"^(?P<world>[^/\\]+?)__(?P<stamp>\d{8}-\d{6})__(?P<reason>[a-z]+)(?:__(?P<full>full))?\.zip$")
_SKIP_FILES = {"session.lock"}
# Archivos ocultos que sí van en una copia completa: de qué modpack y versión
# es el servidor (services/modpack_update.py), para que al restaurar cuadre.
FULL_DOTFILES = {".pack_source.json"}
# Lo que no entra en una copia completa (nombres de primer nivel del servidor).
FULL_SKIP = {"libraries", "logs", "crash-reports", "debug", "backups", "versions", "cache", ".cache",
             ".fabric", ".mixin.out", "__pycache__"}
_FULL_SKIP_SUFFIXES = (".log", ".log.gz", ".tmp", ".part")
# Margen libre que se deja en el disco además de lo que ocupará la copia.
_FREE_MARGIN_BYTES = 256 * 1024 * 1024
# Por debajo de esto, la lista avisa de que queda poco espacio.
LOW_SPACE_RATIO = 0.10

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


def full_entries(server_dir: Path) -> list:
    """Lo que entra en una copia completa: todo el primer nivel salvo FULL_SKIP."""
    entries = []
    for path in sorted(server_dir.iterdir()):
        name = path.name
        if name in FULL_SKIP or (name.startswith(".") and name not in FULL_DOTFILES) or name.endswith(_FULL_SKIP_SUFFIXES) or name in _SKIP_FILES:
            continue
        entries.append(name)
    return entries


def _parse_name(name: str) -> dict | None:
    match = _NAME_RE.match(name)
    if not match:
        return None
    try:
        created = datetime.strptime(match["stamp"], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return {"world": match["world"], "created": created, "reason": match["reason"],
            "kind": "full" if match["full"] else "world"}


# ── Espacio en disco ─────────────────────────────────────────────────────────

def _human(size: int) -> str:
    """Tamaño sin decimales (así no depende de si el idioma usa coma o punto)."""
    mb = size / (1024 * 1024)
    return f"{round(mb / 1024)} GB" if mb >= 10 * 1024 else f"{max(1, round(mb))} MB"


def _tree_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def disk_info(path: Path | None = None) -> dict:
    path = path or BACKUPS_DIR
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {"free": usage.free, "total": usage.total, "low": usage.free < usage.total * LOW_SPACE_RATIO}


def _check_space(needed: int) -> None:
    """Si la copia no cabe en el disco, se dice antes de empezar (y no a medias)."""
    free = disk_info()["free"]
    if free < needed + _FREE_MARGIN_BYTES:
        raise HTTPException(
            status_code=507,
            detail=f"No hay espacio suficiente para la copia: hacen falta unos {_human(needed + _FREE_MARGIN_BYTES)} "
                   f"y quedan {_human(free)} libres en el disco de las copias.",
        )


# ── Destino secundario ───────────────────────────────────────────────────────

_mirror_state = {"last_ok": None, "last_error": None, "copying": False}
_mirror_lock = threading.Lock()


def mirror_root() -> Path | None:
    from services import automation
    value = (automation.load()["backups"].get("mirror_dir") or "").strip()
    return Path(value) if value else None


def validate_mirror_dir(value: str) -> str:
    """
    Comprueba que la carpeta sirve como destino secundario. No se crea si no
    existe: si es un disco o una carpeta de red sin montar, crearla escribiría
    las copias en el mismo disco de siempre sin que nadie se diera cuenta.
    """
    value = (value or "").strip()
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Escribe la ruta completa de la carpeta (por ejemplo /mnt/nas/copias)")
    if not path.is_dir():
        raise ValueError("Esa carpeta no existe (si es un disco o una carpeta de red, comprueba que está montado)")
    resolved = path.resolve()
    backups = BACKUPS_DIR.resolve()
    if resolved == backups or backups in resolved.parents or resolved in backups.parents:
        raise ValueError("El destino secundario tiene que estar fuera de la carpeta de copias principal")
    probe = resolved / ".mcd-write-test"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"No se puede escribir en esa carpeta: {e.strerror or e}")
    return str(path)


def mirror_status() -> dict:
    root = mirror_root()
    status = {"configured": bool(root), "path": str(root) if root else "", **_mirror_state}
    if root:
        status["available"] = root.is_dir()
        if status["available"]:
            try:
                status["disk"] = disk_info(root)
            except OSError:
                status["disk"] = None
    return status


def _mirror_path(modpack: str, name: str) -> Path | None:
    root = mirror_root()
    return root / modpack / name if root else None


def _copy_to_mirror(modpack: str, name: str) -> bool:
    """Copia una copia al destino secundario si aún no está (True si se ha copiado)."""
    root = mirror_root()
    source = backup_dir(modpack) / name
    if not root or not source.is_file():
        return False
    if not root.is_dir():
        raise OSError(f"el destino secundario no está disponible ({root})")
    target = root / modpack / name
    if target.is_file() and target.stat().st_size == source.stat().st_size:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(source, partial)
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return True


def sync_mirror(modpacks: list | None = None) -> int:
    """Copia al destino secundario las copias que todavía no estén allí."""
    root = mirror_root()
    if not root:
        return 0
    if not BACKUPS_DIR.is_dir():
        return 0
    copied = 0
    with _mirror_lock:
        _mirror_state["copying"] = True
        try:
            for folder in sorted(BACKUPS_DIR.iterdir()):
                if not folder.is_dir() or (modpacks and folder.name not in modpacks):
                    continue
                for path in sorted(folder.glob("*.zip")):
                    if _parse_name(path.name) and _copy_to_mirror(folder.name, path.name):
                        copied += 1
            _mirror_state.update({"last_ok": time.time(), "last_error": None})
        except OSError as e:
            _mirror_state["last_error"] = str(e)
            from services.notify import notify
            notify("backup_failed", f"⚠️ No se han podido llevar las copias al destino secundario: {e}")
        finally:
            _mirror_state["copying"] = False
    return copied


def sync_mirror_in_background(modpacks: list | None = None) -> None:
    if mirror_root():
        threading.Thread(target=sync_mirror, args=(modpacks,), daemon=True, name="copias-destino").start()


def _remove_everywhere(modpack: str, name: str) -> None:
    (backup_dir(modpack) / name).unlink(missing_ok=True)
    mirrored = _mirror_path(modpack, name)
    if mirrored:
        try:
            mirrored.unlink(missing_ok=True)
        except OSError:
            pass  # destino desmontado: se queda allí, no es grave


# ── Lista ────────────────────────────────────────────────────────────────────

def list_backups(modpack: str) -> list:
    found: dict = {}
    mirror = _mirror_path(modpack, "x")
    mirror_folder = mirror.parent if mirror else None
    sources = [(backup_dir(modpack), "local")]
    if mirror_folder:
        sources.append((mirror_folder, "mirror"))
    for folder, where in sources:
        try:
            paths = list(folder.glob("*.zip")) if folder.is_dir() else []
        except OSError:
            paths = []
        for path in paths:
            info = _parse_name(path.name)
            if not info:
                continue
            item = found.get(path.name)
            if not item:
                item = found[path.name] = {
                    "name": path.name,
                    "world": info["world"],
                    "reason": info["reason"],
                    "reason_label": REASONS.get(info["reason"], info["reason"]),
                    "kind": info["kind"],
                    "kind_label": KINDS[info["kind"]],
                    "created": info["created"].isoformat(timespec="seconds"),
                    "size": path.stat().st_size,
                    "local": False,
                    "mirrored": False,
                }
            item["local" if where == "local" else "mirrored"] = True
    items = sorted(found.values(), key=lambda item: item["created"], reverse=True)
    return items


def backup_file(modpack: str, name: str) -> Path:
    """Ruta de una copia (la del disco principal o, si se perdió, la del destino secundario)."""
    if not _parse_name(name):
        raise HTTPException(status_code=400, detail="Nombre de copia no válido")
    path = backup_dir(modpack) / name
    if path.is_file():
        return path
    mirrored = _mirror_path(modpack, name)
    if mirrored and mirrored.is_file():
        return mirrored
    raise HTTPException(status_code=404, detail="La copia no existe")


def last_backup_time(modpack: str, reasons=("auto", "task", "manual")) -> float | None:
    times = [
        datetime.fromisoformat(item["created"]).timestamp()
        for item in list_backups(modpack) if item["reason"] in reasons and item["local"]
    ]
    return max(times) if times else None


# ── Hacer, borrar y restaurar ────────────────────────────────────────────────

def _zip_entries(server_dir: Path, entries: list, target: Path) -> int:
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for entry in entries:
            base = server_dir / entry
            if base.is_file():
                try:
                    zf.write(base, entry)
                    count += 1
                except (FileNotFoundError, PermissionError):
                    pass
                continue
            zf.write(base, entry)
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


def create_backup(modpack: str, reason: str = "manual", keep: int | None = None, full: bool = False) -> dict:
    """
    Hace una copia del mundo activo (o de todo el servidor, con full). Si el
    servidor de ese modpack está encendido, congela el guardado mientras copia
    (ver world_frozen). keep: para automáticas y tareas, cuántas de ese tipo
    conservar.
    """
    from services.server_control import world_frozen

    if reason not in REASONS:
        raise ValueError("Motivo de copia desconocido")
    server_dir = DEFAULT_SERVERS_PATH / modpack
    if not server_dir.is_dir():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    world = active_world(server_dir)
    folders = world_folders(server_dir, world)
    if not folders and not full:
        raise HTTPException(status_code=400, detail=f"Este modpack todavía no tiene mundo («{world}»)")
    entries = full_entries(server_dir) if full else folders

    lock = _modpack_lock(modpack)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya se está haciendo una copia de este modpack")
    try:
        with BusyGuard(f"copia de seguridad de {modpack}"):
            folder = backup_dir(modpack)
            folder.mkdir(parents=True, exist_ok=True)
            # Lo que ocupa sin comprimir: los mundos ya van comprimidos y
            # apenas encogen, así que es una estimación prudente.
            _check_space(sum(_tree_size(server_dir / entry) for entry in entries))
            suffix = "__full" if full else ""
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"{world}__{stamp}__{reason}{suffix}.zip"
            target = folder / name
            if target.exists():
                time.sleep(1)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                name = f"{world}__{stamp}__{reason}{suffix}.zip"
                target = folder / name
            partial = folder / (name + ".part")
            started = time.monotonic()
            try:
                with world_frozen(modpack):
                    files = _zip_entries(server_dir, entries, partial)
                partial.replace(target)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            if keep and reason in ("auto", "task"):
                prune(modpack, keep)
            result = {
                "name": name,
                "kind": "full" if full else "world",
                "files": files,
                "size": target.stat().st_size,
                "seconds": round(time.monotonic() - started, 1),
            }
    finally:
        lock.release()
    sync_mirror_in_background([modpack])
    return result


def prune(modpack: str, keep: int) -> int:
    """Borra las automáticas y de tareas más antiguas por encima de `keep` (también del destino secundario)."""
    removable = [item for item in list_backups(modpack) if item["reason"] in ("auto", "task") and item["local"]]
    removed = 0
    for item in removable[keep:]:
        try:
            _remove_everywhere(modpack, item["name"])
            removed += 1
        except OSError:
            pass
    return removed


def delete_backup(modpack: str, name: str) -> None:
    backup_file(modpack, name)  # 400/404 si no vale o no existe en ningún sitio
    _remove_everywhere(modpack, name)


def _zip_top_entries(zf: zipfile.ZipFile) -> tuple:
    """(carpetas, archivos) de primer nivel de un zip de copia."""
    folders, files = set(), set()
    for entry in zf.namelist():
        parts = entry.replace("\\", "/").split("/")
        if not parts[0]:
            continue
        if len(parts) > 1:
            folders.add(parts[0])
        else:
            files.add(parts[0])
    return folders, files - folders


def _check_entry_names(names: set) -> None:
    for name in names:
        if name in ("..", ".") or (name.startswith(".") and name not in FULL_DOTFILES) or "\\" in name or ":" in name:
            raise HTTPException(status_code=400, detail="La copia no tiene el formato esperado")


def restore_backup(modpack: str, name: str) -> dict:
    """
    Sustituye el mundo (o, si la copia es completa, todo lo que trae: mods,
    configuración...) por el de la copia. Solo con el servidor de ese modpack
    parado. Antes guarda una copia del estado actual (motivo «safety», del
    mismo tipo), por si se restaura la que no era. Lo que una copia completa
    no trae (librerías, logs) se deja como está.
    """
    from services.server_control import running_modpack

    if running_modpack() == modpack:
        raise HTTPException(status_code=409, detail="Para el servidor antes de restaurar una copia")
    path = backup_file(modpack, name)
    full = (_parse_name(name) or {}).get("kind") == "full"
    server_dir = DEFAULT_SERVERS_PATH / modpack

    with zipfile.ZipFile(path) as zf:
        folders, files = _zip_top_entries(zf)
        _check_entry_names(folders | files)
        if full:
            if not folders and not files or "libraries" in folders:
                raise HTTPException(status_code=400, detail="La copia no tiene el formato esperado")
            main_world = None
        else:
            bad = [t for t in folders if t in ("mods", "config", "libraries")]
            if not folders or bad or files:
                raise HTTPException(status_code=400, detail="La copia no tiene el formato esperado")
            main_world = next((t for t in sorted(folders) if not t.endswith(("_nether", "_the_end"))), None)
            if not main_world:
                raise HTTPException(status_code=400, detail="La copia no contiene ningún mundo")

        safety = None
        if full or world_folders(server_dir):
            safety = create_backup(modpack, "safety", full=full)["name"]

        lock = _modpack_lock(modpack)
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Hay una copia de este modpack en curso")
        try:
            with BusyGuard(f"restaurando copia de {modpack}"):
                staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=server_dir))
                try:
                    zf.extractall(staging)
                    for top in sorted(folders | files):
                        current = server_dir / top
                        if current.is_dir() and not current.is_symlink():
                            shutil.rmtree(current)
                        elif current.exists() or current.is_symlink():
                            current.unlink()
                        shutil.move(str(staging / top), str(current))
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
        finally:
            lock.release()

    if main_world and active_world(server_dir) != main_world:
        save_server_property(modpack, "level-name", main_world)
    return {"world": main_world or active_world(server_dir), "kind": "full" if full else "world",
            "safety_backup": safety}
