"""
services/pack_install_common.py - Piezas comunes a la instalación de modpacks
de Modrinth y de CurseForge (services/modpack_install.py): errores, rutas
seguras dentro del pack, instalar el modloader, aplicar la RAM, copiar los
overrides, guardar el logo y la caché de «qué trae este modpack».
"""
import asyncio
import re
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path
from services.mod_checks import _KNOWN_CLIENT_ONLY_FINGERPRINTS, _dedup_fingerprint
from services.mod_search import _curseforge_headers, _http_get_json
from services.modloader import LOADER_DISPLAY_NAMES, _http_get, _installer_url
from services.server_create import _vanilla_server_jar_url, _write_run_script
from services.utils import configure_jvm_ram
from services.visuals import save_pack_icon


CURSEFORGE_MODPACK_CLASS_ID = 4471


class ModpackVersionUnavailable(RuntimeError):
    """La versión pedida no aparece en la lista de versiones del modpack (ID inválido/desactualizado)."""


class ModpackDownloadBlocked(RuntimeError):
    """
    El autor bloqueó la descarga por terceros para esta versión concreta (algo
    habitual en CurseForge). A diferencia de un mod suelto bloqueado dentro de
    un modpack (que solo se salta y el resto se instala igual), esto bloquea
    el PROPIO archivo del modpack: instalar desde esta app fallará siempre,
    así que quien llame a esto debe tratarlo como "no instalable", no como un
    simple aviso.
    """


def _safe_join(base: Path, rel_path: str) -> Path:
    """Valida que rel_path no se escape de base — viene de un archivo del modpack, no de código propio."""
    rel_path = rel_path.replace("\\", "/")
    full = base / rel_path
    try:
        full.resolve().relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"Ruta insegura dentro del modpack: {rel_path}")
    return full


def _known_client_only_reason(filename: str) -> str | None:
    """
    Devuelve el motivo si `filename` corresponde a un mod conocido que
    revienta un servidor dedicado (sodium, iris y demás confirmados mod a mod
    en _KNOWN_CLIENT_ONLY_MOD_IDS, services/mod_checks.py), o None si no calza
    con ninguno.
    """
    return _KNOWN_CLIENT_ONLY_FINGERPRINTS.get(_dedup_fingerprint(filename))


async def _run_loader_installer(server_dir: Path, loader_key: str, mc_version: str, loader_version: str, ram_min: str, ram_max: str):
    """
    Descarga y ejecuta el instalador oficial del loader elegido, igual que
    create_server_stream — se repite aquí (en vez de compartir función) porque
    ese generador hace su PROPIO bootstrap final, que en este flujo llega
    después de instalar los archivos del modpack, no antes.
    """
    url, install_args = await asyncio.to_thread(_installer_url, loader_key, mc_version, loader_version)
    installer_path = server_dir / "installer.jar"
    jar_bytes = await asyncio.to_thread(_http_get, url)
    installer_path.write_bytes(jar_bytes)

    yield {"type": "log", "message": "Ejecutando instalador..."}
    proc = await asyncio.create_subprocess_exec(
        "java", "-jar", str(installer_path.resolve()), *install_args,
        cwd=str(server_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if not line:
            continue
        if len(line) > 500:
            line = line[:500] + "… [línea truncada]"
        yield {"type": "log", "message": line}
    returncode = await proc.wait()
    installer_path.unlink(missing_ok=True)
    if returncode != 0:
        raise RuntimeError(f"El instalador terminó con código de salida {returncode}")

    if loader_key in ("fabric", "quilt"):
        jar_name = "fabric-server-launch.jar" if loader_key == "fabric" else "quilt-server-launch.jar"
        if not (server_dir / jar_name).exists():
            raise RuntimeError(f"El instalador no generó {jar_name} como se esperaba")
        await asyncio.to_thread(_write_run_script, server_dir, jar_name, ram_min, ram_max)
    else:
        await asyncio.to_thread(configure_jvm_ram, server_dir, ram_min, ram_max)


async def _install_loader_or_vanilla(server_dir: Path, loader_key: str | None, mc_version: str, loader_version: str | None, ram_min: str, ram_max: str):
    if loader_key:
        yield {"type": "log", "message": f"Instalando {LOADER_DISPLAY_NAMES.get(loader_key, loader_key)} {loader_version}..."}
        async for event in _run_loader_installer(server_dir, loader_key, mc_version, loader_version, ram_min, ram_max):
            yield event
    else:
        yield {"type": "log", "message": f"Descargando server.jar vanilla {mc_version}..."}
        jar_url = await asyncio.to_thread(_vanilla_server_jar_url, mc_version)
        jar_bytes = await asyncio.to_thread(_http_get, jar_url)
        (server_dir / "server.jar").write_bytes(jar_bytes)
        await asyncio.to_thread(_write_run_script, server_dir, "server.jar", ram_min, ram_max)


async def _reapply_ram(server_dir: Path, ram_min: str, ram_max: str):
    """
    La RAM elegida se escribe al instalar el loader, pero los archivos del
    modpack se copian DESPUÉS (overrides, o el Server Pack entero) y muchos
    traen su propio user_jvm_args.txt o variables.txt, que pisaba lo que se
    acababa de configurar. Se vuelve a aplicar al final.
    """
    if not ram_min or not ram_max:
        return
    source = await asyncio.to_thread(configure_jvm_ram, server_dir, ram_min, ram_max)
    if source:
        yield {"type": "log", "message": f"RAM aplicada en {source}: mínimo {ram_min}, máximo {ram_max}."}


def _extract_overrides(zf: zipfile.ZipFile, server_dir: Path) -> None:
    """overrides/ primero, server-overrides/ después (pisa lo anterior) — mismo orden que el spec de Modrinth."""
    for overrides_dir in ("overrides", "server-overrides"):
        prefix = overrides_dir + "/"
        for name in zf.namelist():
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            rel = name[len(prefix):]
            if not rel:
                continue
            dest = _safe_join(server_dir, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))


# ── Contenido de un modpack (vista previa antes de instalar) ──────────────────
# La comprobación de duplicados y el botón «Ver mods» piden lo mismo casi a la
# vez: se guarda el resultado unos minutos (con un candado por clave) para que
# el pack solo se descargue una vez. Lo guardado es la lista ya resuelta, no
# el zip, así que ocupa poco aunque el pack pese cientos de MB.
_PACK_CONTENTS_TTL_SECONDS = 600
_PACK_CONTENTS_MAX = 16
_pack_contents_cache: dict = {}
_pack_contents_locks: dict = {}
_pack_contents_guard = threading.Lock()


def _cached_pack_contents(key: tuple, compute):
    with _pack_contents_guard:
        key_lock = _pack_contents_locks.setdefault(key, threading.Lock())
    with key_lock:
        hit = _pack_contents_cache.get(key)
        if hit and time.time() - hit[0] < _PACK_CONTENTS_TTL_SECONDS:
            return hit[1]
        result = compute()
        with _pack_contents_guard:
            if len(_pack_contents_cache) >= _PACK_CONTENTS_MAX:
                oldest = min(_pack_contents_cache, key=lambda k: _pack_contents_cache[k][0])
                _pack_contents_cache.pop(oldest, None)
                _pack_contents_locks.pop(oldest, None)
            _pack_contents_cache[key] = (time.time(), result)
        return result


_PATH_KINDS = {"mods": "mod", "resourcepacks": "resourcepack", "shaderpacks": "shader", "datapacks": "datapack"}


def _kind_from_path(rel_path: str) -> str:
    return _PATH_KINDS.get(rel_path.split("/", 1)[0], "other")


def _display_name_from_filename(filename: str) -> str:
    return re.sub(r"\.(jar|zip|disabled)$", "", filename, flags=re.IGNORECASE)


def _embedded_jar_entries(zf: zipfile.ZipFile, override_dirs: tuple) -> list:
    """Jars metidos dentro del propio pack (overrides/mods/...), que no son referencias a descargar."""
    entries = []
    seen = set()
    for overrides_dir in override_dirs:
        prefix = overrides_dir + "/mods/"
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(prefix) or not name.lower().endswith(".jar"):
                continue
            filename = name[len(prefix):]
            if "/" in filename or filename in seen:
                continue
            seen.add(filename)
            entries.append({
                "name": _display_name_from_filename(filename), "filename": filename,
                "icon_url": None, "page_url": None, "description": None,
                "kind": "mod", "status": "install", "embedded": True, "size": info.file_size,
            })
    return entries


def _sort_pack_entries(entries: list) -> list:
    order = {"install": 0, "blocked": 1, "client_only": 2, "not_in_server_pack": 2, "known_bad": 2, "not_needed": 3, "unresolved": 4}
    return sorted(entries, key=lambda e: (order.get(e["status"], 9), (e["name"] or "").lower()))


def _store_modpack_logo(server_dir: Path, source: str, project_id) -> None:
    """Guarda el logo del modpack para el panel. Sin red o sin logo no pasa nada."""
    try:
        if source == "modrinth":
            project = _http_get_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(str(project_id))}")
            url = project.get("icon_url")
        else:
            mod = _http_get_json(f"https://api.curseforge.com/v1/mods/{int(project_id)}", headers=_curseforge_headers())
            url = ((mod.get("data") or {}).get("logo") or {}).get("thumbnailUrl")
    except Exception:
        return
    save_pack_icon(server_dir, url)
