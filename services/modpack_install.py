"""
services/modpack_install.py - Búsqueda e instalación de MODPACKS completos
(no mods sueltos) desde Modrinth y CurseForge, creando un servidor nuevo.

A diferencia de services/mod_search.py (mods individuales sobre un modpack
YA existente) y services/server_create.py (servidor vacío elegido a mano),
esto resuelve TODO a partir del modpack: modloader + su versión, la lista
completa de mods del pack, y los overrides de configuración — reusando el
bootstrap de server_create.py para que el resultado quede igual de funcional
que un server creado a mano.

Formatos:
- Modrinth: .mrpack = zip con modrinth.index.json (dependencies: loader+mc,
  files: [{path, downloads: [url], env: {client, server}}]) + overrides/ y
  opcionalmente server-overrides/ (pisa a overrides/ para instalaciones de
  servidor). Los downloads YA son URLs directas.
- CurseForge: .zip con manifest.json (minecraft.version, minecraft.modLoaders,
  files: [{projectID, fileID}] — son REFERENCIAS, no URLs; hay que resolverlas
  con la API de CurseForge) + overrides/. Sin campo de client-only por archivo,
  así que todos los mods se instalan en mods/ sin filtrar (igual que hacen los
  demás launchers con este formato).
"""
import io
import json
import time
import shutil
import zipfile
import asyncio
import urllib.request
import urllib.parse
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from app_constants import (
    CURSEFORGE_BULK_FILES_CHUNK, MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS, MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT,
    CURSEFORGE_FILES_PAGE_SIZE, CURSEFORGE_FILES_MAX,
)
from services.mod_search import _http_get_json, download_bytes, _curseforge_headers, _HTTP_TIMEOUT, CURSEFORGE_GAME_ID
from services.modloader import _http_get, _installer_url, LOADER_DISPLAY_NAMES
from services.server_create import validate_new_server_name, _write_run_script, _bootstrap_common_files, _vanilla_server_jar_url
from services.utils import configure_jvm_ram, get_modpacks
from services.modpack import _dedup_fingerprint, detect_modpack_version

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

_MODRINTH_LOADER_DEP_KEYS = {"forge": "forge", "neoforge": "neoforge", "fabric": "fabric-loader", "quilt": "quilt-loader"}


def _safe_join(base: Path, rel_path: str) -> Path:
    """Valida que rel_path no se escape de base — viene de un archivo del modpack, no de código propio."""
    rel_path = rel_path.replace("\\", "/")
    full = base / rel_path
    try:
        full.resolve().relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"Ruta insegura dentro del modpack: {rel_path}")
    return full


async def _run_loader_installer(server_dir: Path, loader_key: str, mc_version: str, loader_version: str, ram_min: str, ram_max: str):
    """
    Descarga y ejecuta el instalador oficial del loader elegido, igual que
    create_server_stream — se repite acá (en vez de compartir función) porque
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


# ── Modrinth ────────────────────────────────────────────────────────────────

def search_modrinth_modpacks(
    query: str, categories: list[str] | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list, int]:
    facets = [["project_type:modpack"]]
    if categories:
        # Un solo grupo con varias categorías = OR, igual que en la búsqueda de mods.
        facets.append([f"categories:{c}" for c in categories])
    params = {"limit": str(limit), "offset": str(offset), "facets": json.dumps(facets)}
    if query:
        params["query"] = query
    else:
        params["index"] = "downloads"
    url = "https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    results = [
        {
            "source": "modrinth", "id": hit.get("project_id"), "slug": hit.get("slug"),
            "title": hit.get("title"), "description": hit.get("description"),
            "icon_url": hit.get("icon_url"), "downloads": hit.get("downloads", 0),
            "author": hit.get("author"),
            "page_url": f"https://modrinth.com/modpack/{hit['slug']}" if hit.get("slug") else None,
        }
        for hit in data.get("hits", [])
    ]
    return results, data.get("total_hits", len(results))


_modrinth_modpack_categories_cache = {"ts": 0.0, "data": []}


def get_modrinth_modpack_categories() -> list:
    """Igual que get_modrinth_categories() de mod_search.py, pero para project_type=modpack."""
    now = time.time()
    if _modrinth_modpack_categories_cache["data"] and now - _modrinth_modpack_categories_cache["ts"] < MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS:
        return _modrinth_modpack_categories_cache["data"]
    data = _http_get_json("https://api.modrinth.com/v2/tag/category")
    names = sorted({c["name"] for c in data if c.get("project_type") == "modpack" and c.get("header") == "categories"})
    result = [{"id": name, "name": name.replace("-", " ").capitalize(), "children": []} for name in names]
    _modrinth_modpack_categories_cache["ts"] = now
    _modrinth_modpack_categories_cache["data"] = result
    return result


def get_modrinth_modpack_versions(project_id: str) -> list:
    url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}/version"
    data = _http_get_json(url)
    versions = []
    for v in data:
        primary_file = next((f for f in v.get("files", []) if f.get("primary")), None)
        if not primary_file and v.get("files"):
            primary_file = v["files"][0]
        if not primary_file or not primary_file.get("filename", "").lower().endswith(".mrpack"):
            continue
        versions.append({
            "source": "modrinth", "version_id": v.get("id"), "version_number": v.get("version_number"),
            "game_versions": v.get("game_versions", []), "loaders": v.get("loaders", []),
            "download_url": primary_file.get("url"), "filename": primary_file.get("filename"),
        })
    return versions


def _get_modrinth_pack_index(project_id: str, version_id: str) -> tuple[dict, zipfile.ZipFile]:
    versions = get_modrinth_modpack_versions(project_id)
    version = next((v for v in versions if v["version_id"] == version_id), None)
    if not version:
        raise ModpackVersionUnavailable("Versión de modpack no encontrada")
    mrpack_bytes = download_bytes(version["download_url"])
    zf = zipfile.ZipFile(io.BytesIO(mrpack_bytes))
    index = json.loads(zf.read("modrinth.index.json"))
    return index, zf


def get_modrinth_modpack_files(project_id: str, version_id: str) -> tuple[list, str | None]:
    """
    Nombres de archivo (mods, sin overrides) + versión de MC de una versión de
    modpack, sin descargar los mods en sí (solo el .mrpack, que es liviano:
    los mods son URLs externas, no van embebidos) — usado por
    find_similar_installed_modpacks() para comprobar si ya está instalado
    ANTES de descargar nada pesado.
    """
    index, _zf = _get_modrinth_pack_index(project_id, version_id)
    deps = index.get("dependencies", {})
    mc_version = deps.get("minecraft")
    files = index.get("files", [])
    filenames = [
        Path(f["path"]).name
        for f in files
        if f.get("path") and (f.get("env") or {}).get("server") != "unsupported"
    ]
    return filenames, mc_version


async def install_modrinth_modpack_stream(project_id: str, version_id: str, server_name: str, ram_min: str, ram_max: str):
    server_dir = DEFAULT_SERVERS_PATH / server_name
    server_dir.mkdir(parents=True)

    try:
        yield {"type": "log", "message": "Descargando índice del modpack..."}
        index, zf = await asyncio.to_thread(_get_modrinth_pack_index, project_id, version_id)

        deps = index.get("dependencies", {})
        mc_version = deps.get("minecraft")
        if not mc_version:
            raise RuntimeError("El modpack no especifica versión de Minecraft")
        loader_key = None
        loader_version = None
        for key, dep_key in _MODRINTH_LOADER_DEP_KEYS.items():
            if dep_key in deps:
                loader_key = key
                loader_version = deps[dep_key]
                break

        async for event in _install_loader_or_vanilla(server_dir, loader_key, mc_version, loader_version, ram_min, ram_max):
            yield event

        files = index.get("files", [])
        server_files = [f for f in files if (f.get("env") or {}).get("server") != "unsupported"]
        skipped = len(files) - len(server_files)
        note = f" ({skipped} solo-cliente omitido(s))" if skipped else ""
        yield {"type": "log", "message": f"Descargando {len(server_files)} archivo(s) del modpack{note}..."}
        for f in server_files:
            rel_path = f.get("path")
            downloads = f.get("downloads") or []
            if not rel_path or not downloads:
                continue
            dest = _safe_join(server_dir, rel_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            file_bytes = await asyncio.to_thread(download_bytes, downloads[0])
            dest.write_bytes(file_bytes)

        yield {"type": "log", "message": "Aplicando overrides de configuración..."}
        await asyncio.to_thread(_extract_overrides, zf, server_dir)
        zf.close()

        await asyncio.to_thread(_bootstrap_common_files, server_dir, mc_version, loader_key, loader_version)
        yield {"type": "done", "success": True, "name": server_name}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}


# ── CurseForge ──────────────────────────────────────────────────────────────

def search_curseforge_modpacks(
    query: str, categories: list[str] | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list, int]:
    headers = _curseforge_headers()
    params = {
        "gameId": str(CURSEFORGE_GAME_ID), "classId": str(CURSEFORGE_MODPACK_CLASS_ID),
        "pageSize": str(limit), "index": str(offset),
        "sortField": "2", "sortOrder": "desc",
    }
    if query:
        params["searchFilter"] = query
    if categories:
        params["categoryIds"] = json.dumps([int(c) for c in categories][:10])
    url = "https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)
    results = []
    for mod in data.get("data", []):
        authors = mod.get("authors") or []
        links = mod.get("links") or {}
        results.append({
            "source": "curseforge", "id": mod.get("id"), "slug": mod.get("slug"),
            "title": mod.get("name"), "description": mod.get("summary"),
            "icon_url": (mod.get("logo") or {}).get("thumbnailUrl"),
            "downloads": mod.get("downloadCount", 0),
            "author": authors[0]["name"] if authors else None,
            "page_url": links.get("websiteUrl"),
        })
    total = (data.get("pagination") or {}).get("totalCount", len(results))
    return results, total


_curseforge_modpack_categories_cache = {"ts": 0.0, "data": []}


def get_curseforge_modpack_categories() -> list:
    """Igual que get_curseforge_categories() de mod_search.py, pero con classId de modpacks (4471)."""
    now = time.time()
    if _curseforge_modpack_categories_cache["data"] and now - _curseforge_modpack_categories_cache["ts"] < MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS:
        return _curseforge_modpack_categories_cache["data"]
    headers = _curseforge_headers()
    params = {"gameId": str(CURSEFORGE_GAME_ID), "classId": str(CURSEFORGE_MODPACK_CLASS_ID)}
    url = "https://api.curseforge.com/v1/categories?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)

    all_cats = [c for c in data.get("data", []) if not c.get("isClass")]
    children_by_parent: dict = {}
    for c in all_cats:
        parent_id = c.get("parentCategoryId")
        if parent_id != CURSEFORGE_MODPACK_CLASS_ID:
            children_by_parent.setdefault(parent_id, []).append(c)

    top_level = [c for c in all_cats if c.get("parentCategoryId") == CURSEFORGE_MODPACK_CLASS_ID]
    result = [
        {
            "id": c["id"],
            "name": c["name"],
            "children": [
                {"id": ch["id"], "name": ch["name"], "children": []}
                for ch in sorted(children_by_parent.get(c["id"], []), key=lambda ch: ch["name"])
            ],
        }
        for c in sorted(top_level, key=lambda c: c["name"])
    ]
    _curseforge_modpack_categories_cache["ts"] = now
    _curseforge_modpack_categories_cache["data"] = result
    return result


def get_curseforge_modpack_versions(mod_id) -> list:
    """
    Trae TODAS las versiones del modpack (no solo las primeras 50): igual que
    get_curseforge_files() en mod_search.py, la API de CurseForge pagina con
    index/pageSize, y sin este loop las builds más antiguas de un modpack con
    muchas versiones quedaban invisibles para siempre (nunca aparecían en el
    desplegable ni se podían resolver por install/check-existing).
    """
    headers = _curseforge_headers()
    raw_files = []
    index = 0
    while index < CURSEFORGE_FILES_MAX:
        params = {"pageSize": str(CURSEFORGE_FILES_PAGE_SIZE), "index": str(index)}
        url = f"https://api.curseforge.com/v1/mods/{mod_id}/files?" + urllib.parse.urlencode(params)
        data = _http_get_json(url, headers)
        page = data.get("data", [])
        raw_files.extend(page)
        if len(page) < CURSEFORGE_FILES_PAGE_SIZE:
            break
        index += CURSEFORGE_FILES_PAGE_SIZE

    versions = []
    for f in raw_files:
        if not f.get("fileName", "").lower().endswith(".zip"):
            continue
        versions.append({
            "source": "curseforge", "version_id": f.get("id"), "version_number": f.get("displayName"),
            "game_versions": f.get("gameVersions", []),
            "download_url": f.get("downloadUrl"), "filename": f.get("fileName"),
        })
    return versions


_CURSEFORGE_BULK_FILES_CHUNK = CURSEFORGE_BULK_FILES_CHUNK


def _resolve_curseforge_file_urls(file_ids: list) -> dict:
    """POST /v1/mods/files (bulk) en vez de un GET por mod: evita cientos de llamadas para packs grandes."""
    headers = _curseforge_headers()
    result = {}
    for i in range(0, len(file_ids), _CURSEFORGE_BULK_FILES_CHUNK):
        chunk = file_ids[i:i + _CURSEFORGE_BULK_FILES_CHUNK]
        body = json.dumps({"fileIds": chunk}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.curseforge.com/v1/mods/files",
            data=body, method="POST",
            headers={**headers, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        for f in data.get("data", []):
            result[f["id"]] = {"downloadUrl": f.get("downloadUrl"), "fileName": f.get("fileName")}
    return result


def _parse_curseforge_loader(mod_loader_id: str) -> tuple:
    """'forge-47.2.0' -> ('forge', '47.2.0'); 'neoforge-20.1.57' -> ('neoforge', '20.1.57')."""
    for prefix, key in (("neoforge-", "neoforge"), ("forge-", "forge"), ("fabric-", "fabric"), ("quilt-", "quilt")):
        if mod_loader_id.startswith(prefix):
            return key, mod_loader_id[len(prefix):]
    return None, None


def _download_curseforge_pack_zip(mod_id, file_id) -> zipfile.ZipFile:
    versions = get_curseforge_modpack_versions(mod_id)
    version = next((v for v in versions if v["version_id"] == file_id), None)
    if not version:
        raise ModpackVersionUnavailable("Versión de modpack no encontrada")
    if not version.get("download_url"):
        raise ModpackDownloadBlocked(
            "El autor de este modpack bloqueó su descarga por terceros en CurseForge — no se puede instalar desde esta app."
        )
    pack_bytes = download_bytes(version["download_url"])
    return zipfile.ZipFile(io.BytesIO(pack_bytes))


def get_curseforge_modpack_files(mod_id, file_id) -> tuple[list, str | None]:
    """
    Igual que get_modrinth_modpack_files() pero para CurseForge: el manifest
    solo trae referencias (projectID/fileID), así que hace falta resolverlas
    a nombres de archivo reales vía la API (sin descargar los jars) — mismo
    endpoint bulk que ya usa _resolve_curseforge_file_urls() al instalar.
    """
    zf = _download_curseforge_pack_zip(mod_id, file_id)
    manifest = json.loads(zf.read("manifest.json"))
    zf.close()
    mc_version = (manifest.get("minecraft") or {}).get("version")
    file_refs = manifest.get("files", [])
    file_ids = [f["fileID"] for f in file_refs if f.get("fileID")]
    resolved = _resolve_curseforge_file_urls(file_ids)
    filenames = [info["fileName"] for info in resolved.values() if info.get("fileName")]
    return filenames, mc_version


async def install_curseforge_modpack_stream(mod_id, file_id, server_name: str, ram_min: str, ram_max: str):
    server_dir = DEFAULT_SERVERS_PATH / server_name
    server_dir.mkdir(parents=True)

    try:
        headers = _curseforge_headers()
        yield {"type": "log", "message": "Descargando manifest del modpack..."}
        zf = await asyncio.to_thread(_download_curseforge_pack_zip, mod_id, file_id)
        manifest = json.loads(zf.read("manifest.json"))

        mc_version = (manifest.get("minecraft") or {}).get("version")
        if not mc_version:
            raise RuntimeError("El modpack no especifica versión de Minecraft")
        mod_loaders = (manifest.get("minecraft") or {}).get("modLoaders") or []
        primary_loader = next((m for m in mod_loaders if m.get("primary")), mod_loaders[0] if mod_loaders else None)
        loader_key, loader_version = _parse_curseforge_loader(primary_loader["id"]) if primary_loader else (None, None)

        async for event in _install_loader_or_vanilla(server_dir, loader_key, mc_version, loader_version, ram_min, ram_max):
            yield event

        file_refs = manifest.get("files", [])
        yield {"type": "log", "message": f"Resolviendo descargas de {len(file_refs)} mod(s)..."}
        file_ids = [f["fileID"] for f in file_refs if f.get("fileID")]
        resolved = await asyncio.to_thread(_resolve_curseforge_file_urls, file_ids)

        mods_dir = server_dir / "mods"
        mods_dir.mkdir(exist_ok=True)
        skipped_no_url = []
        for ref in file_refs:
            info = resolved.get(ref.get("fileID"))
            if not info or not info.get("downloadUrl"):
                skipped_no_url.append(info["fileName"] if info else str(ref.get("fileID")))
                continue
            dest = _safe_join(mods_dir, info["fileName"])
            file_bytes = await asyncio.to_thread(download_bytes, info["downloadUrl"])
            dest.write_bytes(file_bytes)

        if skipped_no_url:
            yield {"type": "log", "message": f"⚠️ {len(skipped_no_url)} mod(s) no se pudieron descargar automáticamente (el autor bloqueó la distribución por terceros): {', '.join(skipped_no_url[:10])}"}

        yield {"type": "log", "message": "Aplicando overrides de configuración..."}
        overrides_folder = manifest.get("overrides", "overrides")
        prefix = overrides_folder + "/"
        for name in zf.namelist():
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            rel = name[len(prefix):]
            if not rel:
                continue
            dest = _safe_join(server_dir, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))
        zf.close()

        await asyncio.to_thread(_bootstrap_common_files, server_dir, mc_version, loader_key, loader_version)
        yield {"type": "done", "success": True, "name": server_name, "skipped": skipped_no_url}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}


# ── Detección de instalación duplicada ────────────────────────────────────────

def _installed_mod_fingerprints(server_name: str) -> set:
    """
    Huellas "sin versión" (ver _dedup_fingerprint) de los mods ya instalados en
    un servidor, incluidos los .disabled — que un mod esté deshabilitado no
    significa que el modpack no sea ese, así que cuenta igual para esta
    comparación.
    """
    mods_dir = DEFAULT_SERVERS_PATH / server_name / "mods"
    if not mods_dir.exists():
        return set()
    fingerprints = set()
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith(".jar") or low.endswith(".zip") or low.endswith(".jar.disabled") or low.endswith(".zip.disabled"):
            fingerprints.add(_dedup_fingerprint(f.name))
    return fingerprints


def find_similar_installed_modpacks(filenames: list, mc_version: str | None) -> list:
    """
    Compara los nombres de archivo de una versión de modpack candidata a
    instalar contra los mods ya instalados en cada servidor existente, usando
    la misma huella "sin versión/loader/MC" que ya usa
    find_possible_duplicate_mods() (services/modpack.py) para detectar
    duplicados dentro de un mismo modpack. Así, actualizar un mod (que cambia
    el número de versión en el nombre del jar) o añadir mods sueltos a mano no
    rompe la detección: solo importa si el "núcleo" del nombre original sigue
    presente.

    El % se calcula sobre el TOTAL de archivos del modpack candidato, no sobre
    lo instalado en el servidor: añadir mods extra a un servidor no baja el
    porcentaje, solo quitar o reemplazar los que vinieron originalmente con
    el pack sí lo hace.

    No requiere descargar ningún mod: filenames viene de
    get_modrinth_modpack_files()/get_curseforge_modpack_files(), que solo leen
    el índice/manifest del pack, y lo instalado se compara por nombre de
    archivo en disco.
    """
    pack_fingerprints = {
        fp for fp in (_dedup_fingerprint(name) for name in filenames if name)
        if len(fp) >= 4
    }
    if not pack_fingerprints:
        return []

    matches = []
    for server_name in get_modpacks():
        if mc_version:
            server_mc = detect_modpack_version(server_name).get("mc_version")
            if server_mc and server_mc != mc_version:
                continue
        installed_fingerprints = _installed_mod_fingerprints(server_name)
        if not installed_fingerprints:
            continue
        matched = pack_fingerprints & installed_fingerprints
        if not matched:
            continue
        overlap_pct = round(len(matched) * 100 / len(pack_fingerprints))
        if overlap_pct >= MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT:
            matches.append({
                "server_name": server_name, "overlap_pct": overlap_pct,
                "matched_count": len(matched), "total_count": len(pack_fingerprints),
            })

    matches.sort(key=lambda m: m["overlap_pct"], reverse=True)
    return matches
