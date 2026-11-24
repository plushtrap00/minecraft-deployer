"""
services/client_pack.py - Paquete para jugadores: el modpack del servidor listo
para instalarlo en un launcher, con los mismos mods que el servidor.

Dos formatos:
- "curseforge": .zip con manifest.json (app de CurseForge, Prism, ATLauncher).
- "mrpack": .mrpack con modrinth.index.json (Modrinth App, Prism).

Qué lleva:
1. Los mods activos de mods/ (y los desactivados que sean solo de cliente: el
   panel los desactiva en el servidor, pero el jugador sí los quiere). Cada jar
   se identifica por su contenido (services/mod_updates.py): si la plataforma
   del formato lo conoce, el paquete solo lo referencia y el launcher lo baja;
   si no, el jar va dentro del paquete (overrides/mods/).
   Se quitan los que son solo de servidor (Modrinth: client_side
   "unsupported"; Fabric/Quilt: "environment": "server").
2. Si el servidor está vinculado a su modpack original (.pack_source.json), lo
   del modpack que el servidor no usa: mods solo de cliente, resource packs,
   shaders... (lo que el modpack trae y el servidor no tiene ni tuvo nunca:
   lo que quitaste tú a propósito no vuelve) y sus overrides (config/,
   kubejs/...), que son los del modpack para jugadores. Las configuraciones
   del servidor no se meten nunca: pueden llevar tokens y contraseñas.

El paquete se genera en segundo plano (puede tardar la primera vez: hay que
leer todos los jars) y se guarda en <servidor>/.client-pack/ con un .json al
lado que dice con qué mods se hizo; si los mods cambian, el panel lo marca
como desactualizado.
"""
import hashlib
import json
import re
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path

from config import CURSEFORGE_API_KEY, DEFAULT_SERVERS_PATH
from services import mod_updates, modpack_update
from services.mod_checks import classify_mod_side
from services.mod_metadata import read_mod_metadata
from services.mod_search import ModSearchError, download_bytes
from services.modloader import loader_key_from_display
from services.modpack import detect_modpack_version
from services.secure_files import atomic_write_text

OUT_DIR = ".client-pack"
FORMATS = {"curseforge": ".zip", "mrpack": ".mrpack"}
MODRINTH = mod_updates.MODRINTH
CURSEFORGE = mod_updates.CURSEFORGE
_CHUNK = 100
_MRPACK_LOADER_KEYS = {"forge": "forge", "neoforge": "neoforge", "fabric": "fabric-loader", "quilt": "quilt-loader"}
# classId de CurseForge -> carpeta de la instancia del jugador.
_CF_CLASS_FOLDERS = {6: "mods", 12: "resourcepacks", 6552: "shaderpacks"}
_MANIFEST_OVERRIDES = ("overrides", "client-overrides")

_jobs: dict = {}
_jobs_lock = threading.Lock()


class ClientPackError(RuntimeError):
    pass


# ── Utilidades ────────────────────────────────────────────────────────────────

def _server_dir(modpack: str) -> Path:
    return DEFAULT_SERVERS_PATH / modpack


def _out_paths(modpack: str, fmt: str) -> tuple[Path, Path]:
    folder = _server_dir(modpack) / OUT_DIR
    return folder / f"{modpack}{FORMATS[fmt]}", folder / f"{fmt}.json"


def _mods_key(modpack: str) -> str:
    """Huella de mods/ (nombres, tamaños y fechas) y de la versión del modpack vinculada."""
    files = mod_updates._mod_files(_server_dir(modpack) / "mods")
    parts = [f"{f.name}:{f.stat().st_size}:{int(f.stat().st_mtime)}" for f in files]
    source = modpack_update.read_source(modpack) or {}
    parts.append(f"source:{source.get('source')}:{source.get('version_id')}")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _client_name(filename: str) -> str:
    return filename[:-len(".disabled")] if filename.endswith(".disabled") else filename


def _version_label(source: dict | None) -> str:
    if source and source.get("version_number"):
        return str(source["version_number"])
    return time.strftime("%Y-%m-%d")


# ── Qué lleva el paquete ──────────────────────────────────────────────────────

def _side_excluded(path: Path, loader: str | None) -> bool:
    """Solo de servidor según sus propios metadatos (Fabric/Quilt lo declaran)."""
    if loader not in ("fabric", "quilt"):
        return False
    try:
        meta = read_mod_metadata(path.read_bytes())
    except OSError:
        return False
    return meta.get("side") == "server"


def _is_client_only(path: Path) -> bool:
    try:
        return classify_mod_side(read_mod_metadata(path.read_bytes())).get("category") == "client_only"
    except OSError:
        return False


def _server_jars(modpack: str) -> list[Path]:
    """Activos + desactivados que son solo de cliente."""
    jars = []
    for path in mod_updates._mod_files(_server_dir(modpack) / "mods"):
        if path.name.endswith(".disabled") and not _is_client_only(path):
            continue
        jars.append(path)
    return jars


def _modrinth_lookup(hashes: dict) -> dict:
    """{nombre: {"version", "file", "client_side"}} de los jars que Modrinth conoce."""
    by_hash: dict = {}
    for name, entry in hashes.items():
        by_hash.setdefault(entry["sha1"], []).append(name)
    if not by_hash:
        return {}
    versions = mod_updates._post(f"{MODRINTH}/version_files", {"hashes": list(by_hash), "algorithm": "sha1"})
    project_ids = sorted({v.get("project_id") for v in versions.values() if v.get("project_id")})
    sides = {}
    for chunk in _chunks(project_ids):
        url = f"{MODRINTH}/projects?ids=" + urllib.parse.quote(json.dumps(chunk))
        for project in mod_updates._get_list(url):
            sides[project.get("id")] = project.get("client_side")
    found = {}
    for sha1, version in versions.items():
        file = next((f for f in version.get("files") or [] if (f.get("hashes") or {}).get("sha1") == sha1), None)
        if not file or not file.get("url"):
            continue
        for name in by_hash[sha1]:
            found[name] = {"version": version, "file": file, "client_side": sides.get(version.get("project_id"))}
    return found


def _curseforge_lookup(hashes: dict) -> dict:
    """{nombre: {"project_id", "file_id", "download_url"}} de los jars que CurseForge conoce."""
    by_print: dict = {}
    for name, entry in hashes.items():
        if "cf" in entry:
            by_print.setdefault(entry["cf"], []).append(name)
    if not by_print:
        return {}
    from services.mod_search import _curseforge_headers
    headers = _curseforge_headers()
    found = {}
    for chunk in _chunks(list(by_print), 500):
        data = mod_updates._post(f"{CURSEFORGE}/fingerprints/432", {"fingerprints": chunk}, headers).get("data") or {}
        for match in data.get("exactMatches") or []:
            file = match.get("file") or {}
            for name in by_print.get(file.get("fileFingerprint"), []):
                found[name] = {"project_id": match.get("id"), "file_id": file.get("id"),
                               "download_url": file.get("downloadUrl")}
    return found


def _original_pack(source: dict, on_server: set, say) -> dict:
    """
    Lo que aporta el modpack original: {"files": [...], "overrides": {ruta: bytes},
    "client_mods": nombres de todos los mods que el modpack pone en el cliente}.
    Cada file: {"folder", "filename", y "cf": {project_id, file_id, download_url}
    o "mr": entrada del modrinth.index.json}.
    """
    pack_mods = set(source.get("pack_mods") or [])

    def wanted(folder: str, filename: str) -> bool:
        # Un mod que el servidor no tiene y que el modpack no le puso (o sea,
        # que el panel se saltó por ser de cliente). Lo que no es un mod
        # (resource packs, shaders) no va nunca al servidor: siempre.
        if folder != "mods":
            return True
        return filename not in on_server and filename not in pack_mods

    files, overrides, client_mods = [], {}, set()
    if source["source"] == "curseforge":
        say("original", 0, 0)
        from services.pack_install_curseforge import (
            _download_curseforge_pack_zip, _resolve_curseforge_file_urls, _resolve_curseforge_projects,
        )
        zf, _ = _download_curseforge_pack_zip(int(source["project_id"]), int(source["version_id"]))
        manifest = json.loads(zf.read("manifest.json"))
        refs = [f for f in manifest.get("files", []) if f.get("fileID") and f.get("projectID")]
        resolved = _resolve_curseforge_file_urls([f["fileID"] for f in refs])
        projects = _resolve_curseforge_projects(list({f["projectID"] for f in refs}))
        for ref in refs:
            info = resolved.get(ref["fileID"]) or {}
            folder = _CF_CLASS_FOLDERS.get((projects.get(ref["projectID"]) or {}).get("classId", 6))
            filename = info.get("fileName")
            if folder == "mods" and filename:
                client_mods.add(filename)
            if folder and filename and wanted(folder, filename):
                files.append({"folder": folder, "filename": filename,
                              "cf": {"project_id": ref["projectID"], "file_id": ref["fileID"],
                                     "download_url": info.get("downloadUrl")}})
        prefixes = (manifest.get("overrides") or "overrides",)
    else:
        say("original", 0, 0)
        from services.pack_install_modrinth import _get_modrinth_pack_index
        index, zf = _get_modrinth_pack_index(str(source["project_id"]), str(source["version_id"]))
        for entry in index.get("files") or []:
            if (entry.get("env") or {}).get("client") == "unsupported":
                continue
            folder, _, filename = (entry.get("path") or "").rpartition("/")
            if folder == "mods":
                client_mods.add(filename)
            if folder in ("mods", "resourcepacks", "shaderpacks") and wanted(folder, filename):
                files.append({"folder": folder, "filename": filename, "mr": entry})
        prefixes = _MANIFEST_OVERRIDES

    for info in zf.infolist():
        if info.is_dir():
            continue
        prefix = next((p for p in prefixes if info.filename.startswith(p + "/")), None)
        if not prefix:
            continue
        rel = info.filename[len(prefix) + 1:]
        if not rel or ".." in rel.split("/") or rel.startswith("/"):
            continue
        if rel.startswith("mods/"):
            client_mods.add(rel[len("mods/"):])
            if not wanted("mods", rel[len("mods/"):]):
                continue
        overrides[rel] = zf.read(info)
    zf.close()
    return {"files": files, "overrides": overrides, "client_mods": client_mods}


def _plan(modpack: str, fmt: str, say) -> dict:
    server_dir = _server_dir(modpack)
    info = detect_modpack_version(modpack)
    source = modpack_update.read_source(modpack)
    mc = info.get("mc_version") or (source or {}).get("mc_version")
    loader = loader_key_from_display(info.get("modloader")) or (source or {}).get("loader")
    loader_version = info.get("modloader_version")
    if not mc or not loader or not loader_version:
        raise ClientPackError("No se ha podido saber la versión de Minecraft o del modloader de este servidor")

    jars = _server_jars(modpack)
    all_files = mod_updates._mod_files(server_dir / "mods")
    say("hash", 0, len(jars))
    need_cf = {p.name for p in jars} if fmt == "curseforge" and CURSEFORGE_API_KEY else set()
    hashes = mod_updates._hashes(server_dir, jars, need_cf, lambda i, n: say("hash", i, n), prune=False)

    say("modrinth", 0, 0)
    mr = _modrinth_lookup(hashes)
    cf = {}
    if need_cf:
        say("curseforge", 0, 0)
        cf = _curseforge_lookup(hashes)

    original = {"files": [], "overrides": {}, "client_mods": set()}
    original_error = None
    if source and source["source"] == "curseforge" and not CURSEFORGE_API_KEY:
        original_error = "CurseForge no está configurado"
    elif source:
        on_server = {_client_name(p.name) for p in all_files}
        try:
            original = _original_pack(source, on_server, say)
        except Exception as e:  # noqa: BLE001 - sin el modpack original el paquete sigue sirviendo
            original_error = str(e) or type(e).__name__

    entries, excluded = [], []
    for path in jars:
        name = _client_name(path.name)
        mr_info = mr.get(path.name)
        # Si el modpack original lo pone en el cliente, va (aunque Modrinth diga que
        # es solo de servidor: quitarlo podría impedir entrar). Si no, se mira Modrinth
        # y, en Fabric/Quilt, lo que declara el propio mod.
        server_only = (mr_info and mr_info["client_side"] == "unsupported") or _side_excluded(path, loader)
        if server_only and name not in original["client_mods"]:
            excluded.append(name)
            continue
        entries.append({"folder": "mods", "filename": name, "path": path, "mr": mr_info, "cf": cf.get(path.name)})

    return {"modpack": modpack, "mc": mc, "loader": loader, "loader_version": loader_version,
            "version": _version_label(source), "source": source,
            "title": (source or {}).get("title") or modpack,
            "entries": entries, "excluded": excluded, "original": original, "original_error": original_error}


# ── Escritura ─────────────────────────────────────────────────────────────────

def _write_curseforge(plan: dict, out: Path) -> dict:
    files, bundled, manual = [], [], []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in plan["entries"]:
            if entry["cf"]:
                files.append({"projectID": entry["cf"]["project_id"], "fileID": entry["cf"]["file_id"], "required": True})
            else:
                zf.write(entry["path"], f"overrides/mods/{entry['filename']}", compress_type=zipfile.ZIP_STORED)
                bundled.append(entry["filename"])
        extras = 0
        for item in plan["original"]["files"]:
            if item.get("cf"):
                files.append({"projectID": item["cf"]["project_id"], "fileID": item["cf"]["file_id"], "required": True})
                extras += 1
            elif _bundle_download(zf, item, manual):
                extras += 1
        for rel, data in plan["original"]["overrides"].items():
            zf.writestr(f"overrides/{rel}", data)
        manifest = {
            "minecraft": {"version": plan["mc"],
                          "modLoaders": [{"id": f"{plan['loader']}-{plan['loader_version']}", "primary": True}]},
            "manifestType": "minecraftModpack", "manifestVersion": 1,
            "name": plan["title"], "version": plan["version"], "author": "Minecraft Server Deployer",
            "files": files, "overrides": "overrides",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return {"linked": len(files) - extras, "bundled": bundled, "extras": extras, "manual": manual}


def _write_mrpack(plan: dict, out: Path) -> dict:
    files, bundled, manual = [], [], []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in plan["entries"]:
            mr = entry["mr"]
            if mr:
                file = mr["file"]
                files.append({"path": f"mods/{entry['filename']}",
                              "hashes": {"sha1": file["hashes"]["sha1"], "sha512": file["hashes"]["sha512"]},
                              "env": {"client": "required", "server": "required"},
                              "downloads": [file["url"]], "fileSize": file.get("size")})
            else:
                zf.write(entry["path"], f"overrides/mods/{entry['filename']}", compress_type=zipfile.ZIP_STORED)
                bundled.append(entry["filename"])
        extras = 0
        for item in plan["original"]["files"]:
            if item.get("mr"):
                files.append({**item["mr"], "env": {"client": "required", "server": "unsupported"}})
                extras += 1
            elif _bundle_download(zf, item, manual):
                extras += 1
        for rel, data in plan["original"]["overrides"].items():
            zf.writestr(f"overrides/{rel}", data)
        index = {
            "formatVersion": 1, "game": "minecraft", "versionId": plan["version"], "name": plan["title"],
            "summary": "Generado por Minecraft Server Deployer",
            "files": files,
            "dependencies": {"minecraft": plan["mc"], _MRPACK_LOADER_KEYS[plan["loader"]]: plan["loader_version"]},
        }
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False))
    return {"linked": len(files) - extras, "bundled": bundled, "extras": extras, "manual": manual}


def _bundle_download(zf: zipfile.ZipFile, item: dict, manual: list) -> bool:
    """Un archivo del modpack original que el formato no puede referenciar: se baja y va dentro."""
    url = (item.get("cf") or {}).get("download_url") or ((item.get("mr") or {}).get("downloads") or [None])[0]
    if not url:
        manual.append(item["filename"])
        return False
    try:
        zf.writestr(f"overrides/{item['folder']}/{item['filename']}", download_bytes(url))
        return True
    except ModSearchError:
        manual.append(item["filename"])
        return False


def build(modpack: str, fmt: str, progress=None) -> dict:
    if fmt not in FORMATS:
        raise ClientPackError("Formato de paquete desconocido")
    say = progress or (lambda *_: None)
    key = _mods_key(modpack)
    plan = _plan(modpack, fmt, say)
    out, meta_path = _out_paths(modpack, fmt)
    out.parent.mkdir(exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    say("write", 0, 0)
    writer = _write_curseforge if fmt == "curseforge" else _write_mrpack
    try:
        result = writer(plan, tmp)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    meta = {
        "format": fmt, "built_at": int(time.time()), "mods_key": key, "size": out.stat().st_size,
        "mc_version": plan["mc"], "loader": plan["loader"], "loader_version": plan["loader_version"],
        "version": plan["version"], "linked_source": bool(plan["source"]),
        "original_error": plan["original_error"],
        "mods": len(plan["entries"]), "excluded": sorted(plan["excluded"]),
        "overrides": len(plan["original"]["overrides"]), **result,
    }
    meta["bundled"] = sorted(meta["bundled"])
    atomic_write_text(meta_path, json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


# ── Trabajo en segundo plano y estado ─────────────────────────────────────────

def start(modpack: str, fmt: str) -> dict:
    if fmt not in FORMATS:
        raise ClientPackError("Formato de paquete desconocido")
    with _jobs_lock:
        running = next((j for (m, _), j in _jobs.items() if m == modpack and j["state"] == "running"), None)
        if running:
            return running
        job = {"state": "running", "format": fmt, "stage": "hash", "done": 0, "total": 0, "error": None}
        _jobs[(modpack, fmt)] = job

    def progress(stage, done, total):
        job.update(stage=stage, done=done, total=total)

    def run():
        try:
            build(modpack, fmt, progress)
            job["state"] = "done"
        except (ClientPackError, ModSearchError) as e:
            job.update(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - se enseña en el panel
            job.update(state="error", error=f"{type(e).__name__}: {e}")

    threading.Thread(target=run, name=f"client-pack-{modpack}-{fmt}", daemon=True).start()
    return job


def status(modpack: str) -> dict:
    key = _mods_key(modpack)
    formats = {}
    for fmt in FORMATS:
        out, meta_path = _out_paths(modpack, fmt)
        meta = None
        if out.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["stale"] = meta.get("mods_key") != key
                meta.pop("mods_key", None)
            except (OSError, ValueError):
                meta = None
        job = _jobs.get((modpack, fmt))
        formats[fmt] = {"file": meta, "job": {k: job[k] for k in ("state", "stage", "done", "total", "error")} if job else None}
    source = modpack_update.read_source(modpack)
    # Recomendado: el de la plataforma de la que viene el modpack (sus mods están
    # ahí, así que el paquete casi no lleva jars dentro y pesa mucho menos).
    return {"formats": formats, "linked": source is not None,
            "recommended": "mrpack" if (source or {}).get("source") == "modrinth" else "curseforge",
            "curseforge_key": bool(CURSEFORGE_API_KEY)}


def file_for_download(modpack: str, fmt: str) -> Path | None:
    if fmt not in FORMATS:
        return None
    out, _ = _out_paths(modpack, fmt)
    return out if out.exists() else None


def download_name(modpack: str, fmt: str) -> str:
    safe = re.sub(r"[^\w.-]+", "_", modpack).strip("_") or "modpack"
    return f"{safe}-jugadores{FORMATS[fmt]}"
