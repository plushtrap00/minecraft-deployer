"""
services/mod_dependencies.py - Detección e instalación de dependencias obligatorias que faltan.

Contiene:
- Lectura de las dependencias obligatorias que declara cada mod instalado
  (mods.toml / neoforge.mods.toml, fabric.mod.json, quilt.mod.json) y de los
  mod_id que aporta cada jar, incluidos los que lleva empaquetados dentro
  (jar-in-jar) y los "provides" de Fabric/Quilt
- find_missing_dependencies(): qué mod_id obligatorios no aporta ningún mod
  habilitado — es la misma comprobación que hace el loader al arrancar
  ("Missing or unsupported mandatory dependencies"), pero antes de arrancar
- install_missing_dependencies(): las busca en Modrinth/CurseForge y las
  instala con process_mod_jar(), el mismo flujo que la subida manual

Cómo se encuentra el proyecto de cada dependencia (un mod_id como "balm" o
"ftblibrary" no siempre coincide con el slug del proyecto en ninguna web):
1. Si un jar deshabilitado ya la aporta, se reactiva en vez de descargar nada.
2. Las dependencias que el propio sitio tiene registradas para el jar que la
   pide: Modrinth por hash sha1, CurseForge por fingerprint (murmur2). Es la
   vía fiable cuando el jar se descargó de ese sitio.
3. Proyecto de Modrinth con ese slug exacto, y luego búsqueda por nombre en
   Modrinth y CurseForge (solo resultados cuyo slug/título se parezca al id).
Ningún candidato se instala a ciegas: se descarga su versión más nueva
compatible con el MC/loader del servidor y solo se acepta si el jar declara
de verdad ese mod_id.
"""
import io
import re
import json
import zipfile
import hashlib
from pathlib import Path

from config import CURSEFORGE_API_KEY, DEFAULT_SERVERS_PATH
from services.modpack import (
    detect_modpack_version, process_mod_jar, resolve_pending_mods, mod_display_name,
)
from services.modloader import loader_key_from_display
from services.mod_search import (
    ModSearchError, _http_post_json, _curseforge_headers, _norm_id, download_bytes,
    get_modrinth_versions, get_curseforge_files, search_modrinth, search_curseforge,
    CURSEFORGE_GAME_ID,
)

# mod_id que aporta el propio juego/loader, nunca un mod descargable.
_BUILTIN_DEP_IDS = {
    "minecraft", "java", "forge", "neoforge", "fml", "javafml", "lowcodefml",
    "fabricloader", "fabric-loader", "quilt_loader", "quiltloader",
}

# Hasta dónde se siguen las dependencias de las dependencias recién instaladas.
_MAX_ROUNDS = 5
_MAX_NESTED_JAR_DEPTH = 3
# https://docs.curseforge.com/rest-api/#tocS_FileRelationType
_CURSEFORGE_REQUIRED_DEPENDENCY = 3

_TOML_FILES = ("META-INF/neoforge.mods.toml", "META-INF/mods.toml")
_TOML_TABLE_END_RE = re.compile(r'\n\s*\[')
_TOML_MODS_HEADER_RE = re.compile(r'\[\[\s*mods\s*\]\]', re.IGNORECASE)
_TOML_DEP_HEADER_RE = re.compile(r'\[\[\s*dependencies\.["\']?([\w\-.]+)["\']?\s*\]\]', re.IGNORECASE)


def _toml_str(block: str, key: str) -> str | None:
    m = re.search(r'^[ \t]*' + key + r'\s*=\s*[\'"]([^\'"]*)[\'"]', block, re.MULTILINE | re.IGNORECASE)
    return m.group(1) if m else None


def _toml_bool(block: str, key: str) -> bool | None:
    m = re.search(r'^[ \t]*' + key + r'\s*=\s*(true|false)', block, re.MULTILINE | re.IGNORECASE)
    return m.group(1).lower() == "true" if m else None


def _table_body(rest: str) -> str:
    end = _TOML_TABLE_END_RE.search(rest)
    return rest[:end.start()] if end else rest


def _parse_toml(text: str) -> tuple[set, list]:
    """
    (mod_ids aportados, [(owner_mod_id, dep_mod_id, version_range)] obligatorias).

    A diferencia de read_mod_metadata(), que solo mira el primer [[mods]],
    aquí hacen falta TODOS: un mismo jar puede declarar varios mods y
    cualquiera de ellos puede satisfacer la dependencia de otro.

    Obligatoria = type="required" (NeoForge 1.20.2+) o mandatory=true (Forge y
    NeoForge antiguo). side="CLIENT" se descarta: es una dependencia que solo
    hace falta en el cliente, el servidor dedicado arranca sin ella.
    """
    provided = set()
    for m in _TOML_MODS_HEADER_RE.finditer(text):
        mod_id = _toml_str(_table_body(text[m.end():]), "modId")
        if mod_id:
            provided.add(mod_id)

    required = []
    for m in _TOML_DEP_HEADER_RE.finditer(text):
        block = _table_body(text[m.end():])
        dep_id = _toml_str(block, "modId")
        if not dep_id:
            continue
        dep_type = (_toml_str(block, "type") or "").lower()
        mandatory = _toml_bool(block, "mandatory")
        is_required = dep_type == "required" if dep_type else bool(mandatory)
        if not is_required:
            continue
        if (_toml_str(block, "side") or "").upper() == "CLIENT":
            continue
        required.append((m.group(1), dep_id, _toml_str(block, "versionRange")))
    return provided, required


def _parse_fabric(data: dict) -> tuple[set, list]:
    provided = set()
    if data.get("id"):
        provided.add(data["id"])
    for p in data.get("provides") or []:
        if isinstance(p, str):
            provided.add(p)
    required = []
    depends = data.get("depends") or {}
    if isinstance(depends, dict):
        for dep_id, spec in depends.items():
            if isinstance(spec, list):
                spec = ", ".join(s for s in spec if isinstance(s, str))
            elif not isinstance(spec, str):
                spec = None
            required.append((data.get("id"), dep_id, spec))
    return provided, required


def _parse_quilt(data: dict) -> tuple[set, list]:
    meta = data.get("quilt_loader") or {}
    provided = set()
    if meta.get("id"):
        provided.add(meta["id"])
    for p in meta.get("provides") or []:
        pid = p if isinstance(p, str) else (p.get("id") if isinstance(p, dict) else None)
        if pid:
            provided.add(pid)
    required = []
    for dep in meta.get("depends") or []:
        if isinstance(dep, str):
            required.append((meta.get("id"), dep, None))
        elif isinstance(dep, dict) and dep.get("id") and not dep.get("optional"):
            versions = dep.get("versions")
            required.append((meta.get("id"), dep["id"], versions if isinstance(versions, str) else None))
    return provided, required


def read_jar_dependency_info(jar_bytes: bytes, _depth: int = 0) -> dict:
    """
    {"provided": set de mod_id que aporta el jar (incluidos sus jar-in-jar),
     "required": [(owner_mod_id, dep_mod_id, version_range)] obligatorias,
     sin las del propio juego/loader}.

    Los jar-in-jar (META-INF/jarjar/ en Forge/NeoForge, META-INF/jars/ en
    Fabric/Quilt) los carga el loader como mods más, así que cuentan como
    aportados: sin esto, p.ej. Xaero's Minimap (que lleva xaerolib dentro)
    aparecería pidiendo una dependencia que en realidad ya tiene.
    """
    provided, required = set(), []
    try:
        with zipfile.ZipFile(io.BytesIO(jar_bytes)) as zf:
            names = zf.namelist()
            for toml_name in _TOML_FILES:
                if toml_name in names:
                    p, r = _parse_toml(zf.read(toml_name).decode("utf-8", errors="replace"))
                    provided |= p
                    required += r
                    break
            else:
                if "fabric.mod.json" in names:
                    p, r = _parse_fabric(json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="replace")))
                    provided |= p
                    required += r
                elif "quilt.mod.json" in names:
                    p, r = _parse_quilt(json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="replace")))
                    provided |= p
                    required += r

            if _depth < _MAX_NESTED_JAR_DEPTH:
                for name in names:
                    if name.endswith(".jar") and (name.startswith("META-INF/jarjar/") or name.startswith("META-INF/jars/")):
                        nested = read_jar_dependency_info(zf.read(name), _depth + 1)
                        provided |= nested["provided"]
                        required += nested["required"]
    except Exception:
        pass
    required = [r for r in required if r[1] and r[1].lower() not in _BUILTIN_DEP_IDS]
    return {"provided": provided, "required": required}


def _scan_mods_dir(mods_dir: Path) -> dict:
    """Lee todos los jars una vez: qué aporta cada uno (habilitado o no) y qué pide cada habilitado."""
    enabled, disabled = [], []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith(".jar"):
            target = enabled
        elif low.endswith(".jar.disabled"):
            target = disabled
        else:
            continue
        try:
            info = read_jar_dependency_info(f.read_bytes())
        except Exception:
            continue
        target.append((f, info))
    return {"enabled": enabled, "disabled": disabled}


def _missing_from_scan(scan: dict) -> list:
    provided = set()
    for _, info in scan["enabled"]:
        provided |= info["provided"]
    provided_lower = {p.lower() for p in provided}

    disabled_provider = {}
    for path, info in scan["disabled"]:
        for mod_id in info["provided"]:
            disabled_provider.setdefault(mod_id.lower(), path)

    missing: dict = {}
    for path, info in scan["enabled"]:
        for owner, dep_id, version_range in info["required"]:
            if dep_id.lower() in provided_lower:
                continue
            entry = missing.setdefault(dep_id, {
                "dep_id": dep_id, "version_range": version_range, "requested_by": [],
                "disabled_filename": disabled_provider[dep_id.lower()].name if dep_id.lower() in disabled_provider else None,
            })
            if not any(r["filename"] == path.name for r in entry["requested_by"]):
                entry["requested_by"].append({
                    "mod_id": owner, "filename": path.name, "display_name": mod_display_name(path.name),
                })
    return sorted(missing.values(), key=lambda e: e["dep_id"])


def find_missing_dependencies(mods_dir: Path) -> list:
    """
    [{dep_id, version_range, requested_by: [{mod_id, filename, display_name}],
      disabled_filename}] — dependencias obligatorias que ningún mod
    habilitado aporta. Solo lee disco, sin red.
    """
    if not mods_dir.exists():
        return []
    return _missing_from_scan(_scan_mods_dir(mods_dir))


# ── Búsqueda de candidatos en Modrinth / CurseForge ────────────────────────────

def curseforge_fingerprint(data: bytes) -> int:
    """
    Fingerprint de CurseForge: MurmurHash2 (32 bits, semilla 1) del archivo
    sin los bytes de espacio en blanco 9/10/13/32 — así es como lo calcula su
    propio cliente, y es lo que espera POST /v1/fingerprints.
    """
    data = data.translate(None, b"\t\n\r ")
    m = 0x5BD1E995
    mask = 0xFFFFFFFF
    length = len(data)
    h = (1 ^ length) & mask
    full = length - (length % 4)
    for i in range(0, full, 4):
        k = (data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24))
        k = (k * m) & mask
        k ^= k >> 24
        k = (k * m) & mask
        h = (h * m) & mask
        h ^= k
    tail = length % 4
    if tail == 3:
        h ^= data[full + 2] << 16
    if tail >= 2:
        h ^= data[full + 1] << 8
    if tail >= 1:
        h ^= data[full]
        h = (h * m) & mask
    h ^= h >> 13
    h = (h * m) & mask
    h ^= h >> 15
    return h


def _modrinth_required_projects(jar_paths: list) -> dict:
    """{filename: [project_id]} de las dependencias obligatorias que Modrinth tiene registradas para cada jar (por sha1)."""
    by_hash = {}
    for path in jar_paths:
        try:
            by_hash[hashlib.sha1(path.read_bytes()).hexdigest()] = path.name
        except OSError:
            continue
    if not by_hash:
        return {}
    try:
        data = _http_post_json("https://api.modrinth.com/v2/version_files", {"hashes": list(by_hash), "algorithm": "sha1"})
    except ModSearchError:
        return {}
    result = {}
    for sha1, version in (data or {}).items():
        if sha1 not in by_hash or not isinstance(version, dict):
            continue
        result[by_hash[sha1]] = [
            d["project_id"] for d in version.get("dependencies") or []
            if d.get("dependency_type") == "required" and d.get("project_id")
        ]
    return result


def _curseforge_required_projects(jar_paths: list) -> dict:
    """{filename: [mod_id de CurseForge]} de las dependencias obligatorias registradas para cada jar (por fingerprint)."""
    if not CURSEFORGE_API_KEY:
        return {}
    by_fp = {}
    for path in jar_paths:
        try:
            by_fp[curseforge_fingerprint(path.read_bytes())] = path.name
        except OSError:
            continue
    if not by_fp:
        return {}
    try:
        data = _http_post_json(
            f"https://api.curseforge.com/v1/fingerprints/{CURSEFORGE_GAME_ID}",
            {"fingerprints": list(by_fp)}, _curseforge_headers(),
        )
    except ModSearchError:
        return {}
    result = {}
    for match in (data.get("data") or {}).get("exactMatches") or []:
        f = match.get("file") or {}
        filename = by_fp.get(f.get("fileFingerprint"))
        if not filename:
            continue
        result[filename] = [
            d["modId"] for d in f.get("dependencies") or []
            if d.get("relationType") == _CURSEFORGE_REQUIRED_DEPENDENCY and d.get("modId")
        ]
    return result


def _search_candidates(dep_id: str, mc_version: str | None, loader: str | None) -> list:
    """Candidatos por nombre: solo resultados cuyo slug o título contenga el id (o al revés), para no descargar cualquier cosa."""
    target = _norm_id(dep_id)
    if len(target) < 3:
        return []

    def looks_like(result: dict) -> bool:
        for value in (result.get("slug"), result.get("title")):
            norm = _norm_id(value)
            if norm and (target in norm or (len(norm) >= 3 and norm in target)):
                return True
        return False

    candidates = []
    query = dep_id.replace("_", " ").replace("-", " ")
    try:
        results, _ = search_modrinth(query, mc_version, loader, limit=5)
        candidates += [("modrinth", r["id"], r.get("title")) for r in results if looks_like(r)]
    except ModSearchError:
        pass
    if CURSEFORGE_API_KEY:
        try:
            results, _ = search_curseforge(query, mc_version, loader, limit=5)
            candidates += [("curseforge", r["id"], r.get("title")) for r in results if looks_like(r)]
        except ModSearchError:
            pass
    return candidates


def _newest_file(source: str, project_id, mc_version: str | None, loader: str | None) -> tuple:
    """(file_dict, motivo_si_no_hay) — la versión más nueva compatible con descarga directa."""
    try:
        if source == "modrinth":
            files = get_modrinth_versions(str(project_id), mc_version, loader)  # ya vienen de más nueva a más vieja
        else:
            files = sorted(get_curseforge_files(project_id, mc_version, loader), key=lambda f: f.get("file_date") or "", reverse=True)
    except ModSearchError as e:
        return None, str(e)
    if not files:
        return None, "no tiene versiones para la versión de Minecraft/modloader de este servidor"
    downloadable = [f for f in files if f.get("download_url")]
    if not downloadable:
        return None, "el autor bloqueó la descarga por terceros; hay que instalarlo a mano"
    return downloadable[0], None


# ── Instalación ───────────────────────────────────────────────────────────────

def install_missing_dependencies(modpack: str):
    """
    Generador de eventos (para SSE): {"type": "progress", "message"} mientras
    trabaja (con dep_id/state cuando se refiere a una dependencia concreta,
    para que el frontend actualice esa fila), y al final {"type": "done",
    "installed", "enabled", "unresolved"}.
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    info = detect_modpack_version(modpack)
    mc_version = info.get("mc_version")
    loader = loader_key_from_display(info.get("modloader"))

    installed, enabled, unresolved = [], [], {}
    candidate_cache: dict = {}  # (source, project_id) -> {"bytes", "filename", "provided", "title"} | {"error"}
    attempted: set = set()

    for _round in range(_MAX_ROUNDS):
        yield {"type": "progress", "message": "Analizando las dependencias de los mods instalados..."}
        scan = _scan_mods_dir(mods_dir)
        missing = [m for m in _missing_from_scan(scan) if m["dep_id"].lower() not in attempted]
        if not missing:
            break

        # 1) Reactivar los que ya están en mods/ pero deshabilitados.
        to_download = []
        for entry in missing:
            attempted.add(entry["dep_id"].lower())
            if entry["disabled_filename"]:
                src = mods_dir / entry["disabled_filename"]
                dest = mods_dir / entry["disabled_filename"][: -len(".disabled")]
                if src.exists() and not dest.exists():
                    src.rename(dest)
                    enabled.append({"dep_id": entry["dep_id"], "filename": dest.name, "requested_by": entry["requested_by"]})
                    yield {"type": "progress", "message": f"Reactivado {dest.name} (aporta «{entry['dep_id']}»)",
                           "dep_id": entry["dep_id"], "state": "enabled", "filename": dest.name}
                    continue
            to_download.append(entry)
        if not to_download:
            continue

        # 2) Dependencias registradas en Modrinth/CurseForge para los jars que las piden.
        yield {"type": "progress", "message": "Consultando Modrinth y CurseForge..."}
        owner_paths = {r["filename"]: mods_dir / r["filename"] for e in to_download for r in e["requested_by"]}
        modrinth_deps = _modrinth_required_projects(list(owner_paths.values()))
        curseforge_deps = _curseforge_required_projects(list(owner_paths.values()))

        provided_now = set()
        for entry in to_download:
            dep_id = entry["dep_id"]
            if dep_id.lower() in provided_now:
                continue
            owners = ", ".join(r["display_name"] for r in entry["requested_by"])
            yield {"type": "progress", "message": f"Buscando «{dep_id}» (lo necesita {owners})...",
                   "dep_id": dep_id, "state": "searching", "requested_by": entry["requested_by"]}

            candidates = []
            for r in entry["requested_by"]:
                candidates += [("modrinth", pid, None) for pid in modrinth_deps.get(r["filename"], [])]
                candidates += [("curseforge", mid, None) for mid in curseforge_deps.get(r["filename"], [])]
            candidates.append(("modrinth", dep_id, None))
            candidates += _search_candidates(dep_id, mc_version, loader)

            reasons, seen, chosen = [], set(), None
            for source, project_id, title in candidates:
                key = (source, str(project_id))
                if key in seen:
                    continue
                seen.add(key)
                cached = candidate_cache.get(key)
                if cached is None:
                    file, reason = _newest_file(source, project_id, mc_version, loader)
                    if not file:
                        cached = {"error": reason, "title": title or str(project_id)}
                    else:
                        site = "Modrinth" if source == "modrinth" else "CurseForge"
                        yield {"type": "progress", "message": f"Descargando {file['filename']} de {site}...",
                               "dep_id": dep_id, "state": "downloading"}
                        try:
                            jar_bytes = download_bytes(file["download_url"])
                            cached = {
                                "bytes": jar_bytes, "filename": file["filename"], "source": source,
                                "provided": read_jar_dependency_info(jar_bytes)["provided"],
                                "title": title or file["filename"],
                            }
                        except ModSearchError as e:
                            cached = {"error": str(e), "title": title or file["filename"]}
                    candidate_cache[key] = cached
                if "error" in cached:
                    # Un 404 de un slug adivinado no es un motivo útil para el usuario.
                    if source != "modrinth" or str(project_id) != dep_id:
                        reasons.append(f"{cached['title']}: {cached['error']}")
                    continue
                if dep_id.lower() in {p.lower() for p in cached["provided"]}:
                    chosen = cached
                    break

            if not chosen:
                unresolved[dep_id] = {
                    "dep_id": dep_id, "version_range": entry["version_range"], "requested_by": entry["requested_by"],
                    "reason": "; ".join(reasons[:2]) if reasons else "no se encontró en Modrinth" + ("" if CURSEFORGE_API_KEY else " (CurseForge no está configurado)"),
                }
                continue

            result = process_mod_jar(mods_dir, chosen["filename"], chosen["bytes"], mc_version)
            if result["status"] == "added":
                resolve_pending_mods(modpack, result["filename"], result.get("mod_id"), result.get("mod_version"))
                provided_now |= {p.lower() for p in chosen["provided"]}
                installed.append({
                    "dep_id": dep_id, "filename": result["filename"], "source": chosen["source"],
                    "mod_version": result.get("mod_version"), "requested_by": entry["requested_by"],
                })
                yield {"type": "progress", "message": f"Instalado {result['filename']}",
                       "dep_id": dep_id, "state": "installed", "filename": result["filename"]}
            elif result["status"] == "already_installed":
                provided_now |= {p.lower() for p in chosen["provided"]}
            else:
                unresolved[dep_id] = {
                    "dep_id": dep_id, "version_range": entry["version_range"], "requested_by": entry["requested_by"],
                    "reason": result.get("detail") or "no se pudo instalar",
                }

    yield {"type": "done", "installed": installed, "enabled": enabled, "unresolved": list(unresolved.values())}
