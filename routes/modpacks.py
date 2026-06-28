"""
routes/modpacks.py - Endpoints de configuración y contenido de modpacks.

Rutas:
- GET/POST  /api/modpacks/{modpack}/server-properties
- GET/POST  /api/modpacks/{modpack}/config-file
- GET       /api/modpacks/{modpack}/configs
- GET/POST  /api/modpacks/{modpack}/kubejs-file
- GET       /api/modpacks/{modpack}/kubejs
- POST      /api/upload-and-extract
- GET       /api/modpacks/{modpack}/version
- GET       /api/modpacks/{modpack}/mods
- POST      /api/modpacks/{modpack}/mods/upload
- GET       /api/modpacks/{modpack}/detected-mods
- GET       /api/modpacks/{modpack}/worlds
- POST      /api/modpacks/{modpack}/worlds/activate
- POST      /api/modpacks/{modpack}/worlds/create
- DELETE    /api/modpacks/{modpack}/worlds/{world_name}
- GET       /api/modpacks/{modpack}/logs
- GET       /api/modpacks/{modpack}/logs/{filename}
"""
import re
import json
import gzip
import shutil
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse

from config import DEFAULT_SERVERS_PATH, TEMP_DIR
from services.utils import get_mod_configs, get_kubejs_files, extract_archive, configure_jvm_ram
from services.modpack import (
    detect_modpack_version, read_mod_metadata, mc_version_compatible,
    detect_installed_mods, has_mod_keyword,
    parse_server_properties, save_server_property,
    get_worlds, analyze_crash,
)
from services.players import (
    ensure_global_dir, read_global_file, write_global_file, PLAYER_FILES,
)

router = APIRouter(prefix="/api/modpacks", tags=["modpacks"])


# ── server.properties ──────────────────────────────────────────────────────────

@router.get("/{modpack}/server-properties")
async def get_server_properties(modpack: str):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    return JSONResponse({"content": props_file.read_text(encoding="utf-8")})


@router.post("/{modpack}/server-properties")
async def save_server_properties(modpack: str, content: str = Form(...)):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    props_file.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})



@router.post("/{modpack}/server-property")
async def set_server_property(modpack: str, key: str = Form(...), value: str = Form(...)):
    """Actualiza una sola propiedad en server.properties."""
    if not (DEFAULT_SERVERS_PATH / modpack / "server.properties").exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    save_server_property(modpack, key, value)
    return JSONResponse({"success": True, "key": key, "value": value})

# ── Archivos de config ─────────────────────────────────────────────────────────

@router.get("/{modpack}/configs")
async def get_mod_config_list(modpack: str):
    return JSONResponse({"mods": get_mod_configs(modpack)})


@router.get("/{modpack}/config-file")
async def get_config_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "config").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"content": full_path.read_text(encoding="utf-8", errors="replace"), "path": path})


@router.post("/{modpack}/config-file")
async def save_config_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "config").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})


# ── KubeJS ─────────────────────────────────────────────────────────────────────

@router.get("/{modpack}/kubejs")
async def get_kubejs_list(modpack: str):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    exists = kjs_dir.exists()
    return JSONResponse({"exists": exists, "groups": get_kubejs_files(modpack) if exists else {}})


@router.get("/{modpack}/kubejs-file")
async def get_kubejs_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"content": full_path.read_text(encoding="utf-8", errors="replace"), "path": path})


@router.post("/{modpack}/kubejs-file")
async def save_kubejs_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    base = (DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve()
    try:
        full_path.resolve().relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    full_path.write_text(content, encoding="utf-8")
    return JSONResponse({"success": True})


# ── Upload & extract ───────────────────────────────────────────────────────────

upload_router = APIRouter(tags=["modpacks"])

@upload_router.post("/api/upload-and-extract")
async def upload_and_extract(
    file: UploadFile = File(...),
    folder_name: str = Form(...),
    configure_ram: str = Form("0"),
    ram_min: str = Form(""),
    ram_max: str = Form(""),
):
    if not folder_name.strip():
        raise HTTPException(status_code=400, detail="El nombre de carpeta no puede estar vacío")

    dest = DEFAULT_SERVERS_PATH / folder_name.strip()
    temp_file = TEMP_DIR / file.filename
    try:
        import shutil as _shutil
        with open(temp_file, "wb") as buffer:
            _shutil.copyfileobj(file.file, buffer)

        file_size_mb = temp_file.stat().st_size / (1024 * 1024)
        result = extract_archive(temp_file, dest)

        jvm_configured = None
        if configure_ram == "1" and ram_min and ram_max:
            jvm_path = configure_jvm_ram(dest, ram_min, ram_max)
            if jvm_path:
                jvm_configured = f"-Xms{ram_min} / -Xmx{ram_max}"

        # Sincronizar archivos globales de jugadores al nuevo modpack
        ensure_global_dir()
        synced_player_files = []
        for fname in PLAYER_FILES:
            global_data = read_global_file(fname)
            if global_data:
                dest_file = dest / fname
                dest_file.write_text(
                    json.dumps(global_data, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                synced_player_files.append(fname)

        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "size_mb": round(file_size_mb, 2),
            "destination": str(dest),
            "files_extracted": result["files_extracted"],
            "format": result["format"],
            "jvm_configured": jvm_configured,
            "synced_player_files": synced_player_files,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file.exists():
            temp_file.unlink()


# ── Versión y mods ─────────────────────────────────────────────────────────────

@router.get("/{modpack}/version")
async def get_modpack_version(modpack: str):
    return JSONResponse(detect_modpack_version(modpack))


@router.get("/{modpack}/mods")
async def list_mods(modpack: str):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return JSONResponse({"mods": [], "exists": False, "count": 0})
    mods = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".zip") or low.endswith(".jar.disabled")):
            continue
        stem = f.stem if not f.name.endswith(".disabled") else f.stem.replace(".jar", "").replace(".zip", "")
        clean = re.sub(r'[-_+][0-9].*$', '', stem)
        clean = re.sub(r'[-_](forge|fabric|neoforge|mc|minecraft).*$', '', clean, flags=re.IGNORECASE)
        clean = clean.replace("-", " ").replace("_", " ").strip()
        mods.append({"name": clean or stem, "enabled": not f.name.endswith(".disabled")})
    return JSONResponse({"mods": mods, "exists": True, "count": len(mods)})


@router.post("/{modpack}/mods/upload")
async def upload_mod(modpack: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".jar"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .jar")
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")
    dest = mods_dir / file.filename
    if dest.exists():
        raise HTTPException(status_code=400, detail=f"{file.filename} ya existe en mods/")

    jar_bytes = await file.read()
    server_info = detect_modpack_version(modpack)
    server_mc = server_info.get("mc_version")
    meta = read_mod_metadata(jar_bytes)

    if server_mc and meta["mc_versions"]:
        if not mc_version_compatible(server_mc, meta["mc_versions"]):
            raise HTTPException(
                status_code=409,
                detail=f"Incompatible: el mod requiere MC {', '.join(meta['mc_versions'])} pero el servidor es {server_mc}"
            )

    dest.write_bytes(jar_bytes)
    return JSONResponse({
        "success": True,
        "filename": file.filename,
        "mod_id": meta.get("mod_id"),
        "mod_version": meta.get("mod_version"),
        "mod_mc_versions": meta.get("mc_versions"),
        "server_mc": server_mc,
        "size_kb": round(len(jar_bytes) / 1024, 1),
    })


@router.get("/{modpack}/detected-mods")
async def detected_mods(modpack: str):
    names = detect_installed_mods(modpack)
    return JSONResponse({
        "has_biomesoplenty": has_mod_keyword(names, "biomesoplenty") or has_mod_keyword(names, "biomes-o-plenty"),
        "has_create": has_mod_keyword(names, "create"),
        "has_jei": has_mod_keyword(names, "jei"),
        "has_rei": has_mod_keyword(names, "rei"),
        "has_waystones": has_mod_keyword(names, "waystones"),
        "has_spark": has_mod_keyword(names, "spark"),
        "mod_count": len(names),
    })


# ── Mundos ─────────────────────────────────────────────────────────────────────

@router.get("/{modpack}/worlds")
async def list_worlds(modpack: str):
    worlds_info = get_worlds(modpack)
    props = parse_server_properties(modpack)
    return JSONResponse({
        **worlds_info,
        "level_type": props.get("level-type", "minecraft:normal"),
        "seed": props.get("level-seed", ""),
    })


@router.post("/{modpack}/worlds/activate")
async def activate_world(modpack: str, world_name: str = Form(...)):
    base = DEFAULT_SERVERS_PATH / modpack
    if not (base / world_name).exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "active": world_name})


@router.post("/{modpack}/worlds/create")
async def create_world(
    modpack: str,
    world_name: str = Form(...),
    level_type: str = Form("minecraft:normal"),
    seed: str = Form(""),
    activate: str = Form("1"),
):
    if not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
        raise HTTPException(status_code=400, detail="Nombre de mundo inválido (solo letras, números, _ y -)")
    base = DEFAULT_SERVERS_PATH / modpack
    if (base / world_name).exists():
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre")
    save_server_property(modpack, "level-type", level_type)
    save_server_property(modpack, "level-seed", seed)
    if activate == "1":
        save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "world_name": world_name, "message": "Mundo configurado. Se generará al iniciar el servidor."})


@router.delete("/{modpack}/worlds/{world_name}")
async def delete_world(modpack: str, world_name: str):
    base = DEFAULT_SERVERS_PATH / modpack
    world_path = base / world_name
    try:
        world_path.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not world_path.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    props = parse_server_properties(modpack)
    if world_name == props.get("level-name", "world"):
        raise HTTPException(status_code=400, detail="No puedes borrar el mundo activo. Cambia a otro primero.")
    shutil.rmtree(world_path)
    for suffix in ["_nether", "_the_end"]:
        sibling = base / (world_name + suffix)
        if sibling.exists():
            shutil.rmtree(sibling)
    return JSONResponse({"success": True})


# ── Logs & crash reports ───────────────────────────────────────────────────────

@router.get("/{modpack}/logs")
async def get_log_list(modpack: str):
    base = DEFAULT_SERVERS_PATH / modpack
    logs = []
    if (base / "logs").exists():
        for f in sorted((base / "logs").iterdir(), reverse=True):
            if f.is_file() and f.suffix in {".log", ".gz", ".txt"}:
                logs.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "log"})
    crashes = []
    if (base / "crash-reports").exists():
        for f in sorted((base / "crash-reports").iterdir(), reverse=True):
            if f.is_file():
                crashes.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "crash"})
    return JSONResponse({"logs": logs[:20], "crashes": crashes[:30]})


@router.get("/{modpack}/logs/{filename}")
async def get_log_file(modpack: str, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=403, detail="Nombre de archivo inválido")
    base = DEFAULT_SERVERS_PATH / modpack
    file_path = next(
        (c for c in [base / "logs" / filename, base / "crash-reports" / filename] if c.exists()),
        None
    )
    if file_path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if filename.endswith(".gz"):
        with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    else:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    culprits = analyze_crash(raw, modpack)
    return JSONResponse({"content": raw, "culprits": culprits, "filename": filename})


# ── Firewall (ufw) ─────────────────────────────────────────────────────────────

firewall_router = APIRouter(tags=["firewall"])

@firewall_router.post("/api/firewall/set")
async def set_firewall(mode: str = Form(...)):
    """
    Configura ufw para el puerto 25565.
    mode='lan'    → solo red local (192.168.1.0/24)
    mode='public' → acceso desde cualquier IP
    """
    import subprocess

    if mode not in ("lan", "public"):
        raise HTTPException(status_code=400, detail="mode debe ser 'lan' o 'public'")

    def run(cmd: list) -> tuple[int, str]:
        r = subprocess.run(["sudo"] + cmd, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    # Primero limpiar reglas existentes del 25565
    run(["ufw", "delete", "allow", "25565"])
    run(["ufw", "delete", "allow", "from", "192.168.1.0/24", "to", "any", "port", "25565"])

    if mode == "public":
        code, out = run(["ufw", "allow", "25565"])
    else:
        code, out = run(["ufw", "allow", "from", "192.168.1.0/24", "to", "any", "port", "25565"])

    if code != 0:
        raise HTTPException(status_code=500, detail=f"Error ejecutando ufw: {out}")

    return JSONResponse({"success": True, "mode": mode})


@firewall_router.get("/api/firewall/status")
async def firewall_status():
    """Devuelve el modo actual del firewall para el puerto 25565."""
    import subprocess
    r = subprocess.run(["sudo", "ufw", "status"], capture_output=True, text=True)
    output = r.stdout

    # Detectar si hay regla pública (ALLOW Anywhere en 25565)
    lines = output.splitlines()
    has_public = any("25565" in l and "Anywhere" in l and "ALLOW" in l for l in lines)
    has_lan    = any("25565" in l and "192.168.1.0/24" in l for l in lines)

    if has_public:
        mode = "public"
    elif has_lan:
        mode = "lan"
    else:
        mode = "unknown"

    return JSONResponse({"mode": mode, "ufw_output": output})
