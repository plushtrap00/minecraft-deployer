"""
services/pack_install_modrinth.py - Modpacks de Modrinth (.mrpack): buscar,
versiones, qué trae cada versión e instalarla como servidor nuevo.

Un .mrpack es un zip con modrinth.index.json (dependencies: loader + mc;
files: [{path, downloads: [url], env: {client, server}}]) + overrides/ y
opcionalmente server-overrides/. Las descargas YA son URLs directas.
"""
import asyncio
import io
import json
import re
import shutil
import time
import urllib.parse
import zipfile
from pathlib import Path
from config import DEFAULT_SERVERS_PATH
from app_constants import MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS
from services.mod_search import MODRINTH_LOADERS, _http_get_json, download_bytes, modrinth_result_extras
from services.modpack_update import record_source
from services.server_create import _bootstrap_common_files
from services.pack_install_common import (
    ModpackVersionUnavailable, _cached_pack_contents, _display_name_from_filename, _embedded_jar_entries,
    _extract_overrides, _install_loader_or_vanilla, _kind_from_path, _known_client_only_reason,
    _reapply_ram, _safe_join, _sort_pack_entries, _store_modpack_logo,
)


_MODRINTH_LOADER_DEP_KEYS = {"forge": "forge", "neoforge": "neoforge", "fabric": "fabric-loader", "quilt": "quilt-loader"}


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


_MODRINTH_CDN_PROJECT_RE = re.compile(r"cdn\.modrinth\.com/data/([A-Za-z0-9]+)/")


_MODRINTH_PROJECTS_CHUNK = 100


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
        await asyncio.to_thread(record_source, server_dir, "modrinth", project_id, version_id,
                                index.get("versionId"), mc_version, loader_key, index.get("name"))
        yield {"type": "done", "success": True, "name": server_name}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}
