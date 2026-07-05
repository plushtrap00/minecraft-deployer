"""
services/mod_search.py - Búsqueda e instalación de mods desde Modrinth y CurseForge.

Contiene:
- Búsqueda de mods por nombre en Modrinth (API pública, sin key) y CurseForge
  (requiere CURSEFORGE_API_KEY, ver .env.example)
- Consulta de los archivos de un mod compatibles con la versión de MC y el
  modloader detectados en el modpack
- Descarga de los bytes del .jar elegido, para que el llamador lo procese con
  el mismo process_mod_jar() que usa la subida manual (routes/modpacks.py)
"""
import json
import urllib.request
import urllib.error
import urllib.parse

from config import CURSEFORGE_API_KEY

_HTTP_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 60
_USER_AGENT = "minecraft-deployer/1.0 (mod search)"

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

def search_modrinth(query: str, mc_version: str | None, loader: str | None, limit: int = 20) -> list:
    facets = [["project_type:mod"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader in MODRINTH_LOADERS:
        facets.append([f"categories:{loader}"])
    params = {"query": query, "limit": str(limit), "facets": json.dumps(facets)}
    url = "https://api.modrinth.com/v2/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    return [
        {
            "source": "modrinth",
            "id": hit.get("project_id"),
            "title": hit.get("title"),
            "description": hit.get("description"),
            "icon_url": hit.get("icon_url"),
            "downloads": hit.get("downloads", 0),
            "author": hit.get("author"),
        }
        for hit in data.get("hits", [])
    ]


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


# ── CurseForge (api.curseforge.com/v1, requiere x-api-key) ────────────────────

def _curseforge_headers() -> dict:
    if not CURSEFORGE_API_KEY:
        raise ModSearchError(
            "CurseForge no está configurado: agrega CURSEFORGE_API_KEY a tu .env "
            "(se consigue gratis en console.curseforge.com/#/api-keys)"
        )
    return {"x-api-key": CURSEFORGE_API_KEY, "Accept": "application/json"}


def search_curseforge(query: str, mc_version: str | None, loader: str | None, limit: int = 20) -> list:
    headers = _curseforge_headers()
    params = {
        "gameId": str(CURSEFORGE_GAME_ID),
        "classId": str(CURSEFORGE_MOD_CLASS_ID),
        "searchFilter": query,
        "pageSize": str(limit),
        "sortField": "2",  # popularidad
        "sortOrder": "desc",
    }
    if mc_version:
        params["gameVersion"] = mc_version
    if loader in CURSEFORGE_LOADER_TYPES:
        params["modLoaderType"] = str(CURSEFORGE_LOADER_TYPES[loader])
    url = "https://api.curseforge.com/v1/mods/search?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)

    results = []
    for mod in data.get("data", []):
        authors = mod.get("authors") or []
        results.append({
            "source": "curseforge",
            "id": mod.get("id"),
            "title": mod.get("name"),
            "description": mod.get("summary"),
            "icon_url": (mod.get("logo") or {}).get("thumbnailUrl"),
            "downloads": mod.get("downloadCount", 0),
            "author": authors[0]["name"] if authors else None,
        })
    return results


def get_curseforge_files(mod_id, mc_version: str | None, loader: str | None) -> list:
    headers = _curseforge_headers()
    params = {"pageSize": "50"}
    if mc_version:
        params["gameVersion"] = mc_version
    if loader in CURSEFORGE_LOADER_TYPES:
        params["modLoaderType"] = str(CURSEFORGE_LOADER_TYPES[loader])
    url = f"https://api.curseforge.com/v1/mods/{mod_id}/files?" + urllib.parse.urlencode(params)
    data = _http_get_json(url, headers)

    files = []
    for f in data.get("data", []):
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
