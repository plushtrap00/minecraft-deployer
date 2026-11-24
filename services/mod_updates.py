"""
services/mod_updates.py - Buscar y aplicar actualizaciones de los mods instalados.

Cada jar de mods/ se identifica por su contenido, no por el nombre:
- Modrinth: SHA-1 del archivo (POST /v2/version_files y /version_files/update).
- CurseForge (solo si hay CURSEFORGE_API_KEY y Modrinth no lo conoce): la
  huella murmur2 que usa su API (POST /v1/fingerprints/432), y de ahí
  latestFilesIndexes del mod para la última versión de la versión de MC y el
  loader del servidor.

Todo va por lotes (unas pocas peticiones para todo el modpack, no una por mod).
Los hashes se guardan en <servidor>/.mod_hashes.json por nombre+tamaño+fecha,
así que la segunda comprobación ya no relee los jars.

La comprobación corre en un hilo (un modpack grande puede tardar) y el panel
consulta el progreso. Las actualizaciones se aplican de una en una desde el
panel: el jar nuevo se descarga, se comprueba su hash y el antiguo se guarda
en <servidor>/.mods-replaced/<lote>/ para poder deshacer el lote entero.
"""
import hashlib
import json
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from config import CURSEFORGE_API_KEY, DEFAULT_SERVERS_PATH
from services.mod_hashes import curseforge_fingerprint  # noqa: F401 (también se usa desde fuera)
from services.mod_metadata import mod_display_name
from services.mod_search import (
    CURSEFORGE_GAME_ID, CURSEFORGE_LOADER_TYPES, ModSearchError,
    _curseforge_headers, _http_get_json, _http_post_json, download_bytes,
)
from services.modloader import loader_key_from_display
from services.modpack import detect_modpack_version
from services.secure_files import atomic_write_text

HASH_CACHE_NAME = ".mod_hashes.json"
REPLACED_DIR_NAME = ".mods-replaced"
KEEP_REPLACED_BATCHES = 3
MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
_STABILITY = {"release": 1, "beta": 2, "alpha": 3}

_jobs: dict = {}
_jobs_lock = threading.Lock()
_apply_lock = threading.Lock()


def _post(url: str, body: dict, headers: dict | None = None) -> dict:
    data = _http_post_json(url, body, headers)
    return data if isinstance(data, dict) else {}


def _get_list(url: str) -> list:
    data = _http_get_json(url)
    return data if isinstance(data, list) else []


def _mod_files(mods_dir: Path) -> list:
    if not mods_dir.is_dir():
        return []
    return sorted((f for f in mods_dir.iterdir()
                   if f.is_file() and f.name.lower().endswith((".jar", ".jar.disabled"))),
                  key=lambda f: f.name.lower())


def _load_hash_cache(server_dir: Path) -> dict:
    try:
        data = json.loads((server_dir / HASH_CACHE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _hashes(server_dir: Path, files: list, need_fingerprint: set, progress=None, prune: bool = True) -> dict:
    """{nombre: {"sha1", "cf"}}; cf solo para los de need_fingerprint (es lento).
    prune: quitar de la caché los jars que ya no están (solo si files es mods/ entero)."""
    cache = _load_hash_cache(server_dir)
    out, changed = {}, False
    for index, path in enumerate(files):
        st = path.stat()
        key = f"{st.st_size}:{int(st.st_mtime)}"
        entry: dict[str, Any] | None = cache.get(path.name)
        if not entry or entry.get("key") != key:
            entry = {"key": key}
            changed = True
        if "sha1" not in entry or (path.name in need_fingerprint and "cf" not in entry):
            data = path.read_bytes()
            entry["sha1"] = hashlib.sha1(data).hexdigest()
            if path.name in need_fingerprint:
                entry["cf"] = curseforge_fingerprint(data)
            changed = True
        cache[path.name] = entry
        out[path.name] = entry
        if progress:
            progress(index + 1, len(files))
    if changed and prune:
        names = {f.name for f in files}
        cache = {k: v for k, v in cache.items() if k in names}
    if changed:
        try:
            atomic_write_text(server_dir / HASH_CACHE_NAME, json.dumps(cache))
        except OSError:
            pass
    return out


# ── Modrinth ──────────────────────────────────────────────────────────────────

def _modrinth_loaders(loader: str | None, mc: str | None) -> list:
    if loader == "quilt":
        return ["quilt", "fabric"]
    if loader == "neoforge" and mc == "1.20.1":
        return ["neoforge", "forge"]
    return [loader] if loader else []


def _primary_file(version: dict) -> dict | None:
    files = version.get("files") or []
    return next((f for f in files if f.get("primary")), files[0] if files else None)


def _newer(candidate: dict, current: dict) -> bool:
    return (candidate.get("id") != current.get("id")
            and (candidate.get("date_published") or "") > (current.get("date_published") or ""))


def _stable_enough(version_type: str | None, current_type: str | None) -> bool:
    return _STABILITY.get(version_type or "release", 3) <= _STABILITY.get(current_type or "release", 3)


def _modrinth_check(hashes: dict, mc: str | None, loader: str | None) -> tuple:
    """Devuelve ({nombre: actualización}, nombres que Modrinth reconoce)."""
    by_hash = {}
    for name, entry in hashes.items():
        by_hash.setdefault(entry["sha1"], []).append(name)
    if not by_hash:
        return {}, set()
    current = _post(f"{MODRINTH}/version_files", {"hashes": list(by_hash), "algorithm": "sha1"})
    known = {name for h in current for name in by_hash.get(h, [])}
    body = {"hashes": list(current), "algorithm": "sha1"}
    loaders = _modrinth_loaders(loader, mc)
    if loaders:
        body["loaders"] = loaders
    if mc:
        body["game_versions"] = [mc]
    latest = _post(f"{MODRINTH}/version_files/update", body) if current else {}

    found = {}
    for sha1, now in current.items():
        best = latest.get(sha1)
        if best and not _stable_enough(best.get("version_type"), now.get("version_type")):
            best = _modrinth_stable_version(now, mc, loaders)
        if not best or not _newer(best, now):
            continue
        file = _primary_file(best)
        if not file or not file.get("url"):
            continue
        for name in by_hash[sha1]:
            found[name] = {
                "source": "modrinth", "project_id": now.get("project_id"),
                "current_version": now.get("version_number"), "new_version": best.get("version_number"),
                "new_filename": file.get("filename"), "download_url": file.get("url"),
                "sha1": (file.get("hashes") or {}).get("sha1"), "release_type": best.get("version_type"),
                "date": best.get("date_published"),
            }
    _modrinth_titles(found)
    return found, known


def _modrinth_stable_version(current: dict, mc: str | None, loaders: list) -> dict | None:
    """La última de la misma estabilidad o mejor (si la más nueva es beta y la tuya no)."""
    params = {}
    if loaders:
        params["loaders"] = json.dumps(loaders)
    if mc:
        params["game_versions"] = json.dumps([mc])
    url = f"{MODRINTH}/project/{urllib.parse.quote(current.get('project_id') or '')}/version"
    try:
        versions = _get_list(url + ("?" + urllib.parse.urlencode(params) if params else ""))
    except ModSearchError:
        return None
    ok = [v for v in versions if _stable_enough(v.get("version_type"), current.get("version_type"))]
    return max(ok, key=lambda v: v.get("date_published") or "", default=None)


def _modrinth_titles(found: dict) -> None:
    ids = sorted({u["project_id"] for u in found.values() if u.get("project_id")})
    if not ids:
        return
    try:
        projects = _get_list(f"{MODRINTH}/projects?ids=" + urllib.parse.quote(json.dumps(ids)))
    except ModSearchError:
        return
    info = {p.get("id"): p for p in projects}
    for update in found.values():
        project = info.get(update.get("project_id")) or {}
        update["title"] = project.get("title")
        if project.get("slug"):
            update["page_url"] = f"https://modrinth.com/{project.get('project_type') or 'mod'}/{project['slug']}"


# ── CurseForge ────────────────────────────────────────────────────────────────

def _curseforge_check(hashes: dict, mc: str | None, loader: str | None) -> tuple:
    by_print = {}
    for name, entry in hashes.items():
        if "cf" in entry:
            by_print.setdefault(entry["cf"], []).append(name)
    if not by_print:
        return {}, set()
    headers = _curseforge_headers()
    data = _post(f"{CURSEFORGE}/fingerprints/{CURSEFORGE_GAME_ID}",
                           {"fingerprints": list(by_print)}, headers).get("data") or {}
    matches = data.get("exactMatches") or []
    known = set()
    current_by_mod = {}
    for match in matches:
        file = match.get("file") or {}
        names = by_print.get(file.get("fileFingerprint"), [])
        known.update(names)
        if names:
            current_by_mod[match.get("id")] = (file, names)
    if not current_by_mod:
        return {}, known

    mods = _post(f"{CURSEFORGE}/mods", {"modIds": list(current_by_mod)}, headers).get("data") or []
    wanted_loaders = {CURSEFORGE_LOADER_TYPES.get(loader)} if loader else set()
    if loader == "neoforge" and mc == "1.20.1":
        wanted_loaders.add(CURSEFORGE_LOADER_TYPES["forge"])
    if loader == "quilt":
        wanted_loaders.add(CURSEFORGE_LOADER_TYPES["fabric"])
    picks = {}
    for mod in mods:
        current, names = current_by_mod.get(mod.get("id"), ({}, []))
        options = [i for i in mod.get("latestFilesIndexes") or []
                   if (not mc or i.get("gameVersion") == mc)
                   and (not wanted_loaders or i.get("modLoader") in wanted_loaders)
                   and (i.get("releaseType") or 3) <= (current.get("releaseType") or 1)
                   and (i.get("fileId") or 0) > (current.get("id") or 0)]
        if options:
            best = max(options, key=lambda i: i["fileId"])
            picks[best["fileId"]] = (mod, current, names)
    if not picks:
        return {}, known

    files = _post(f"{CURSEFORGE}/mods/files", {"fileIds": list(picks)}, headers).get("data") or []
    found = {}
    for file in files:
        mod, current, names = picks.get(file.get("id"), (None, None, []))
        if not mod:
            continue
        sha1 = next((h.get("value") for h in file.get("hashes") or [] if h.get("algo") == 1), None)
        for name in names:
            found[name] = {
                "source": "curseforge", "project_id": mod.get("id"), "title": mod.get("name"),
                "page_url": (mod.get("links") or {}).get("websiteUrl"),
                "current_version": current.get("displayName"), "new_version": file.get("displayName"),
                "new_filename": file.get("fileName"), "download_url": file.get("downloadUrl"),
                "sha1": sha1, "release_type": {1: "release", 2: "beta", 3: "alpha"}.get(file.get("releaseType")),
                "date": file.get("fileDate"),
            }
    return found, known


# ── Comprobación en segundo plano ─────────────────────────────────────────────

def check(modpack: str, progress=None) -> dict:
    server_dir = DEFAULT_SERVERS_PATH / modpack
    info = detect_modpack_version(modpack)
    mc, loader = info.get("mc_version"), loader_key_from_display(info.get("modloader"))
    files = _mod_files(server_dir / "mods")
    say = progress or (lambda *_: None)

    say("hash", 0, len(files))
    hashes = _hashes(server_dir, files, set(), lambda i, n: say("hash", i, n))
    say("modrinth", 0, 0)
    found, known = _modrinth_check(hashes, mc, loader)

    curseforge_used = bool(CURSEFORGE_API_KEY)
    if curseforge_used:
        rest = [f for f in files if f.name not in known]
        if rest:
            say("fingerprint", 0, len(rest))
            prints = _hashes(server_dir, rest, {f.name for f in rest},
                             lambda i, n: say("fingerprint", i, n), prune=False)
            say("curseforge", 0, 0)
            cf_found, cf_known = _curseforge_check(prints, mc, loader)
            found.update(cf_found)
            known |= cf_known

    updates = []
    for path in files:
        update = found.get(path.name)
        if not update:
            continue
        st = path.stat()
        updates.append({
            **update, "filename": path.name, "file_key": f"{st.st_size}:{int(st.st_mtime)}",
            "name": update.get("title") or mod_display_name(path.name),
            "disabled": path.name.endswith(".disabled"),
        })
    return {
        "mc_version": mc, "loader": loader, "total": len(files),
        "known": len(known), "unknown": len(files) - len(known),
        "curseforge": curseforge_used, "updates": updates,
        "checked_at": int(time.time()), "batch": time.strftime("%Y%m%d-%H%M%S"),
    }


def start_check(modpack: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(modpack)
        if job and job["state"] == "running":
            return job
        job = {"state": "running", "stage": "hash", "done": 0, "total": 0, "result": None, "error": None}
        _jobs[modpack] = job

    def progress(stage, done, total):
        job.update(stage=stage, done=done, total=total)

    def run():
        try:
            job["result"] = check(modpack, progress)
            job["state"] = "done"
        except ModSearchError as e:
            job.update(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - se enseña en el panel
            job.update(state="error", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=run, name=f"mod-updates-{modpack}", daemon=True).start()
    return job


def job_status(modpack: str) -> dict | None:
    return _jobs.get(modpack)


# ── Aplicar y deshacer ────────────────────────────────────────────────────────

def _replaced_root(modpack: str) -> Path:
    return DEFAULT_SERVERS_PATH / modpack / REPLACED_DIR_NAME


def _prune_batches(root: Path) -> None:
    batches = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    for old in batches[:-KEEP_REPLACED_BATCHES]:
        shutil.rmtree(old, ignore_errors=True)


def apply_one(modpack: str, filename: str) -> dict:
    """Actualiza un mod de la última comprobación (las URLs no las manda el navegador)."""
    job = _jobs.get(modpack) or {}
    result = job.get("result") or {}
    update = next((u for u in result.get("updates", []) if u["filename"] == filename), None)
    if not update:
        raise ValueError("Ese mod no está en la última comprobación: vuelve a buscar actualizaciones")
    if not update.get("download_url"):
        raise ValueError("El autor no permite descargar este mod desde otras aplicaciones: actualízalo a mano desde su página")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    old = mods_dir / filename
    try:
        st = old.stat()
    except OSError:
        raise ValueError("El archivo del mod ya no está: vuelve a buscar actualizaciones")
    if f"{st.st_size}:{int(st.st_mtime)}" != update["file_key"]:
        raise ValueError("El archivo del mod ha cambiado desde la comprobación: vuelve a buscar actualizaciones")

    new_name = Path(str(update["new_filename"] or "").replace("\\", "/")).name
    if not new_name.lower().endswith(".jar") or new_name.startswith("."):
        raise ValueError("Nombre de archivo de mod inválido")
    if update["disabled"]:
        new_name += ".disabled"
    data = download_bytes(update["download_url"])
    if update.get("sha1") and hashlib.sha1(data).hexdigest() != update["sha1"].lower():
        raise ValueError("El archivo descargado no coincide con el que anuncia la web: no se ha tocado nada")

    with _apply_lock:
        batch_dir = _replaced_root(modpack) / result["batch"]
        batch_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = batch_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = []
        if (mods_dir / new_name).exists() and new_name != filename:
            raise ValueError("Ya hay otro archivo con el nombre de la versión nueva en mods/")
        shutil.move(str(old), str(batch_dir / filename))
        tmp = mods_dir / (new_name + ".part")
        try:
            tmp.write_bytes(data)
            tmp.replace(mods_dir / new_name)
        except OSError:
            tmp.unlink(missing_ok=True)
            shutil.move(str(batch_dir / filename), str(old))
            raise
        manifest.append({"old": filename, "new": new_name, "name": update["name"],
                         "from": update["current_version"], "to": update["new_version"]})
        atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
        _prune_batches(_replaced_root(modpack))
    update["applied"] = True
    return {"filename": filename, "new_filename": new_name, "batch": result["batch"]}


def undo_batch(modpack: str, batch: str) -> dict:
    """Vuelve a poner los jars de un lote y quita los que lo sustituyeron."""
    if not batch or "/" in batch or "\\" in batch or batch.startswith("."):
        raise ValueError("Lote no válido")
    batch_dir = _replaced_root(modpack) / batch
    try:
        manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("No queda nada que deshacer de esa actualización")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    restored = []
    with _apply_lock:
        for item in reversed(manifest):
            saved = batch_dir / item["old"]
            if not saved.is_file():
                continue
            (mods_dir / item["new"]).unlink(missing_ok=True)
            shutil.move(str(saved), str(mods_dir / item["old"]))
            restored.append(item["old"])
        shutil.rmtree(batch_dir, ignore_errors=True)
    _jobs.pop(modpack, None)
    return {"restored": restored}
