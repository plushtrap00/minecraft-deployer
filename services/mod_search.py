"""
services/mod_search.py - Búsqueda e instalación de mods desde Modrinth y CurseForge.

Contiene:
- Búsqueda de mods por nombre en Modrinth (API pública, sin key) y CurseForge
  (requiere CURSEFORGE_API_KEY, ver .env.example), con filtro opcional por
  categoría (misma taxonomía que expone cada API)
- Consulta de los archivos de un mod compatibles con la versión de MC y el
  modloader detectados en el modpack
- Descarga de los bytes del .jar elegido, para que el llamador lo procese con
  el mismo process_mod_jar() que usa la subida manual (routes/modpacks.py)
- Marcado de qué resultados de búsqueda ya están instalados en el modpack
"""
import re
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from config import CURSEFORGE_API_KEY

_HTTP_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 60
_USER_AGENT = "minecraft-deployer/1.0 (mod search)"
_CATEGORIES_CACHE_TTL = 3600

MODRINTH_LOADERS = {"forge", "neoforge", "fabric", "quilt"}

# https://docs.curseforge.com/rest-api/#tocS_ModLoaderType
CURSEFORGE_LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CURSEFORGE_GAME_ID = 432
CURSEFORGE_MOD_CLASS_ID = 6


class ModSearchError(Exception):
    """Error de red o de la API externa, ya traducido a un mensaje legible."""
    pass


def _http_get_json(url: str, headers: dict | None = None) -> dict | list:
    req_headers = {"User-Agent": _USER_AGENT}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise ModSearchError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ModSearchError(str(e.reason)) from e


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise ModSearchError(f"No se pudo descargar el archivo (HTTP {e.code})") from e
    except urllib.error.URLError as e:
        raise ModSearchError(f"No se pudo descargar el archivo: {e.reason}") from e


# ── Modrinth (api.modrinth.com/v2, sin autenticación) ──────────────────────────

def search_modrinth(
    query: str, mc_version: str | None, loader: str | None,
    categories: list[str] | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list, int]:
    facets = [["project_type:mod"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader in MODRINTH_LOADERS:
        facets.append([f"categories:{loader}"])
    if categories:
        # Un solo grupo con varias categorías = OR ("adventure" o "magic"),
        # igual que al tildar varias casillas en la web de Modrinth.
        facets.append([f"categories:{c}" for c in categories])
    params = {"limit": str(limit), "offset": str(offset), "facets": json.dumps(facets)}
    # Sin query, Modrinth devuelve resultados ordenados por popularidad (modo
    # "explorar", igual que entrar directo a la web sin buscar nada).
    if query:
        params["query"] = query
    else:
        params["index"] = "downloads"
    url = "https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    results = [
        {
            "source": "modrinth",
            "id": hit.get("project_id"),
            "slug": hit.get("slug"),
            "title": hit.get("title"),
            "description": hit.get("description"),
            "icon_url": hit.get("icon_url"),
            "downloads": hit.get("downloads", 0),
            "author": hit.get("author"),
            "page_url": f"https://modrinth.com/mod/{hit['slug']}" if hit.get("slug") else None,
        }
        for hit in data.get("hits", [])
    ]
    return results, data.get("total_hits", len(results))


def get_modrinth_versions(project_id: str, mc_version: str | None, loader: str | None) -> list:
    params = {}
    if loader in MODRINTH_LOADERS:
        params["loaders"] = json.dumps([loader])
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])
    url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}/version"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)

    versions = []
    for v in data:
        primary_file = next((f for f in v.get("files", []) if f.get("primary")), None)
        if not primary_file and v.get("files"):
            primary_file = v["files"][0]
        if not primary_file:
            continue
        versions.append({
            "source": "modrinth",
            "version_id": v.get("id"),
            "version_number": v.get("version_number"),
            "filename": primary_file.get("filename"),
            "download_url": primary_file.get("url"),
            "game_versions": v.get("game_versions", []),
        })
    return versions


_modrinth_categories_cache = {"ts": 0.0, "data": []}


def get_modrinth_categories() -> list:
    """
    Categorías de Modrinth para project_type=mod (adventure, magic, storage...).
    A diferencia de CurseForge, la API de Modrinth (GET /v2/tag/category) no
    expone ningún campo de jerarquía (solo name/icon/project_type/header):
    es una taxonomía plana, así que "children" siempre va vacío. Se deja en
    la respuesta para que el frontend use el mismo componente en ambas
    pestañas sin necesitar dos formas de dato distintas.
    """
    now = time.time()
    if _modrinth_categories_cache["data"] and now - _modrinth_categories_cache["ts"] < _CATEGORIES_CACHE_TTL:
        return _modrinth_categories_cache["data"]
    data = _http_get_json("https://api.modrinth.com/v2/tag/category")
    names = sorted({c["name"] for c in data if c.get("project_type") == "mod" and c.get("header") == "categories"})
    result = [{"id": name, "name": name.replace("-", " ").capitalize(), "children": []} for name in names]
    _modrinth_categories_cache["ts"] = now
    _modrinth_categories_cache["data"] = result
    return result


# ── CurseForge (api.curseforge.com/v1, requiere x-api-key) ────────────────────

def _curseforge_headers() -> dict:
    if not CURSEFORGE_API_KEY:
        raise ModSearchError(
            "CurseForge no está configurado: agrega CURSEFORGE_API_KEY a tu .env "
            "(se consigue gratis en console.curseforge.com/#/api-keys)"
        )
    return {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


def search_curseforge(
    query: str, mc_version: str | None, loader: str | None,
    categories: list[str] | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list, int]:
    headers = _curseforge_headers()
    params = {
        "gameId": str(CURSEFORGE_GAME_ID),
        "classId": str(CURSEFORGE_MOD_CLASS_ID),
        "pageSize": str(limit),
        "index": str(offset),
        "sortField": "2",  # popularidad
        "sortOrder": "desc",
    }
    # Sin query, CurseForge devuelve resultados ordenados por popularidad
    # (modo "explorar"), igual que Modrinth arriba.
    if query:
        params["searchFilter"] = query
    if mc_version:
        params["gameVersion"] = mc_version
    if loader in CURSEFORGE_LOADER_TYPES:
        params["modLoaderType"] = str(CURSEFORGE_LOADER_TYPES[loader])
    if categories:
        # categoryIds (plural) permite varias a la vez con semántica OR y
        # tiene prioridad sobre categoryId; máximo 10 según la API.
        params["categoryIds"] = json.dumps([int(c) for c in categories][:10])
    url = "https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)

    results = []
    for mod in data.get("data", []):
        authors = mod.get("authors") or []
        links = mod.get("links") or {}
        results.append({
            "source": "curseforge",
            "id": mod.get("id"),
            "slug": mod.get("slug"),
            "title": mod.get("name"),
            "description": mod.get("summary"),
            "icon_url": (mod.get("logo") or {}).get("thumbnailUrl"),
            "downloads": mod.get("downloadCount", 0),
            "author": authors[0]["name"] if authors else None,
            "page_url": links.get("websiteUrl"),
        })
    total = (data.get("pagination") or {}).get("totalCount", len(results))
    return results, total


_CURSEFORGE_FILES_PAGE_SIZE = 50
_CURSEFORGE_FILES_MAX = 300  # tope de seguridad: 6 páginas como mucho por mod


def get_curseforge_files(mod_id, mc_version: str | None, loader: str | None) -> list:
    """
    Trae TODOS los archivos del mod (no solo los primeros 50): la API de
    CurseForge pagina con index/pageSize, así que sin este loop las versiones
    más antiguas de mods con muchos builds quedaban invisibles para siempre.
    """
    headers = _curseforge_headers()
    base_params = {"pageSize": str(_CURSEFORGE_FILES_PAGE_SIZE)}
    if mc_version:
        base_params["gameVersion"] = mc_version
    if loader in CURSEFORGE_LOADER_TYPES:
        base_params["modLoaderType"] = str(CURSEFORGE_LOADER_TYPES[loader])

    raw_files = []
    index = 0
    while index < _CURSEFORGE_FILES_MAX:
        params = dict(base_params, index=str(index))
        url = f"https://api.curseforge.com/v1/mods/{mod_id}/files?" + urllib.parse.urlencode(params)
        data = _http_get_json(url, headers)
        page = data.get("data", [])
        raw_files.extend(page)
        if len(page) < _CURSEFORGE_FILES_PAGE_SIZE:
            break
        index += _CURSEFORGE_FILES_PAGE_SIZE

    files = []
    for f in raw_files:
        files.append({
            "source": "curseforge",
            "version_id": f.get("id"),
            "version_number": f.get("displayName"),
            "filename": f.get("fileName"),
            # El autor puede deshabilitar la descarga por terceros; en ese caso
            # downloadUrl viene null y el frontend debe avisar que no se puede instalar.
            "download_url": f.get("downloadUrl"),
            "game_versions": f.get("gameVersions", []),
        })
    return files


_curseforge_categories_cache = {"ts": 0.0, "data": []}


def get_curseforge_categories() -> list:
    """
    Categorías de CurseForge para Minecraft mods (classId=6), con jerarquía:
    Addons, Technology, World Gen... tienen subcategorías propias.

    La API (GET /v1/categories) devuelve TODO en una lista plana; cada
    categoría trae parentCategoryId. Las de primer nivel tienen
    parentCategoryId == classId (6, la propia clase "mods"); las
    subcategorías tienen parentCategoryId == id de su categoría padre.
    Acá se arma el árbol de 2 niveles a partir de esa lista.
    """
    now = time.time()
    if _curseforge_categories_cache["data"] and now - _curseforge_categories_cache["ts"] < _CATEGORIES_CACHE_TTL:
        return _curseforge_categories_cache["data"]
    headers = _curseforge_headers()
    params = {"gameId": str(CURSEFORGE_GAME_ID), "classId": str(CURSEFORGE_MOD_CLASS_ID)}
    url = "https://api.curseforge.com/v1/categories?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)

    all_cats = [c for c in data.get("data", []) if not c.get("isClass")]
    children_by_parent: dict = {}
    for c in all_cats:
        parent_id = c.get("parentCategoryId")
        if parent_id != CURSEFORGE_MOD_CLASS_ID:
            children_by_parent.setdefault(parent_id, []).append(c)

    top_level = [c for c in all_cats if c.get("parentCategoryId") == CURSEFORGE_MOD_CLASS_ID]
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
    _curseforge_categories_cache["ts"] = now
    _curseforge_categories_cache["data"] = result
    return result


# ── Detección de "ya instalado" ────────────────────────────────────────────────
#
# El slug/id que devuelven Modrinth y CurseForge no siempre es idéntico al
# mod_id real embebido en el jar (p.ej. slug "biomes-o-plenty" vs mod_id real
# "biomesoplenty"), así que se comparan ambos lados normalizados a solo
# alfanuméricos en minúsculas, no con igualdad exacta de string.

_installed_ids_cache: dict = {}  # str(mods_dir) -> (mtime, {normalized ids})


def _norm_id(value: str | None) -> str:
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())


def _installed_normalized_ids(mods_dir: Path) -> set:
    from services.modpack import build_mod_id_index  # import perezoso: evita ciclo con services.modpack

    key = str(mods_dir)
    try:
        mtime = mods_dir.stat().st_mtime
    except Exception:
        mtime = None

    cached = _installed_ids_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    index = build_mod_id_index(mods_dir) if mods_dir.exists() else {}
    result = {_norm_id(mod_id) for mod_id in index.keys()}
    _installed_ids_cache[key] = (mtime, result)
    return result


def mark_installed(results: list, mods_dir: Path) -> list:
    """Agrega result['installed'] = True/False comparando el slug contra los mod_id instalados."""
    installed_ids = _installed_normalized_ids(mods_dir)
    for r in results:
        r["installed"] = bool(r.get("slug")) and _norm_id(r["slug"]) in installed_ids
    return results
