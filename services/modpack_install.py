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
import re
import shutil
import struct
import zipfile
import threading
import asyncio
import urllib.request
import urllib.parse
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from app_constants import (
    CURSEFORGE_BULK_FILES_CHUNK, MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS, MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT,
    CURSEFORGE_FILES_PAGE_SIZE, CURSEFORGE_FILES_MAX,
)
from services.mod_search import (
    _http_get_json, download_bytes, _curseforge_headers, _HTTP_TIMEOUT, CURSEFORGE_GAME_ID,
    MODRINTH_LOADERS, CURSEFORGE_LOADER_TYPES, CURSEFORGE_MOD_CLASS_ID,
    modrinth_result_extras, curseforge_result_extras,
)
from services.modloader import _http_get, _installer_url, LOADER_DISPLAY_NAMES
from services.server_create import validate_new_server_name, _write_run_script, _bootstrap_common_files, _vanilla_server_jar_url
from services.utils import configure_jvm_ram, get_modpacks
from services.visuals import save_pack_icon
from services.modpack import detect_modpack_version
from services.mod_checks import _dedup_fingerprint, _KNOWN_CLIENT_ONLY_FINGERPRINTS
from services.pending_mods import write_pending_mods

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


# ── Modrinth ────────────────────────────────────────────────────────────────

def search_modrinth_modpacks(
    query: str, categories: list[str] | None = None, limit: int = 20, offset: int = 0,
    mc_version: str | None = None, loader: str | None = None,
) -> tuple[list, int]:
    facets = [["project_type:modpack"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader in MODRINTH_LOADERS:
        # Modrinth trata los modloaders como una categoría más (mismo facet que
        # ya usa search_modrinth() en mod_search.py para mods sueltos) — grupo
        # propio, no mezclado con las categorías de género, para que sea un AND
        # con ellas en vez de un OR.
        facets.append([f"categories:{loader}"])
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
            **modrinth_result_extras(hit),
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


_MODRINTH_CDN_PROJECT_RE = re.compile(r"cdn\.modrinth\.com/data/([A-Za-z0-9]+)/")
_PATH_KINDS = {"mods": "mod", "resourcepacks": "resourcepack", "shaderpacks": "shader", "datapacks": "datapack"}
_MODRINTH_PROJECTS_CHUNK = 100


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


def _resolve_modrinth_projects(project_ids: list) -> dict:
    """GET /v2/projects?ids=[...] por tandas -> {project_id: proyecto}. Sin red, devuelve lo que haya podido."""
    result = {}
    for i in range(0, len(project_ids), _MODRINTH_PROJECTS_CHUNK):
        chunk = project_ids[i:i + _MODRINTH_PROJECTS_CHUNK]
        url = "https://api.modrinth.com/v2/projects?ids=" + urllib.parse.quote(json.dumps(chunk))
        try:
            data = _http_get_json(url)
        except Exception:
            continue
        for p in data or []:
            if p.get("id"):
                result[p["id"]] = p
    return result


def _sort_pack_entries(entries: list) -> list:
    order = {"install": 0, "blocked": 1, "client_only": 2, "not_in_server_pack": 2, "known_bad": 2, "not_needed": 3, "unresolved": 4}
    return sorted(entries, key=lambda e: (order.get(e["status"], 9), (e["name"] or "").lower()))


def get_modrinth_modpack_mods(project_id: str, version_id: str) -> dict:
    """
    Lo que traería una versión de modpack de Modrinth, sin descargar ningún
    mod: el .mrpack solo trae URLs. Cada entrada lleva `status` con lo que
    haría la instalación con ella (ver install_modrinth_modpack_stream):
    install, client_only (env.server = unsupported) o known_bad
    (_KNOWN_CLIENT_ONLY_MOD_IDS). `filenames` mantiene el criterio de
    siempre para find_similar_installed_modpacks().
    """
    def compute():
        index, zf = _get_modrinth_pack_index(project_id, version_id)
        deps = index.get("dependencies", {})
        files = [f for f in index.get("files", []) if f.get("path")]

        project_ids = []
        for f in files:
            match = _MODRINTH_CDN_PROJECT_RE.search(" ".join(f.get("downloads") or []))
            f["_project_id"] = match.group(1) if match else None
            if f["_project_id"] and f["_project_id"] not in project_ids:
                project_ids.append(f["_project_id"])
        projects = _resolve_modrinth_projects(project_ids) if project_ids else {}

        entries = []
        for f in files:
            rel_path = f["path"]
            filename = Path(rel_path).name
            kind = _kind_from_path(rel_path)
            if (f.get("env") or {}).get("server") == "unsupported":
                status = "client_only"
            elif kind == "mod" and _known_client_only_reason(filename):
                status = "known_bad"
            else:
                status = "install"
            project = projects.get(f["_project_id"]) or {}
            page_url = None
            if project.get("slug"):
                page_url = f"https://modrinth.com/{project.get('project_type') or 'mod'}/{project['slug']}"
            entries.append({
                "name": project.get("title") or _display_name_from_filename(filename),
                "filename": filename, "icon_url": project.get("icon_url"), "page_url": page_url,
                "description": project.get("description"), "kind": kind, "status": status,
                "embedded": False, "size": f.get("fileSize"),
            })
        entries.extend(_embedded_jar_entries(zf, ("overrides", "server-overrides")))
        zf.close()
        return {
            "mods": _sort_pack_entries(entries),
            "filenames": [Path(f["path"]).name for f in files if (f.get("env") or {}).get("server") != "unsupported"],
            "mc_version": deps.get("minecraft"),
            "server_pack": None,
        }

    return _cached_pack_contents(("modrinth", str(project_id), str(version_id)), compute)


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
        skipped_known_bad = []
        for f in server_files:
            rel_path = f.get("path")
            downloads = f.get("downloads") or []
            if not rel_path or not downloads:
                continue
            # El campo "env" de Modrinth ya filtró lo declarado client-only,
            # pero algunos mods (sodium/iris y demás de
            # _KNOWN_CLIENT_ONLY_MOD_IDS) declaran server-compatible de forma
            # incorrecta — se comprueban aparte solo dentro de mods/, para no
            # marcar por casualidad un resourcepack/shaderpack con un nombre
            # parecido.
            if rel_path.startswith("mods/"):
                bad_reason = _known_client_only_reason(Path(rel_path).name)
                if bad_reason:
                    skipped_known_bad.append(Path(rel_path).name)
                    continue
            dest = _safe_join(server_dir, rel_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            file_bytes = await asyncio.to_thread(download_bytes, downloads[0])
            dest.write_bytes(file_bytes)

        if skipped_known_bad:
            yield {"type": "log", "message": f"🚫 {len(skipped_known_bad)} mod(s) conocidos por reventar un servidor dedicado no se instalan: {', '.join(skipped_known_bad)}"}

        yield {"type": "log", "message": "Aplicando overrides de configuración..."}
        await asyncio.to_thread(_extract_overrides, zf, server_dir)
        zf.close()
        async for event in _reapply_ram(server_dir, ram_min, ram_max):
            yield event

        await asyncio.to_thread(_bootstrap_common_files, server_dir, mc_version, loader_key, loader_version)
        await asyncio.to_thread(_store_modpack_logo, server_dir, "modrinth", project_id)
        yield {"type": "done", "success": True, "name": server_name}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}


# ── CurseForge ──────────────────────────────────────────────────────────────

def search_curseforge_modpacks(
    query: str, categories: list[str] | None = None, limit: int = 20, offset: int = 0,
    mc_version: str | None = None, loader: str | None = None,
) -> tuple[list, int]:
    headers = _curseforge_headers()
    params = {
        "gameId": str(CURSEFORGE_GAME_ID), "classId": str(CURSEFORGE_MODPACK_CLASS_ID),
        "pageSize": str(limit), "index": str(offset),
        "sortField": "2", "sortOrder": "desc",
    }
    if query:
        params["searchFilter"] = query
    if mc_version:
        params["gameVersion"] = mc_version
    if loader in CURSEFORGE_LOADER_TYPES:
        params["modLoaderType"] = str(CURSEFORGE_LOADER_TYPES[loader])
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
            **curseforge_result_extras(mod),
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
            # ID del archivo "Server Files" asociado a esta build, si el autor
            # publicó uno (null si no) — ver install_curseforge_modpack_stream:
            # cuando existe, se prefiere sobre resolver/descargar cada mod
            # suelto porque ya viene listo para arrancar.
            "server_pack_file_id": f.get("serverPackFileId"),
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
            result[f["id"]] = {"downloadUrl": f.get("downloadUrl"), "fileName": f.get("fileName"), "fileLength": f.get("fileLength")}
    return result


def _resolve_curseforge_project_classes(project_ids: list) -> dict:
    """
    POST /v1/mods (bulk) -> {projectID: classId}. El manifest.json de un
    modpack de CurseForge mezcla en "files" referencias a mods (classId=6,
    CURSEFORGE_MOD_CLASS_ID) CON resource packs, shaders y cualquier otro tipo
    de proyecto, sin distinguirlos — esto es lo único que permite separarlos
    antes de decidir qué va a mods/ y qué no hace falta en absoluto para un
    servidor (un resource pack o shader no lo usa el server, son 100% del
    lado cliente).
    """
    return {pid: project.get("classId") for pid, project in _resolve_curseforge_projects(project_ids).items()}


def _resolve_curseforge_projects(project_ids: list) -> dict:
    """POST /v1/mods (bulk) -> {projectID: proyecto completo} (nombre, logo, enlaces, classId...)."""
    headers = _curseforge_headers()
    result = {}
    for i in range(0, len(project_ids), _CURSEFORGE_BULK_FILES_CHUNK):
        chunk = project_ids[i:i + _CURSEFORGE_BULK_FILES_CHUNK]
        body = json.dumps({"modIds": chunk}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.curseforge.com/v1/mods",
            data=body, method="POST",
            headers={**headers, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        for m in data.get("data", []):
            result[m["id"]] = m
    return result


def _parse_curseforge_loader(mod_loader_id: str) -> tuple:
    """'forge-47.2.0' -> ('forge', '47.2.0'); 'neoforge-20.1.57' -> ('neoforge', '20.1.57')."""
    for prefix, key in (("neoforge-", "neoforge"), ("forge-", "forge"), ("fabric-", "fabric"), ("quilt-", "quilt")):
        if mod_loader_id.startswith(prefix):
            return key, mod_loader_id[len(prefix):]
    return None, None


def _download_curseforge_pack_zip(mod_id, file_id) -> tuple:
    """Devuelve (ZipFile del archivo "Client", dict de la versión) — la versión trae server_pack_file_id si esta build tiene Server Pack asociado."""
    versions = get_curseforge_modpack_versions(mod_id)
    version = next((v for v in versions if v["version_id"] == file_id), None)
    if not version:
        raise ModpackVersionUnavailable("Versión de modpack no encontrada")
    if not version.get("download_url"):
        raise ModpackDownloadBlocked(
            "El autor de este modpack bloqueó su descarga por terceros en CurseForge — no se puede instalar desde esta app."
        )
    pack_bytes = download_bytes(version["download_url"])
    return zipfile.ZipFile(io.BytesIO(pack_bytes)), version


def _resolve_curseforge_server_pack(server_pack_file_id: int) -> dict | None:
    """
    Resuelve el archivo "Server Files" asociado a una versión de modpack
    (server_pack_file_id, de get_curseforge_modpack_versions) a su URL de
    descarga real. Devuelve None si el autor también bloqueó ESTE archivo
    para descarga por terceros (es un archivo aparte del "Client", puede
    estar bloqueado aunque el otro no lo esté, o viceversa) — en ese caso
    quien llame debe caer al método mod-por-mod, igual que si no existiera.
    """
    resolved = _resolve_curseforge_file_urls([server_pack_file_id])
    info = resolved.get(server_pack_file_id)
    if not info or not info.get("downloadUrl"):
        return None
    return {"download_url": info["downloadUrl"], "filename": info.get("fileName") or "server-files.zip"}


_REMOTE_ZIP_TAIL_BYTES = 65536 + 22
_REMOTE_ZIP_MAX_DIRECTORY_BYTES = 32 * 1024 * 1024


def _http_get_range(url: str, range_header: str) -> tuple[bytes, int]:
    """GET con Range -> (bytes, tamaño total del archivo). Error si el servidor no admite rangos (no baja el archivo entero)."""
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError("solo http/https")
    req = urllib.request.Request(url, headers={"User-Agent": "minecraft-deployer/1.0", "Range": range_header})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        content_range = resp.headers.get("Content-Range") or ""
        if resp.status != 206 or "/" not in content_range:
            raise ValueError("el servidor no admite descargas parciales")
        total = int(content_range.rsplit("/", 1)[1])
        return resp.read(_REMOTE_ZIP_MAX_DIRECTORY_BYTES + _REMOTE_ZIP_TAIL_BYTES), total


def _list_remote_zip(url: str) -> list | None:
    """
    [(ruta, tamaño)] de un zip remoto leyendo solo su directorio central (el
    final del archivo, unos KB) con peticiones Range, en vez de bajar el zip
    entero — un Server Pack puede pesar cientos de MB. None si no se puede
    (el servidor no admite rangos, zip raro...): quien llama tira de plan B.
    """
    try:
        tail, total = _http_get_range(url, f"bytes=-{_REMOTE_ZIP_TAIL_BYTES}")
        tail_start = total - len(tail)
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0 or len(tail) - eocd < 22:
            return None
        cd_size, cd_offset = struct.unpack("<II", tail[eocd + 12:eocd + 20])
        if cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
            # ZIP64: el localizador va justo antes y apunta al registro EOCD64.
            loc = eocd - 20
            if loc < 0 or tail[loc:loc + 4] != b"PK\x06\x07":
                return None
            (eocd64_offset,) = struct.unpack("<Q", tail[loc + 8:loc + 16])
            if eocd64_offset >= tail_start:
                rec = tail[eocd64_offset - tail_start:eocd64_offset - tail_start + 56]
            else:
                rec, _ = _http_get_range(url, f"bytes={eocd64_offset}-{eocd64_offset + 55}")
            if rec[:4] != b"PK\x06\x06":
                return None
            cd_size, cd_offset = struct.unpack("<QQ", rec[40:56])
        if cd_size > _REMOTE_ZIP_MAX_DIRECTORY_BYTES:
            return None
        if cd_offset >= tail_start:
            directory = tail[cd_offset - tail_start:cd_offset - tail_start + cd_size]
        else:
            directory, _ = _http_get_range(url, f"bytes={cd_offset}-{cd_offset + cd_size - 1}")
        entries = []
        pos = 0
        while pos + 46 <= len(directory) and directory[pos:pos + 4] == b"PK\x01\x02":
            flags = struct.unpack("<H", directory[pos + 8:pos + 10])[0]
            size = struct.unpack("<I", directory[pos + 24:pos + 28])[0]
            name_len, extra_len, comment_len = struct.unpack("<HHH", directory[pos + 28:pos + 34])
            raw_name = directory[pos + 46:pos + 46 + name_len]
            entries.append((raw_name.decode("utf-8" if flags & 0x800 else "cp437", errors="replace"), size))
            pos += 46 + name_len + extra_len + comment_len
        return entries or None
    except Exception:
        return None


_CURSEFORGE_CLASS_KINDS = {CURSEFORGE_MOD_CLASS_ID: "mod", 12: "resourcepack", 6552: "shader", 6945: "datapack"}


def _server_pack_entries(server_jars: list, manifest_entries: list) -> list:
    """
    Lista según el Server Pack (lo que de verdad acaba en mods/), con nombre,
    icono y enlace sacados del manifest cuando el jar calza (por nombre exacto
    o por huella, por si el Server Pack trae otra versión del mismo mod). Los
    mods del manifest que no están en el Server Pack son los que el autor dejó
    fuera del servidor (casi siempre, solo de cliente).
    """
    manifest_mods = [e for e in manifest_entries if e["kind"] == "mod" and e["filename"]]
    by_name = {e["filename"]: e for e in manifest_mods}
    by_fingerprint = {}
    for e in manifest_mods:
        by_fingerprint.setdefault(_dedup_fingerprint(e["filename"]), e)

    matched = set()
    entries = []
    for filename, size in server_jars:
        source = by_name.get(filename) or by_fingerprint.get(_dedup_fingerprint(filename))
        if source:
            matched.add(id(source))
        entries.append({
            "name": source["name"] if source else _display_name_from_filename(filename),
            "filename": filename,
            "icon_url": source["icon_url"] if source else None,
            "page_url": source["page_url"] if source else None,
            "description": source["description"] if source else None,
            "kind": "mod",
            "status": "known_bad" if _known_client_only_reason(filename) else "install",
            "embedded": False, "size": size,
        })
    for e in manifest_entries:
        if e["kind"] == "mod" and e["filename"] and id(e) not in matched:
            entries.append({**e, "status": "not_in_server_pack"})
        elif e["kind"] != "mod":
            entries.append(e)
    return entries


def get_curseforge_modpack_mods(mod_id, file_id) -> dict:
    """
    Como get_modrinth_modpack_mods() pero para CurseForge, con el mismo
    criterio que install_curseforge_modpack_stream():

    - Si la build trae «Server Files» descargables, la instalación usa ese
      paquete, así que la lista sale de él (leyendo solo su índice, ver
      _list_remote_zip): server_pack = "exact". Si no se puede leer su
      índice, se marca "approx" y lo bloqueado para terceros no se marca
      como «a mano» (el Server Pack es otro archivo y ya lo incluye).
    - Si no (no hay Server Pack o también está bloqueado), mod a mod: lo que
      no es un mod no hace falta (not_needed), los conocidos por romper el
      servidor se saltan (known_bad) y los que el autor no deja bajar a
      terceros quedan para subirlos a mano (blocked). server_pack = None.
    """
    def compute():
        zf, version = _download_curseforge_pack_zip(mod_id, file_id)
        manifest = json.loads(zf.read("manifest.json"))
        refs = [f for f in manifest.get("files", []) if f.get("fileID")]
        resolved = _resolve_curseforge_file_urls([f["fileID"] for f in refs])
        project_ids = list({f["projectID"] for f in refs if f.get("projectID")})
        projects = _resolve_curseforge_projects(project_ids) if project_ids else {}

        entries = []
        for ref in refs:
            info = resolved.get(ref["fileID"]) or {}
            project = projects.get(ref.get("projectID")) or {}
            filename = info.get("fileName")
            class_id = project.get("classId", CURSEFORGE_MOD_CLASS_ID)
            kind = _CURSEFORGE_CLASS_KINDS.get(class_id, "other")
            if class_id != CURSEFORGE_MOD_CLASS_ID:
                status = "not_needed"
            elif filename and _known_client_only_reason(filename):
                status = "known_bad"
            elif not info:
                status = "unresolved"
            elif not info.get("downloadUrl"):
                status = "blocked"
            else:
                status = "install"
            entries.append({
                "name": project.get("name") or (_display_name_from_filename(filename) if filename else f"Archivo {ref['fileID']}"),
                "filename": filename, "icon_url": (project.get("logo") or {}).get("thumbnailUrl"),
                "page_url": (project.get("links") or {}).get("websiteUrl"), "description": project.get("summary"),
                "kind": kind, "status": status, "embedded": False, "size": info.get("fileLength"),
            })
        entries.extend(_embedded_jar_entries(zf, (manifest.get("overrides", "overrides"),)))
        zf.close()

        server_pack = None
        server_pack_info = None
        if version.get("server_pack_file_id"):
            try:
                server_pack_info = _resolve_curseforge_server_pack(version["server_pack_file_id"])
            except Exception:
                server_pack_info = None
        if server_pack_info:
            listing = _list_remote_zip(server_pack_info["download_url"])
            server_jars = [
                (name[len("mods/"):], size) for name, size in (listing or [])
                if name.startswith("mods/") and name.lower().endswith(".jar") and "/" not in name[len("mods/"):]
            ]
            if server_jars:
                entries = _server_pack_entries(server_jars, entries)
                server_pack = "exact"
            else:
                entries = [{**e, "status": "install"} if e["status"] == "blocked" else e for e in entries]
                server_pack = "approx"

        return {
            "mods": _sort_pack_entries(entries),
            "filenames": [info["fileName"] for info in resolved.values() if info.get("fileName")],
            "mc_version": (manifest.get("minecraft") or {}).get("version"),
            "server_pack": server_pack,
        }

    return _cached_pack_contents(("curseforge", str(mod_id), str(file_id)), compute)


async def install_curseforge_modpack_stream(mod_id, file_id, server_name: str, ram_min: str, ram_max: str):
    server_dir = DEFAULT_SERVERS_PATH / server_name
    server_dir.mkdir(parents=True)

    try:
        headers = _curseforge_headers()
        yield {"type": "log", "message": "Descargando manifest del modpack..."}
        zf, version = await asyncio.to_thread(_download_curseforge_pack_zip, mod_id, file_id)
        manifest = json.loads(zf.read("manifest.json"))

        mc_version = (manifest.get("minecraft") or {}).get("version")
        if not mc_version:
            raise RuntimeError("El modpack no especifica versión de Minecraft")
        mod_loaders = (manifest.get("minecraft") or {}).get("modLoaders") or []
        primary_loader = next((m for m in mod_loaders if m.get("primary")), mod_loaders[0] if mod_loaders else None)
        loader_key, loader_version = _parse_curseforge_loader(primary_loader["id"]) if primary_loader else (None, None)

        async for event in _install_loader_or_vanilla(server_dir, loader_key, mc_version, loader_version, ram_min, ram_max):
            yield event

        # Antes de resolver y descargar los mods uno por uno, se comprueba si
        # el autor publicó un "Server Files" para esta build (server_pack_file_id,
        # ver get_curseforge_modpack_versions) — un zip ya preparado con los
        # mods de servidor (sin los de cliente) más su propia config/scripts,
        # pensado para bajar y arrancar directo. Cuando existe y se puede
        # descargar, se usa entero en vez de resolver cada mod contra la API;
        # solo se cae al método mod-por-mod si no hay Server Pack o si ESE
        # archivo en concreto también está bloqueado para terceros (es un
        # archivo aparte del "Client", el bloqueo de uno no implica el del otro).
        server_pack_file_id = version.get("server_pack_file_id")
        server_pack_info = None
        if server_pack_file_id:
            yield {"type": "log", "message": "Este modpack tiene un Server Pack — comprobando si se puede usar en vez de descargar los mods uno por uno..."}
            server_pack_info = await asyncio.to_thread(_resolve_curseforge_server_pack, server_pack_file_id)

        skipped_no_url = []
        if server_pack_info:
            yield {"type": "log", "message": f"✅ Server Pack encontrado ({server_pack_info['filename']}) — descargando de una sola vez..."}
            pack_bytes = await asyncio.to_thread(download_bytes, server_pack_info["download_url"])

            def _extract_server_pack():
                with zipfile.ZipFile(io.BytesIO(pack_bytes)) as server_zf:
                    count = len(server_zf.namelist())
                    server_zf.extractall(server_dir)
                    return count

            extracted_count = await asyncio.to_thread(_extract_server_pack)
            yield {"type": "log", "message": f"Server Pack extraído ({extracted_count} archivo(s)) — ya incluye sus propios mods y overrides."}

            # El Server Pack lo arma el autor del modpack, no esta app — puede
            # incluir igual algún mod como sodium/iris que ya sabemos que
            # revienta un servidor dedicado (pasa sobre todo con mods que
            # declaran side="BOTH" de forma incorrecta, ver
            # _KNOWN_CLIENT_ONLY_MOD_IDS en services/mod_checks.py).
            server_pack_mods_dir = server_dir / "mods"
            if server_pack_mods_dir.exists():
                removed_known_bad = []
                for jar_path in server_pack_mods_dir.iterdir():
                    if not jar_path.is_file():
                        continue
                    bad_reason = _known_client_only_reason(jar_path.name)
                    if bad_reason:
                        removed_known_bad.append(jar_path.name)
                        jar_path.unlink()
                if removed_known_bad:
                    yield {"type": "log", "message": f"🚫 {len(removed_known_bad)} mod(s) conocidos por reventar un servidor dedicado quitados del Server Pack: {', '.join(removed_known_bad)}"}
        else:
            if server_pack_file_id:
                yield {"type": "log", "message": "⚠️ El Server Pack de este modpack está bloqueado para descarga por terceros — se instalarán los mods uno por uno."}
            else:
                yield {"type": "log", "message": "Este modpack no tiene Server Pack — se instalarán los mods uno por uno."}

            all_file_refs = manifest.get("files", [])
            # manifest.json mezcla en "files" referencias a mods CON resource
            # packs, shaders y cualquier otro tipo de proyecto de CurseForge,
            # sin ninguna marca que los distinga ahí mismo — solo el classId
            # del proyecto (no del archivo) lo dice. Sin filtrar esto, un
            # resource pack bloqueado para terceros (algo frecuente, ni
            # siquiera es un mod que el servidor vaya a usar) terminaba
            # tratado igual que un mod real: bloqueando el arranque del
            # servidor hasta "instalarlo", cuando en realidad no hacía falta
            # en absoluto en un servidor.
            project_ids = list({f["projectID"] for f in all_file_refs if f.get("projectID")})
            project_classes = await asyncio.to_thread(_resolve_curseforge_project_classes, project_ids) if project_ids else {}
            file_refs = [f for f in all_file_refs if project_classes.get(f.get("projectID"), CURSEFORGE_MOD_CLASS_ID) == CURSEFORGE_MOD_CLASS_ID]
            skipped_non_mod_count = len(all_file_refs) - len(file_refs)
            if skipped_non_mod_count:
                yield {"type": "log", "message": f"ℹ️ {skipped_non_mod_count} archivo(s) que no son mods (resource packs, shaders...) se omiten: no hacen falta en un servidor."}

            yield {"type": "log", "message": f"Resolviendo descargas de {len(file_refs)} mod(s)..."}
            file_ids = [f["fileID"] for f in file_refs if f.get("fileID")]
            resolved = await asyncio.to_thread(_resolve_curseforge_file_urls, file_ids)

            mods_dir = server_dir / "mods"
            mods_dir.mkdir(exist_ok=True)
            # skipped_no_url son mods con nombre de archivo conocido pero sin URL de
            # descarga (bloqueados por el autor): se persisten en mods-pendientes.txt
            # porque se pueden verificar por nombre más tarde (ver write_pending_mods
            # / get_pending_mods). unresolved_ids son referencias que la API ni
            # siquiera devolvió (fileID inválido/borrado) — no hay nombre de archivo
            # con el que comprobar si ya se resolvieron a mano, así que solo se
            # avisan en el log: persistirlas dejaría el modpack bloqueado para
            # arrancar para siempre, sin ninguna forma de que el autoborrado lo detecte.
            unresolved_ids = []
            skipped_known_bad = []
            for ref in file_refs:
                info = resolved.get(ref.get("fileID"))
                # Se comprueba ANTES que el bloqueo de descarga a propósito:
                # un mod como sodium/iris que además esté bloqueado por
                # terceros (pasa) no debe terminar en mods-pendientes.json
                # pidiendo instalarlo a mano — ya sabemos que no hace falta
                # en el servidor sea cual sea su estado de descarga.
                filename_hint = info.get("fileName") if info else None
                if filename_hint and _known_client_only_reason(filename_hint):
                    skipped_known_bad.append(filename_hint)
                    continue
                if not info or not info.get("downloadUrl"):
                    if info and info.get("fileName"):
                        skipped_no_url.append(info["fileName"])
                    else:
                        unresolved_ids.append(str(ref.get("fileID")))
                    continue
                dest = _safe_join(mods_dir, info["fileName"])
                file_bytes = await asyncio.to_thread(download_bytes, info["downloadUrl"])
                dest.write_bytes(file_bytes)

            if skipped_known_bad:
                yield {"type": "log", "message": f"🚫 {len(skipped_known_bad)} mod(s) conocidos por reventar un servidor dedicado no se instalan: {', '.join(skipped_known_bad)}"}
            if skipped_no_url:
                yield {"type": "log", "message": f"⚠️ {len(skipped_no_url)} mod(s) no se pudieron descargar automáticamente (el autor bloqueó la distribución por terceros): {', '.join(skipped_no_url[:10])}"}
                await asyncio.to_thread(write_pending_mods, server_name, skipped_no_url)
            if unresolved_ids:
                yield {"type": "log", "message": f"⚠️ {len(unresolved_ids)} referencia(s) de mod no se pudieron resolver en absoluto (ID inválido o borrado en CurseForge): {', '.join(unresolved_ids[:10])}"}

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
        async for event in _reapply_ram(server_dir, ram_min, ram_max):
            yield event

        await asyncio.to_thread(_bootstrap_common_files, server_dir, mc_version, loader_key, loader_version)
        await asyncio.to_thread(_store_modpack_logo, server_dir, "curseforge", mod_id)
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
    find_possible_duplicate_mods() (services/mod_checks.py) para detectar
    duplicados dentro de un mismo modpack. Así, actualizar un mod (que cambia
    el número de versión en el nombre del jar) o añadir mods sueltos a mano no
    rompe la detección: solo importa si el "núcleo" del nombre original sigue
    presente.

    El % se calcula sobre el TOTAL de archivos del modpack candidato, no sobre
    lo instalado en el servidor: añadir mods extra a un servidor no baja el
    porcentaje, solo quitar o reemplazar los que vinieron originalmente con
    el pack sí lo hace.

    No requiere descargar ningún mod: filenames viene de
    get_modrinth_modpack_mods()/get_curseforge_modpack_mods(), que solo leen
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
