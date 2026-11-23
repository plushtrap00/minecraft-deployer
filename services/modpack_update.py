"""
services/modpack_update.py - Pasar un servidor instalado a otra versión de su modpack.

Origen del modpack: <servidor>/.pack_source.json, que se escribe al instalar
desde Modrinth/CurseForge (record_source) o al vincularlo a mano desde el panel
para los instalados antes de que existiera esto (link_source):
  {"source", "project_id", "title", "version_id", "version_number",
   "mc_version", "loader", "pack_mods": [jars que puso el modpack], ...}

Actualizar (update_stream), con el servidor parado:
1. Copia completa del servidor (services/backups.py), sin ella no se sigue.
2. Instalación limpia de la versión nueva en una carpeta temporal oculta
   (.pack-update-<nombre>), reutilizando el instalador de siempre con la RAM
   actual del servidor.
3. Fusión en el servidor real:
   - mods/: los del modpack nuevo + los que añadiste tú (los que no estaban en
     pack_mods). Si no se sabe qué mods eran del modpack (vinculado a mano),
     solo se quedan los nuevos y se dice cuáles han desaparecido.
   - Los jar y scripts de arranque sueltos: se sustituyen (pueden cambiar la
     versión del loader o de Minecraft).
   - Las carpetas (config/, kubejs/, libraries/...): se escriben los archivos
     que trae el modpack nuevo; lo tuyo que el modpack no trae se queda. En
     libraries/ eso deja también las del loader anterior, así que restaurar la
     copia del paso 1 sigue arrancando.
   - Nunca se tocan el mundo, server.properties, las listas de jugadores, los
     logs ni las copias.
"""
import asyncio
import json
import shutil
import time
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.secure_files import atomic_write_text

SOURCE_FILE = ".pack_source.json"
_updating: set = set()
STAGING_PREFIX = ".pack-update-"

# Lo que es del usuario: no se copia desde la instalación nueva.
KEEP_NAMES = {
    "server.properties", "eula.txt", "ops.json", "whitelist.json", "banned-players.json",
    "banned-ips.json", "usercache.json", "server-icon.png", "logs", "crash-reports",
    "backups", "world", "mods-pendientes.json",
}


def read_source(modpack: str) -> dict | None:
    try:
        data = json.loads((DEFAULT_SERVERS_PATH / modpack / SOURCE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("source") in ("modrinth", "curseforge") else None
    except (OSError, ValueError):
        return None


def _jar_names(mods_dir: Path) -> list:
    if not mods_dir.is_dir():
        return []
    return sorted(f.name for f in mods_dir.iterdir() if f.is_file() and f.name.lower().endswith(".jar"))


def record_source(server_dir: Path, source: str, project_id, version_id, version_number: str | None,
                  mc_version: str | None, loader: str | None, title: str | None = None) -> None:
    """Se llama al terminar de instalar: en ese momento todo mods/ es del modpack."""
    data = {
        "source": source, "project_id": str(project_id), "title": title,
        "version_id": str(version_id), "version_number": version_number,
        "mc_version": mc_version, "loader": loader,
        "pack_mods": _jar_names(server_dir / "mods"), "installed_at": int(time.time()),
    }
    atomic_write_text(server_dir / SOURCE_FILE, json.dumps(data, indent=2, ensure_ascii=False))


def link_source(modpack: str, source: str, project_id: str, title: str | None) -> dict:
    """Para servidores instalados antes de que se guardara el origen."""
    if source not in ("modrinth", "curseforge"):
        raise ValueError("source debe ser 'modrinth' o 'curseforge'")
    if not str(project_id).strip():
        raise ValueError("Falta el modpack")
    data = {"source": source, "project_id": str(project_id).strip(), "title": title,
            "version_id": None, "version_number": None, "pack_mods": None,
            "linked_at": int(time.time())}
    atomic_write_text(DEFAULT_SERVERS_PATH / modpack / SOURCE_FILE, json.dumps(data, indent=2, ensure_ascii=False))
    return data


def unlink_source(modpack: str) -> None:
    (DEFAULT_SERVERS_PATH / modpack / SOURCE_FILE).unlink(missing_ok=True)


def list_versions(modpack: str) -> dict:
    """Versiones publicadas del modpack, de la más nueva a la más vieja, marcando la instalada."""
    from services.modpack_install import get_curseforge_modpack_versions, get_modrinth_modpack_versions
    source = read_source(modpack)
    if not source:
        return {"source": None, "versions": []}
    if source["source"] == "modrinth":
        versions = get_modrinth_modpack_versions(source["project_id"])
    else:
        versions = get_curseforge_modpack_versions(int(source["project_id"]))
        versions.sort(key=lambda v: v["version_id"], reverse=True)
    out = []
    for v in versions:
        out.append({
            "version_id": str(v["version_id"]), "version_number": v.get("version_number"),
            "game_versions": [g for g in v.get("game_versions") or [] if g[:1].isdigit()],
            "downloadable": bool(v.get("download_url")),
            "installed": str(v["version_id"]) == str(source.get("version_id")),
        })
    return {"source": {k: v for k, v in source.items() if k != "pack_mods"}, "versions": out}


def _move(src: Path, dest: Path) -> None:
    if dest.is_dir() and not dest.is_symlink():
        shutil.rmtree(dest)
    elif dest.exists() or dest.is_symlink():
        dest.unlink()
    shutil.move(str(src), str(dest))


def _merge_tree(src: Path, dest: Path) -> int:
    """Copia los archivos de src encima de dest, sin borrar lo que solo está en dest."""
    count = 0
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        target = dest / path.relative_to(src)
        if target.is_dir():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def _mod_id(path: Path) -> str | None:
    from services.mod_metadata import read_mod_metadata
    try:
        return read_mod_metadata(path.read_bytes()).get("mod_id")
    except Exception:  # noqa: BLE001 - un jar raro no debe parar la actualización
        return None


def merge_into(staging: Path, server_dir: Path, pack_mods: list | None, level_name: str = "world") -> dict:
    """Paso 3 del docstring. Devuelve qué mods se han conservado y cuáles han desaparecido."""
    old_mods = server_dir / "mods"
    new_mods = staging / "mods"
    old_names = _jar_names(old_mods)
    new_names = set(_jar_names(new_mods))
    kept, removed = [], []
    for name in old_names:
        if name in new_names:
            continue
        if pack_mods is not None and name not in pack_mods:
            kept.append(name)  # lo añadiste tú
        else:
            removed.append(name)
    # Lo que ha cambiado solo de versión (mismo mod id) no ha «desaparecido».
    replaced = []
    if removed:
        new_ids = {}
        for name in new_names - set(old_names):
            mod_id = _mod_id(new_mods / name)
            if mod_id:
                new_ids[mod_id] = name
        for name in list(removed):
            mod_id = _mod_id(old_mods / name)
            if mod_id and mod_id in new_ids:
                removed.remove(name)
                replaced.append({"old": name, "new": new_ids[mod_id]})
    # Los deshabilitados (.jar.disabled) que no sean del modpack también se quedan.
    disabled = [f.name for f in old_mods.iterdir() if f.is_file() and f.name.endswith(".jar.disabled")] if old_mods.is_dir() else []

    new_mods.mkdir(exist_ok=True)
    for name in kept + disabled:
        if not (new_mods / name).exists() and not (new_mods / name.removesuffix(".disabled")).exists():
            shutil.copy2(old_mods / name, new_mods / name)
    if old_mods.exists():
        shutil.rmtree(old_mods)
    shutil.move(str(new_mods), str(old_mods))

    keep = KEEP_NAMES | {level_name, f"{level_name}_nether", f"{level_name}_the_end"}
    for entry in staging.iterdir():
        if entry.name in keep or entry.name.startswith(".") or entry.name == "mods":
            continue
        target = server_dir / entry.name
        if entry.is_dir() and target.is_dir():
            _merge_tree(entry, target)
        else:
            _move(entry, target)

    # Mods que CurseForge no deja descargar: el aviso de la versión nueva
    # sustituye al de la vieja.
    pending = staging / "mods-pendientes.json"
    if pending.exists():
        _move(pending, server_dir / "mods-pendientes.json")
    return {"kept": kept, "removed": removed, "replaced": replaced, "disabled_kept": disabled}


def _level_name(server_dir: Path) -> str:
    try:
        for line in (server_dir / "server.properties").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("level-name="):
                return line.split("=", 1)[1].strip() or "world"
    except OSError:
        pass
    return "world"


async def update_stream(modpack: str, version_id: str):
    """Eventos como los del instalador: {"type": "log"|"done", ...}."""
    from services import backups
    from services.modpack_install import install_curseforge_modpack_stream, install_modrinth_modpack_stream
    from services.server_control import running_modpack
    from services.utils import detect_jvm_ram

    server_dir = DEFAULT_SERVERS_PATH / modpack
    staging_name = STAGING_PREFIX + modpack
    staging = DEFAULT_SERVERS_PATH / staging_name
    source = read_source(modpack)
    if modpack in _updating:
        yield {"type": "done", "success": False, "detail": "Ya se está actualizando este modpack"}
        return
    _updating.add(modpack)
    try:
        if not source:
            raise ValueError("Este servidor no está vinculado a ningún modpack")
        if running_modpack() == modpack:
            raise ValueError("Para el servidor antes de actualizar el modpack")
        if str(version_id) == str(source.get("version_id")):
            raise ValueError("Esa versión ya es la instalada")

        yield {"type": "log", "message": "Haciendo una copia completa del servidor por si hay que volver atrás..."}
        backup = await asyncio.to_thread(backups.create_backup, modpack, "packupdate", None, True)
        yield {"type": "log", "message": f"✅ Copia hecha: {backup.get('name')}"}

        ram = await asyncio.to_thread(detect_jvm_ram, server_dir)
        ram_min, ram_max = ram.get("ram_min") or "2G", ram.get("ram_max") or "4G"
        if staging.exists():
            shutil.rmtree(staging)
        if source["source"] == "modrinth":
            installer = install_modrinth_modpack_stream(source["project_id"], str(version_id), staging_name, ram_min, ram_max)
        else:
            installer = install_curseforge_modpack_stream(int(source["project_id"]), int(version_id), staging_name, ram_min, ram_max)
        installed = None
        async for event in installer:
            if event.get("type") == "done":
                installed = event
            else:
                yield event
        if not installed or not installed.get("success"):
            raise RuntimeError((installed or {}).get("detail") or "No se pudo descargar la versión nueva")

        yield {"type": "log", "message": "Pasando la versión nueva al servidor (el mundo no se toca)..."}
        result = await asyncio.to_thread(merge_into, staging, server_dir, source.get("pack_mods"), _level_name(server_dir))
        new_source = read_source(staging_name) or {}
        new_source["title"] = new_source.get("title") or source.get("title")
        if source.get("pack_mods") is None:
            new_source["note"] = "vinculado a mano"
        atomic_write_text(server_dir / SOURCE_FILE, json.dumps(new_source, indent=2, ensure_ascii=False))
        yield {"type": "done", "success": True, "name": modpack, "backup": backup.get("name"),
               "version_number": new_source.get("version_number"), "mc_version": new_source.get("mc_version"),
               "previous_mc": source.get("mc_version"), **result}
    except Exception as e:  # noqa: BLE001 - se enseña en el panel
        yield {"type": "done", "success": False, "detail": str(e)}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        _updating.discard(modpack)


# ── Tarea en segundo plano ────────────────────────────────────────────────────
# La actualización no puede depender de que el navegador siga conectado: si el
# stream se cortara a mitad (pestaña cerrada, wifi), se cancelaría con el
# servidor a medio fusionar. Corre como tarea propia y el stream solo la sigue.
_tasks: dict = {}


def start_update(modpack: str, version_id: str) -> dict:
    """Llamar desde el bucle de asyncio. Si ya hay una en marcha, devuelve esa."""
    job = _tasks.get(modpack)
    if job and not job["finished"]:
        return job
    job = {"events": [], "finished": False, "version_id": str(version_id)}

    async def run():
        from services.busy import BusyGuard
        try:
            with BusyGuard(f"actualizando el modpack de {modpack}"):
                async for event in update_stream(modpack, version_id):
                    job["events"].append(event)
        except Exception as e:  # noqa: BLE001
            job["events"].append({"type": "done", "success": False, "detail": str(e)})
        finally:
            job["finished"] = True

    job["task"] = asyncio.get_running_loop().create_task(run())
    _tasks[modpack] = job
    return job


def running_update(modpack: str) -> dict | None:
    job = _tasks.get(modpack)
    return job if job and not job["finished"] else None


async def follow(job: dict):
    """Los eventos de la tarea según van llegando (desde el principio)."""
    sent = 0
    while True:
        events = job["events"]
        while sent < len(events):
            yield events[sent]
            sent += 1
        if job["finished"] and sent >= len(job["events"]):
            return
        await asyncio.sleep(0.3)
