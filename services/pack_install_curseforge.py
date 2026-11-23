"""
services/pack_install_curseforge.py - Modpacks de CurseForge: buscar,
versiones, qué trae cada versión e instalarla como servidor nuevo.

Un modpack de CurseForge es un .zip con manifest.json (minecraft.version,
minecraft.modLoaders, files: [{projectID, fileID}] — son REFERENCIAS, no
URLs; se resuelven con la API) + overrides/. Si el autor publica un «server
pack», se usa para saber qué mods hacen falta en el servidor (leyendo solo el
índice del zip remoto, sin descargarlo entero).
"""
import asyncio
import io
import json
import shutil
import struct
import time
import urllib.parse
import urllib.request
import zipfile
from config import DEFAULT_SERVERS_PATH
from app_constants import (
    CURSEFORGE_BULK_FILES_CHUNK, CURSEFORGE_FILES_MAX, CURSEFORGE_FILES_PAGE_SIZE, MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS,
)
from services.mod_checks import _dedup_fingerprint
from services.mod_search import (
    CURSEFORGE_GAME_ID, CURSEFORGE_LOADER_TYPES, CURSEFORGE_MOD_CLASS_ID, _HTTP_TIMEOUT,
    _curseforge_headers, _http_get_json, curseforge_result_extras, download_bytes,
)
from services.modpack_update import record_source
from services.pending_mods import write_pending_mods
from services.server_create import _bootstrap_common_files
from services.pack_install_common import (
    CURSEFORGE_MODPACK_CLASS_ID, ModpackDownloadBlocked, ModpackVersionUnavailable, _cached_pack_contents,
    _display_name_from_filename, _embedded_jar_entries, _install_loader_or_vanilla, _known_client_only_reason,
    _reapply_ram, _safe_join, _sort_pack_entries, _store_modpack_logo,
)


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

            # El Server Pack lo monta el autor del modpack, no esta app — puede
            # incluir aun así algún mod como sodium/iris que ya sabemos que
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
        await asyncio.to_thread(record_source, server_dir, "curseforge", mod_id, file_id,
                                version.get("version_number"), mc_version, loader_key, manifest.get("name"))
        yield {"type": "done", "success": True, "name": server_name, "skipped": skipped_no_url}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}
