import os
import json
import re
import shutil
import zipfile
import tarfile
import asyncio
import threading
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import uvicorn

# ── Server process state ───────────────────────────────────────────────────────
mc_process = None
mc_process_lock = threading.Lock()
mc_output_lines = []          # rolling buffer of last 500 lines
mc_output_lock = threading.Lock()
mc_sse_clients = set()        # active SSE connections
mc_sse_lock = threading.Lock()
mc_running_modpack = None
MAX_LINES = 500

def _broadcast(line):
    with mc_output_lock:
        mc_output_lines.append(line)
        if len(mc_output_lines) > MAX_LINES:
            mc_output_lines.pop(0)
    with mc_sse_lock:
        dead = set()
        for q in mc_sse_clients:
            try:
                q.put_nowait(line)
            except Exception:
                dead.add(q)
        mc_sse_clients.difference_update(dead)


def _accept_eula(server_dir: Path):
    eula_file = server_dir / "eula.txt"
    if not eula_file.exists():
        return False
    text = eula_file.read_text(encoding="utf-8")
    if "eula=true" in text.lower():
        return False  # already accepted
    new_text = text.replace("eula=false", "eula=true").replace("eula=False", "eula=true")
    eula_file.write_text(new_text, encoding="utf-8")
    return True


def _reader_thread(proc, temp_script=None):
    """Reads stdout+stderr from the MC process and fans out to SSE clients."""
    global mc_process, mc_running_modpack, mc_start_time
    eula_handled = False
    import datetime
    mc_start_time = datetime.datetime.utcnow()
    # Reset metrics
    mc_metrics["players_online"] = []
    mc_metrics["tps"] = None
    mc_metrics["mspt"] = None
    mc_metrics["ram_used_mb"] = None
    # Detect spark by checking mods/ folder at startup
    if mc_running_modpack:
        mods_dir = DEFAULT_SERVERS_PATH / mc_running_modpack / "mods"
        spark_found = False
        if mods_dir.exists():
            for f in mods_dir.iterdir():
                if "spark" in f.name.lower() and f.suffix.lower() == ".jar":
                    spark_found = True
                    break
        mc_metrics["spark_available"] = spark_found
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            _broadcast(line)
            _parse_metrics_line(line)
            # Detect EULA rejection and handle it
            if not eula_handled and "you need to agree to the eula" in line.lower():
                eula_handled = True
                server_dir = DEFAULT_SERVERS_PATH / mc_running_modpack
                if _accept_eula(server_dir):
                    _broadcast("\x1b[33m[Deployer] EULA aceptada automáticamente. Reiniciando servidor...\x1b[0m")
    finally:
        proc.wait()
        if temp_script:
            try:
                os.unlink(temp_script)
            except Exception:
                pass
        mc_start_time = None
        mc_metrics["players_online"] = []
        mc_metrics["tps"] = None
        mc_metrics["spark_available"] = False
        mc_metrics["cpu_process"] = None
        mc_metrics["cpu_system"] = None
        _notify_stopped()

def _notify_stopped():
    global mc_process, mc_running_modpack
    with mc_process_lock:
        mc_process = None
        mc_running_modpack = None
    line = "\x1b[33m[Deployer] Servidor detenido.\x1b[0m"
    with mc_output_lock:
        mc_output_lines.append(line)
    with mc_sse_lock:
        for q in mc_sse_clients:
            try:
                q.put_nowait(line)
                q.put_nowait("__STOPPED__")
            except Exception:
                pass

app = FastAPI(title="Minecraft Server Deployer")

TEMP_DIR = Path("uploads_temp")
TEMP_DIR.mkdir(exist_ok=True)

DEFAULT_SERVERS_PATH = Path.home() / "servers-minecraft"
DEFAULT_SERVERS_PATH.mkdir(exist_ok=True)

CONFIG_EXTENSIONS = {".toml", ".cfg", ".json", ".yaml", ".yml", ".properties"}


# ── Utilidades ─────────────────────────────────────────────────────────────────

def get_system_ram_gb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    return None


def get_modpacks():
    packs = []
    if DEFAULT_SERVERS_PATH.exists():
        for item in sorted(DEFAULT_SERVERS_PATH.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                packs.append(item.name)
    return packs


def get_mod_configs(modpack_name: str):
    config_dir = DEFAULT_SERVERS_PATH / modpack_name / "config"
    if not config_dir.exists():
        return {}

    mods = {}

    for path in sorted(config_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in CONFIG_EXTENSIONS:
            continue

        # Determinar nombre del mod: subcarpeta directa bajo config, o "root"
        rel = path.relative_to(config_dir)
        parts = rel.parts
        if len(parts) == 1:
            mod_key = "__root__"
        else:
            mod_key = parts[0]

        if mod_key not in mods:
            mods[mod_key] = []
        mods[mod_key].append(str(rel))

    return mods


KUBEJS_EXTENSIONS = {".js", ".ts", ".json", ".yaml", ".yml", ".txt", ".md"}

def get_kubejs_files(modpack_name: str):
    kubejs_dir = DEFAULT_SERVERS_PATH / modpack_name / "kubejs"
    if not kubejs_dir.exists():
        return {}
    groups = {}
    for path in sorted(kubejs_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in KUBEJS_EXTENSIONS:
            continue
        rel = path.relative_to(kubejs_dir)
        parts = rel.parts
        group = parts[0] if len(parts) > 1 else "__root__"
        if group not in groups:
            groups[group] = []
        groups[group].append(str(rel))
    return groups

def extract_archive(archive_path: Path, dest_path: Path):
    dest_path.mkdir(parents=True, exist_ok=True)
    filename = archive_path.name.lower()

    if filename.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            total = len(zf.namelist())
            zf.extractall(dest_path)
        return {"files_extracted": total, "format": "ZIP"}
    elif filename.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tf:
            total = len(tf.getnames())
            tf.extractall(dest_path)
        return {"files_extracted": total, "format": "TAR.GZ"}
    elif filename.endswith(".tar.bz2"):
        with tarfile.open(archive_path, "r:bz2") as tf:
            total = len(tf.getnames())
            tf.extractall(dest_path)
        return {"files_extracted": total, "format": "TAR.BZ2"}
    elif filename.endswith(".tar"):
        with tarfile.open(archive_path, "r:") as tf:
            total = len(tf.getnames())
            tf.extractall(dest_path)
        return {"files_extracted": total, "format": "TAR"}
    elif filename.endswith(".rar"):
        try:
            import rarfile
            with rarfile.RarFile(archive_path, "r") as rf:
                total = len(rf.namelist())
                rf.extractall(dest_path)
            return {"files_extracted": total, "format": "RAR"}
        except ImportError:
            result = os.system("unrar x '" + str(archive_path) + "' '" + str(dest_path) + "/'")
            if result != 0:
                raise HTTPException(status_code=500, detail="Para RAR instala: pip install rarfile && sudo apt install unrar")
            return {"files_extracted": -1, "format": "RAR (via unrar)"}
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado: " + filename)


def configure_jvm_ram(dest_path: Path, ram_min: str, ram_max: str):
    # Search priority: user_jvm_args.txt (root/subdir), then variables.txt (root/subdir)
    jvm_file = None
    jvm_type = None
    for pattern in ["user_jvm_args.txt", "*/user_jvm_args.txt"]:
        candidates = list(dest_path.glob(pattern))
        if candidates:
            jvm_file = candidates[0]
            jvm_type = "jvm_args"
            break
    if jvm_file is None:
        for pattern in ["variables.txt", "*/variables.txt"]:
            candidates = list(dest_path.glob(pattern))
            if candidates:
                jvm_file = candidates[0]
                jvm_type = "variables"
                break
    if jvm_file is None:
        return None

    with open(jvm_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    xms_found = False
    xmx_found = False

    if jvm_type == "jvm_args":
        # Format: bare flags, one per line (-Xms4G, -Xmx8G, -XX:...)
        for line in lines:
            stripped = line.strip()
            if re.match(r'^-Xms', stripped, re.IGNORECASE):
                new_lines.append("-Xms" + ram_min + "\n")
                xms_found = True
            elif re.match(r'^-Xmx', stripped, re.IGNORECASE):
                new_lines.append("-Xmx" + ram_max + "\n")
                xmx_found = True
            else:
                new_lines.append(line)
        if not xms_found:
            new_lines.insert(0, "-Xms" + ram_min + "\n")
        if not xmx_found:
            new_lines.insert(0 if not xms_found else 1, "-Xmx" + ram_max + "\n")

    elif jvm_type == "variables":
        # Format: KEY=value pairs. JAVA_ARGS="-Xmx4G -Xms4G ..."
        for line in lines:
            stripped = line.strip()
            if re.match(r'^JAVA_ARGS\s*=', stripped):
                # Detect if value is quoted: JAVA_ARGS="..." or JAVA_ARGS=...
                m_quoted = re.match(r'^(JAVA_ARGS\s*=\s*)"(.*)"\s*$', stripped)
                m_plain  = re.match(r'^(JAVA_ARGS\s*=\s*)(.*)$', stripped)
                if m_quoted:
                    key_part = m_quoted.group(1)
                    args = m_quoted.group(2)
                    quoted = True
                elif m_plain:
                    key_part = m_plain.group(1)
                    args = m_plain.group(2)
                    quoted = False
                else:
                    new_lines.append(line)
                    continue
                # Replace existing Xms/Xmx
                args = re.sub(r'-Xms\S+', '-Xms' + ram_min, args, flags=re.IGNORECASE)
                args = re.sub(r'-Xmx\S+', '-Xmx' + ram_max, args, flags=re.IGNORECASE)
                # Add if not present
                if '-Xms' not in args:
                    args = '-Xms' + ram_min + ' ' + args
                if '-Xmx' not in args:
                    args = '-Xmx' + ram_max + ' ' + args
                # Preserve original quoting style
                if quoted:
                    new_lines.append(key_part + '"' + args + '"' + "\n")
                else:
                    new_lines.append(key_part + args + "\n")
                xms_found = True
                xmx_found = True
            else:
                new_lines.append(line)

    with open(jvm_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return str(jvm_file)


# ── Rutas ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r") as fh:
        html = fh.read()
    return HTMLResponse(content=html)


@app.get("/api/system-info")
async def system_info():
    ram_gb = get_system_ram_gb()
    max_allowed = None
    if ram_gb:
        max_allowed = round(ram_gb * 0.8, 1)
    return JSONResponse({
        "ram_total_gb": ram_gb,
        "ram_max_allowed_gb": max_allowed,
    })


@app.get("/api/modpacks")
async def list_modpacks():
    packs = get_modpacks()
    result = []
    for name in packs:
        path = DEFAULT_SERVERS_PATH / name
        has_props = (path / "server.properties").exists()
        has_config = (path / "config").exists()
        has_kubejs = (path / "kubejs").exists()
        start_script = None
        for s in ["startserver.sh", "start.sh", "run.sh"]:
            if (path / s).exists():
                start_script = s
                break
        ver = detect_modpack_version(name)
        result.append({
            "name": name,
            "path": str(path),
            "has_server_properties": has_props,
            "has_config": has_config,
            "has_kubejs": has_kubejs,
            "start_script": start_script,
            "mc_version": ver.get("mc_version"),
            "modloader": ver.get("modloader"),
            "modloader_version": ver.get("modloader_version"),
        })
    return JSONResponse({"modpacks": result})


@app.get("/api/modpacks/{modpack}/server-properties")
async def get_server_properties(modpack: str):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    with open(props_file, "r", encoding="utf-8") as f:
        content = f.read()
    return JSONResponse({"content": content})


@app.post("/api/modpacks/{modpack}/server-properties")
async def save_server_properties(modpack: str, content: str = Form(...)):
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    with open(props_file, "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse({"success": True})


@app.get("/api/modpacks/{modpack}/configs")
async def get_mod_config_list(modpack: str):
    mods = get_mod_configs(modpack)
    return JSONResponse({"mods": mods})


@app.get("/api/modpacks/{modpack}/config-file")
async def get_config_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    # Evitar path traversal
    try:
        full_path.resolve().relative_to((DEFAULT_SERVERS_PATH / modpack / "config").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return JSONResponse({"content": content, "path": path})


@app.post("/api/modpacks/{modpack}/config-file")
async def save_config_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "config" / path
    try:
        full_path.resolve().relative_to((DEFAULT_SERVERS_PATH / modpack / "config").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse({"success": True})


@app.get("/api/modpacks/{modpack}/kubejs")
async def get_kubejs_list(modpack: str):
    kjs_dir = DEFAULT_SERVERS_PATH / modpack / "kubejs"
    exists = kjs_dir.exists()
    files = get_kubejs_files(modpack) if exists else {}
    return JSONResponse({"exists": exists, "groups": files})


@app.get("/api/modpacks/{modpack}/kubejs-file")
async def get_kubejs_file(modpack: str, path: str):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    try:
        full_path.resolve().relative_to((DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        return JSONResponse({"content": f.read(), "path": path})


@app.post("/api/modpacks/{modpack}/kubejs-file")
async def save_kubejs_file(modpack: str, path: str = Form(...), content: str = Form(...)):
    full_path = DEFAULT_SERVERS_PATH / modpack / "kubejs" / path
    try:
        full_path.resolve().relative_to((DEFAULT_SERVERS_PATH / modpack / "kubejs").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse({"success": True})


@app.post("/api/upload-and-extract")
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
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size_mb = temp_file.stat().st_size / (1024 * 1024)
        result = extract_archive(temp_file, dest)

        jvm_configured = None
        if configure_ram == "1" and ram_min and ram_max:
            jvm_path = configure_jvm_ram(dest, ram_min, ram_max)
            if jvm_path:
                jvm_configured = "-Xms" + ram_min + " / -Xmx" + ram_max

        # Sync global player files to the new modpack if they have data
        ensure_global_dir()
        synced_player_files = []
        for fname in PLAYER_FILES:
            global_data = read_global_file(fname)
            if global_data:  # only sync if there's actual data
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


# ── Global player management ──────────────────────────────────────────────────

GLOBAL_DIR = DEFAULT_SERVERS_PATH / ".global"
PLAYER_FILES = ["ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]

def ensure_global_dir():
    """Create .global dir and its files only. Never touches modpack folders."""
    GLOBAL_DIR.mkdir(exist_ok=True)
    for fname in PLAYER_FILES:
        fpath = GLOBAL_DIR / fname
        if not fpath.exists():
            # If a modpack already has this file, import it as the initial global state
            # so we don't lose existing data
            imported = False
            for pack in get_modpacks():
                src = DEFAULT_SERVERS_PATH / pack / fname
                if src.exists():
                    try:
                        data = json.loads(src.read_text(encoding="utf-8"))
                        if data:  # only import if non-empty
                            fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                            imported = True
                            break
                    except Exception:
                        pass
            if not imported:
                fpath.write_text("[]", encoding="utf-8")

def read_global_file(fname: str) -> list:
    ensure_global_dir()
    fpath = GLOBAL_DIR / fname
    try:
        return json.loads(fpath.read_text(encoding="utf-8"))
    except Exception:
        return []

def write_global_file(fname: str, data: list):
    ensure_global_dir()
    (GLOBAL_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def send_console_if_running(modpack: str, commands: list):
    """Send commands to the console if the given modpack is currently running."""
    global mc_process, mc_running_modpack
    with mc_process_lock:
        if mc_process is None or mc_process.poll() is not None:
            return False
        if mc_running_modpack != modpack and modpack != "__all__":
            return False
        try:
            for cmd in commands:
                mc_process.stdin.write((cmd + "\n").encode("utf-8"))
            mc_process.stdin.flush()
            return True
        except Exception:
            return False


def sync_to_all_modpacks(fname: str, data: list):
    """Write the global file to every modpack folder.
    Skips the currently running modpack to avoid corrupting live server files."""
    packs = get_modpacks()
    synced = []
    skipped = []
    for pack in packs:
        # Don't overwrite files of a running server
        if pack == mc_running_modpack:
            skipped.append(pack)
            continue
        dest = DEFAULT_SERVERS_PATH / pack / fname
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        synced.append(pack)
    return synced

def find_player(data: list, name_or_uuid: str) -> int:
    """Return index of player in list, -1 if not found. Matches name or uuid."""
    key = name_or_uuid.lower()
    for i, entry in enumerate(data):
        if entry.get("name", "").lower() == key or entry.get("uuid", "").lower() == key:
            return i
    return -1


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/players")
async def get_all_players():
    ensure_global_dir()
    return JSONResponse({
        "ops": read_global_file("ops.json"),
        "whitelist": read_global_file("whitelist.json"),
        "banned_players": read_global_file("banned-players.json"),
        "banned_ips": read_global_file("banned-ips.json"),
    })


@app.post("/api/players/op")
async def add_op(name: str = Form(...), uuid: str = Form(""), level: int = Form(4)):
    data = read_global_file("ops.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya es op")
    data.append({"uuid": uuid or "", "name": name, "level": level, "bypassesPlayerLimit": False})
    write_global_file("ops.json", data)
    synced = sync_to_all_modpacks("ops.json", data)
    send_console_if_running("__all__", [f"op {name}"])
    return JSONResponse({"success": True, "synced": synced})


@app.delete("/api/players/op/{name}")
async def remove_op(name: str):
    data = read_global_file("ops.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no es op")
    data.pop(idx)
    write_global_file("ops.json", data)
    synced = sync_to_all_modpacks("ops.json", data)
    send_console_if_running("__all__", [f"deop {name}"])
    return JSONResponse({"success": True, "synced": synced})


@app.post("/api/players/whitelist")
async def add_whitelist(name: str = Form(...), uuid: str = Form("")):
    data = read_global_file("whitelist.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está en la whitelist")
    data.append({"uuid": uuid or "", "name": name})
    write_global_file("whitelist.json", data)
    synced = sync_to_all_modpacks("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist add {name}"])
    return JSONResponse({"success": True, "synced": synced})


@app.delete("/api/players/whitelist/{name}")
async def remove_whitelist(name: str):
    data = read_global_file("whitelist.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está en la whitelist")
    data.pop(idx)
    write_global_file("whitelist.json", data)
    synced = sync_to_all_modpacks("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist remove {name}"])
    return JSONResponse({"success": True, "synced": synced})


@app.post("/api/players/ban")
async def ban_player(name: str = Form(...), uuid: str = Form(""), reason: str = Form("Banned by admin")):
    import datetime
    data = read_global_file("banned-players.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está baneado")
    data.append({
        "uuid": uuid or "",
        "name": name,
        "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"),
        "source": "Deployer",
        "expires": "forever",
        "reason": reason,
    })
    write_global_file("banned-players.json", data)
    synced = sync_to_all_modpacks("banned-players.json", data)
    send_console_if_running("__all__", [f"ban {name} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@app.delete("/api/players/ban/{name}")
async def unban_player(name: str):
    data = read_global_file("banned-players.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está baneado")
    data.pop(idx)
    write_global_file("banned-players.json", data)
    synced = sync_to_all_modpacks("banned-players.json", data)
    send_console_if_running("__all__", [f"pardon {name}"])
    return JSONResponse({"success": True, "synced": synced})


@app.post("/api/players/ban-ip")
async def ban_ip(ip: str = Form(...), reason: str = Form("Banned by admin")):
    import datetime
    data = read_global_file("banned-ips.json")
    if any(e.get("ip") == ip for e in data):
        raise HTTPException(status_code=400, detail=f"{ip} ya está baneada")
    data.append({
        "ip": ip,
        "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"),
        "source": "Deployer",
        "expires": "forever",
        "reason": reason,
    })
    write_global_file("banned-ips.json", data)
    synced = sync_to_all_modpacks("banned-ips.json", data)
    send_console_if_running("__all__", [f"ban-ip {ip} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@app.delete("/api/players/ban-ip/{ip}")
async def unban_ip(ip: str):
    data = read_global_file("banned-ips.json")
    idx = next((i for i, e in enumerate(data) if e.get("ip") == ip), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{ip} no está baneada")
    data.pop(idx)
    write_global_file("banned-ips.json", data)
    synced = sync_to_all_modpacks("banned-ips.json", data)
    send_console_if_running("__all__", [f"pardon-ip {ip}"])
    return JSONResponse({"success": True, "synced": synced})


@app.post("/api/players/sync")
async def sync_all():
    """Force sync all global files to all modpacks."""
    results = {}
    for fname in PLAYER_FILES:
        data = read_global_file(fname)
        synced = sync_to_all_modpacks(fname, data)
        results[fname] = synced
    warning = None
    if mc_running_modpack:
        warning = "El servidor " + mc_running_modpack + " estaba activo y no se sincronizó para no interrumpirlo. Usa los comandos de consola en su lugar."
    return JSONResponse({"success": True, "results": results, "warning": warning})


# ── Metrics ───────────────────────────────────────────────────────────────────

mc_metrics = {
    "players_online": [],
    "players_max": 20,
    "tps": None,
    "mspt": None,
    "cpu_process": None,
    "cpu_system": None,
    "ram_used_mb": None,
    "ram_max_mb": None,
    "uptime_seconds": 0,
    "last_updated": None,
    "spark_available": False,
}
mc_start_time = None
mc_spark_detected = False

def _parse_metrics_line(line: str):
    """Extract metrics from console output lines."""
    import re as _re
    import datetime

    # Player join: USERNAME joined the game
    join = _re.search(r'(\\w+) joined the game', line)
    if join:
        name = join.group(1)
        if name not in mc_metrics["players_online"]:
            mc_metrics["players_online"].append(name)

    # Player leave: USERNAME left the game
    leave = _re.search(r'(\w+) left the game', line)
    if leave:
        name = leave.group(1)
        if name in mc_metrics["players_online"]:
            mc_metrics["players_online"].remove(name)

    # Spark TPS: "20.0, *20.0, *20.0, *20.0, *20.0" (after the TPS header line)
    if mc_metrics["spark_available"] and '[⚡]' in line:
        # Line with TPS values: numbers separated by commas, possibly with *
        tps_spark = _re.search(r'\[\⚡\]\s*\*?([\d.]+),\s*\*?([\d.]+)', line)
        if tps_spark and 'TPS from' not in line and 'Tick' not in line and 'CPU' not in line:
            mc_metrics["tps"] = float(tps_spark.group(1))

        # Tick durations: "0.6/1.1/1.9/3.3; 0.6/0.9/1.4/3.3" — use median (2nd value) of last 10s
        mspt_spark = _re.search(r'\[\⚡\]\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+;', line)
        if mspt_spark:
            mc_metrics["mspt"] = float(mspt_spark.group(1))

        # CPU: "18%, 13%, 9% (system)" and "0%, 0%, 3% (process)"
        cpu_sys = _re.search(r'\[\⚡\]\s*(\d+)%.*\(system\)', line)
        if cpu_sys:
            mc_metrics["cpu_system"] = int(cpu_sys.group(1))
        cpu_proc = _re.search(r'\[\⚡\]\s*(\d+)%.*\(process\)', line)
        if cpu_proc:
            mc_metrics["cpu_process"] = int(cpu_proc.group(1))

    # TPS patterns for different modloaders:
    # NeoForge/Forge: "Overall: 20.00 TPS, 49.78 MSPT"
    tps_m = _re.search(r'Overall[:\s]+(\d+\.?\d*)\s*TPS.*?(\d+\.?\d*)\s*MSPT', line, _re.IGNORECASE)
    if tps_m:
        mc_metrics["tps"] = float(tps_m.group(1))
        mc_metrics["mspt"] = float(tps_m.group(2))
    else:
        # Alt: "Overall: 20.0 TPS / 49.78 ms"
        tps_m2 = _re.search(r'Overall[:\s]+(\d+\.?\d*)\s*TPS[^/]*/\s*(\d+\.?\d*)\s*ms', line, _re.IGNORECASE)
        if tps_m2:
            mc_metrics["tps"] = float(tps_m2.group(1))
            mc_metrics["mspt"] = float(tps_m2.group(2))

    # Fabric/Carpet: "TPS: 20.0, MSPT: 49.7"
    tps_fab = _re.search(r'TPS[:\s]+(\d+\.?\d*).*?MSPT[:\s]+(\d+\.?\d*)', line, _re.IGNORECASE)
    if tps_fab:
        mc_metrics["tps"] = float(tps_fab.group(1))
        mc_metrics["mspt"] = float(tps_fab.group(2))

    # Vanilla /tps output: "The server is running at 20.0/20 ticks per second"
    tps_v = _re.search(r'running at (\d+\.?\d*)/20 ticks per second', line, _re.IGNORECASE)
    if tps_v:
        mc_metrics["tps"] = float(tps_v.group(1))

    # Generic fallback: any "XX.X TPS" near "ms"
    tps_gen = _re.search(r'(\d+\.?\d+)\s*tps.*?(\d+\.?\d+)\s*ms', line, _re.IGNORECASE)
    if tps_gen and mc_metrics["tps"] is None:
        mc_metrics["tps"] = float(tps_gen.group(1))
        mc_metrics["mspt"] = float(tps_gen.group(2))

    # RAM from JVM: Used Memory: 1234 MB / 4096 MB
    ram_m = _re.search(r'[Uu]sed [Mm]emory:\s*(\d+)\s*MB\s*/\s*(\d+)\s*MB', line)
    if ram_m:
        mc_metrics["ram_used_mb"] = int(ram_m.group(1))
        mc_metrics["ram_max_mb"] = int(ram_m.group(2))

    # Player count from /list: There are X of a max of Y players online
    list_m = _re.search(r'[Tt]here are (\d+) of a max(?: of)? (\d+) players online', line)
    if list_m:
        mc_metrics["players_max"] = int(list_m.group(2))

    mc_metrics["last_updated"] = datetime.datetime.utcnow().isoformat()


@app.get("/api/server/metrics")
async def get_metrics():
    import datetime
    uptime = None
    if mc_start_time:
        uptime = int((datetime.datetime.utcnow() - mc_start_time).total_seconds())
    # Always read live RAM from /proc on each request
    with mc_process_lock:
        proc = mc_process
    if proc is not None and proc.poll() is None:
        try:
            pid = proc.pid
            status_path = f"/proc/{pid}/status"
            if Path(status_path).exists():
                with open(status_path) as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mc_metrics["ram_used_mb"] = round(int(line.split()[1]) / 1024, 1)
                        elif line.startswith("VmPeak:"):
                            mc_metrics["ram_max_mb"] = round(int(line.split()[1]) / 1024, 1)
        except Exception:
            pass
    return JSONResponse({
        **mc_metrics,
        "running": proc is not None and proc.poll() is None,
        "uptime_seconds": uptime,
    })


@app.post("/api/server/metrics/refresh")
async def refresh_metrics():
    """Send list command and read process RAM from /proc."""
    global mc_process
    with mc_process_lock:
        if mc_process is None or mc_process.poll() is not None:
            raise HTTPException(status_code=400, detail="Servidor no activo")
        try:
            mc_process.stdin.write(b"list\n")
            if mc_metrics.get("spark_available"):
                mc_process.stdin.write(b"spark tps\n")
            mc_process.stdin.flush()
        except Exception:
            pass
        # Read RAM from /proc/<pid>/status (Linux only)
        try:
            pid = mc_process.pid
            status_path = f"/proc/{pid}/status"
            if Path(status_path).exists():
                with open(status_path) as f:
                    for line in f:
                        if line.startswith("VmRSS:"):  # Resident Set Size = actual RAM used
                            kb = int(line.split()[1])
                            mc_metrics["ram_used_mb"] = round(kb / 1024, 1)
                        elif line.startswith("VmPeak:"):
                            kb = int(line.split()[1])
                            mc_metrics["ram_max_mb"] = round(kb / 1024, 1)
        except Exception:
            pass
    return JSONResponse({"success": True})


# ── Modpack version detection ─────────────────────────────────────────────────

# NeoForge version prefix -> MC version
# NeoForge uses MC version as prefix: 21.1.x = MC 1.21.1, 21.0.x = MC 1.21, 20.4.x = MC 1.20.4
def mc_from_neoforge(ver: str) -> str:
    m = re.match(r'^(\d+)\.(\d+)\.', ver)
    if m:
        major, minor = m.group(1), m.group(2)
        return f"1.{major}.{minor}" if minor != "0" else f"1.{major}"
    return None

# Forge major version -> MC version (approximate, covers common versions)
FORGE_MC_MAP = {
    "54": "1.21.1", "53": "1.21", "52": "1.20.6", "51": "1.20.4",
    "49": "1.20.2", "47": "1.20.1", "45": "1.20", "44": "1.19.4",
    "43": "1.19.3", "42": "1.19.2", "41": "1.19", "40": "1.18.2",
    "39": "1.18.1", "38": "1.18", "37": "1.17.1", "36": "1.16.5",
}

def mc_from_forge(ver: str) -> str:
    m = re.match(r'^(\d+)\.', ver)
    if m:
        return FORGE_MC_MAP.get(m.group(1))
    return None

def detect_modpack_version(modpack: str) -> dict:
    """Detect Minecraft version and modloader from variables.txt, server.properties, or jar filenames."""
    base = DEFAULT_SERVERS_PATH / modpack
    result = {"mc_version": None, "modloader": None, "modloader_version": None}

    # 1. Try variables.txt (most reliable)
    for fname in ["variables.txt", "Variables.txt"]:
        vfile = base / fname
        if vfile.exists():
            text = vfile.read_text(encoding="utf-8", errors="replace")
            for line in text.split("\n"):
                line = line.strip()
                m = re.match(r'^MINECRAFT_VERSION\s*=\s*(.+)$', line)
                if m: result["mc_version"] = m.group(1).strip().strip('"')
                m = re.match(r'^MODLOADER\s*=\s*(.+)$', line)
                if m: result["modloader"] = m.group(1).strip().strip('"')
                m = re.match(r'^MODLOADER_VERSION\s*=\s*(.+)$', line)
                if m: result["modloader_version"] = m.group(1).strip().strip('"')
            # If we have modloader version but no MC version, derive it
            if not result["mc_version"] and result["modloader_version"] and result["modloader"]:
                ml = result["modloader"].lower()
                if "neoforge" in ml:
                    result["mc_version"] = mc_from_neoforge(result["modloader_version"])
                elif "forge" in ml:
                    result["mc_version"] = mc_from_forge(result["modloader_version"])
            if result["mc_version"] or result["modloader"]:
                return result

    # 2. Try detecting from jar filenames in root or libraries/
    for search_dir in [base, base / "libraries"]:
        if not search_dir.exists():
            continue
        for f in search_dir.iterdir():
            name = f.name.lower()
            # NeoForge: neoforge-1.21.1-21.1.229.jar OR neoforge-21.1.229.jar
            m = re.match(r'neoforge[-_](1\.\d+\.\d+)[-_]([\d.]+)', name)
            if m:
                result["mc_version"] = m.group(1)
                result["modloader"] = "NeoForge"
                result["modloader_version"] = m.group(2)
                return result
            m = re.match(r'neoforge[-_](\d+\.\d+\.\d+)', name)
            if m:
                ver = m.group(1)
                result["modloader"] = "NeoForge"
                result["modloader_version"] = ver
                result["mc_version"] = mc_from_neoforge(ver)
                return result
            # Forge: forge-1.20.1-47.2.0.jar
            m = re.match(r'forge[-_]([\d.]+)[-_]([\d.]+)', name)
            if m:
                result["mc_version"] = m.group(1)
                result["modloader"] = "Forge"
                result["modloader_version"] = m.group(2)
                return result
            # Forge: forge-47.2.0.jar (no MC prefix)
            m = re.match(r'forge[-_](\d+\.\d+\.\d+)', name)
            if m:
                ver = m.group(1)
                result["modloader"] = "Forge"
                result["modloader_version"] = ver
                result["mc_version"] = mc_from_forge(ver)
                return result
            # Fabric: fabric-server-mc.1.21.1-loader.0.16.0.jar
            m = re.match(r'fabric.*mc\.([\d.]+)', name)
            if m:
                result["mc_version"] = m.group(1)
                result["modloader"] = "Fabric"
                return result
            # Quilt
            m = re.match(r'quilt.*mc\.([\d.]+)', name)
            if m:
                result["mc_version"] = m.group(1)
                result["modloader"] = "Quilt"
                return result

    # 3. Try server.properties for vanilla (no modloader jar)
    props_file = base / "server.properties"
    if props_file.exists():
        result["modloader"] = "Vanilla"

    return result


def read_mod_metadata(jar_bytes: bytes) -> dict:
    """Read mod metadata from a jar file bytes. Returns mc_versions, modloader, mod_id, mod_version."""
    import zipfile as _zf
    import io
    result = {"mc_versions": [], "modloader": None, "mod_id": None, "mod_version": None, "error": None}
    try:
        with _zf.ZipFile(io.BytesIO(jar_bytes)) as zf:
            names = zf.namelist()

            # NeoForge/Forge: META-INF/neoforge.mods.toml (modern) or META-INF/mods.toml (legacy)
            toml_file = None
            if "META-INF/neoforge.mods.toml" in names:
                toml_file = "META-INF/neoforge.mods.toml"
                result["modloader"] = "NeoForge"
            elif "META-INF/mods.toml" in names:
                toml_file = "META-INF/mods.toml"
                result["modloader"] = "NeoForge/Forge"
            if toml_file:
                text = zf.read(toml_file).decode("utf-8", errors="replace")
                # mod id
                m = re.search(r'modId\s*=\s*"([^"]+)"', text)
                if m: result["mod_id"] = m.group(1)
                # mod version
                m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
                if m: result["mod_version"] = m.group(1)
                # minecraft version range: "[1.21,1.22)" or "1.21.x"
                mc_versions = re.findall(r'minecraft.*?versionRange\s*=\s*"([^"]+)"', text, re.IGNORECASE | re.DOTALL)
                if not mc_versions:
                    mc_versions = re.findall(r'\[forge\].*?versionRange.*?"([^"]+)"', text, re.DOTALL)
                result["mc_versions"] = mc_versions

            elif "META-INF/neoforge.mods.toml" not in names and "META-INF/mods.toml" not in names:
                pass  # will fall through to fabric/quilt check

            # Fabric: fabric.mod.json
            elif "fabric.mod.json" in names:
                result["modloader"] = "Fabric"
                import json as _json
                data = _json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="replace"))
                result["mod_id"] = data.get("id")
                result["mod_version"] = data.get("version")
                depends = data.get("depends", {})
                mc = depends.get("minecraft") or depends.get("fabricloader")
                if mc:
                    result["mc_versions"] = [mc] if isinstance(mc, str) else mc

            # Quilt: quilt.mod.json
            elif "quilt.mod.json" in names:
                result["modloader"] = "Quilt"
                import json as _json
                data = _json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="replace"))
                meta = data.get("quilt_loader", {})
                result["mod_id"] = meta.get("id")
                result["mod_version"] = meta.get("version")
                deps = meta.get("depends", [])
                for dep in deps:
                    if isinstance(dep, dict) and dep.get("id") == "minecraft":
                        v = dep.get("versions")
                        if v: result["mc_versions"] = [v] if isinstance(v, str) else v

            else:
                result["error"] = "No se encontró metadata de mod (mods.toml / fabric.mod.json)"

    except Exception as e:
        result["error"] = str(e)
    return result


def mc_version_compatible(server_mc: str, mod_versions: list) -> bool:
    """Check if server MC version is compatible with mod's declared version ranges."""
    if not server_mc or not mod_versions:
        return True  # can't check, allow
    for vrange in mod_versions:
        vrange = vrange.strip()
        # Exact: "1.21.1"
        if vrange == server_mc:
            return True
        # Wildcard: "1.21.x" or "1.21.*"
        if re.match(r'^[\d.]+[.*x]$', vrange):
            prefix = re.sub(r'[.*x]+$', '', vrange).rstrip('.')
            if server_mc.startswith(prefix):
                return True
        # Maven range: "[1.21,1.22)" "[1.21.1,)"
        m = re.match(r'^[\[\(]([\d.]*),\s*([\d.]*)[\]\)]$', vrange)
        if m:
            lo, hi = m.group(1), m.group(2)
            def ver_tuple(v):
                return tuple(int(x) for x in v.split('.') if x.isdigit())
            sv = ver_tuple(server_mc)
            ok = True
            if lo:
                lo_t = ver_tuple(lo)
                ok = ok and (sv >= lo_t if vrange[0] == '[' else sv > lo_t)
            if hi:
                hi_t = ver_tuple(hi)
                ok = ok and (sv < hi_t if vrange[-1] == ')' else sv <= hi_t)
            if ok:
                return True
    return False


@app.get("/api/modpacks/{modpack}/version")
async def get_modpack_version(modpack: str):
    info = detect_modpack_version(modpack)
    return JSONResponse(info)


@app.post("/api/modpacks/{modpack}/mods/upload")
async def upload_mod(modpack: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".jar"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .jar")

    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        raise HTTPException(status_code=404, detail="Carpeta mods/ no encontrada en este modpack")

    dest = mods_dir / file.filename
    if dest.exists():
        raise HTTPException(status_code=400, detail=f"{file.filename} ya existe en mods/")

    # Read jar bytes for metadata check
    jar_bytes = await file.read()

    # Get server version
    server_info = detect_modpack_version(modpack)
    server_mc = server_info.get("mc_version")

    # Read mod metadata
    meta = read_mod_metadata(jar_bytes)

    # Check compatibility
    if meta.get("error") and not meta.get("mod_id"):
        # No metadata at all — warn but allow (some mods don't declare properly)
        pass
    elif server_mc and meta["mc_versions"]:
        if not mc_version_compatible(server_mc, meta["mc_versions"]):
            raise HTTPException(
                status_code=409,
                detail=f"Incompatible: el mod requiere MC {', '.join(meta['mc_versions'])} pero el servidor es {server_mc}"
            )

    # Save the jar
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


# ── Mod list ──────────────────────────────────────────────────────────────────

@app.get("/api/modpacks/{modpack}/mods")
async def list_mods(modpack: str):
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return JSONResponse({"mods": [], "exists": False, "count": 0})
    mods = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        stem = f.stem if not f.name.endswith('.disabled') else f.stem.replace('.jar','').replace('.zip','')
        low = f.name.lower()
        if not (low.endswith('.jar') or low.endswith('.zip') or low.endswith('.jar.disabled')):
            continue
        clean = re.sub(r'[-_+][0-9].*$', '', stem)
        clean = re.sub(r'[-_](forge|fabric|neoforge|mc|minecraft).*$', '', clean, flags=re.IGNORECASE)
        clean = clean.replace('-', ' ').replace('_', ' ').strip()
        mods.append({
            "name": clean or stem,
            "enabled": not f.name.endswith('.disabled'),
        })
    return JSONResponse({"mods": mods, "exists": True, "count": len(mods)})


# ── Mod detection ─────────────────────────────────────────────────────────────

def detect_installed_mods(modpack: str):
    """Return set of mod jar filenames (lowercase) from the mods/ folder."""
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return set()
    names = set()
    for f in mods_dir.iterdir():
        if f.is_file() and f.suffix.lower() in {".jar", ".zip"}:
            names.add(f.name.lower())
    return names

def has_mod_keyword(mod_names: set, keyword: str) -> bool:
    return any(keyword in n for n in mod_names)


@app.get("/api/modpacks/{modpack}/detected-mods")
async def detected_mods(modpack: str):
    names = detect_installed_mods(modpack)
    return JSONResponse({
        "has_biomesoplenty": has_mod_keyword(names, "biomesoplenty") or has_mod_keyword(names, "biomes-o-plenty") or has_mod_keyword(names, "biomes_o_plenty"),
        "has_terraforged": has_mod_keyword(names, "terraforged") or has_mod_keyword(names, "terra-forged"),
        "mod_count": len(names),
    })


# ── World management ──────────────────────────────────────────────────────────

def parse_server_properties(modpack: str):
    """Parse server.properties into a dict."""
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    props = {}
    if not props_file.exists():
        return props
    with open(props_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
    return props

def save_server_property(modpack: str, key: str, value: str):
    """Update a single key in server.properties."""
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        raise HTTPException(status_code=404, detail="server.properties no encontrado")
    with open(props_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(key + "=") or stripped.startswith(key + " ="):
            new_lines.append(key + "=" + value + "\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(key + "=" + value + "\n")
    with open(props_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def get_worlds(modpack: str):
    """Detect world folders in the modpack directory."""
    base = DEFAULT_SERVERS_PATH / modpack
    props = parse_server_properties(modpack)
    active = props.get("level-name", "world")
    worlds = []
    if not base.exists():
        return worlds, active
    # A world folder contains region/ or level.dat
    for item in sorted(base.iterdir()):
        if not item.is_dir():
            continue
        is_world = (item / "level.dat").exists() or (item / "region").exists()
        if is_world:
            size_mb = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) / (1024*1024)
            worlds.append({
                "name": item.name,
                "active": item.name == active,
                "size_mb": round(size_mb, 1),
            })
    return worlds, active


@app.get("/api/modpacks/{modpack}/worlds")
async def list_worlds(modpack: str):
    worlds, active = get_worlds(modpack)
    props = parse_server_properties(modpack)
    return JSONResponse({
        "worlds": worlds,
        "active": active,
        "level_type": props.get("level-type", "minecraft:normal"),
        "seed": props.get("level-seed", ""),
    })


@app.post("/api/modpacks/{modpack}/worlds/activate")
async def activate_world(modpack: str, world_name: str = Form(...)):
    """Switch the active world by updating level-name in server.properties."""
    base = DEFAULT_SERVERS_PATH / modpack
    world_path = base / world_name
    if not world_path.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "active": world_name})


@app.post("/api/modpacks/{modpack}/worlds/create")
async def create_world(
    modpack: str,
    world_name: str = Form(...),
    level_type: str = Form("minecraft:normal"),
    seed: str = Form(""),
    activate: str = Form("1"),
):
    """Prepare server.properties for a new world generation."""
    if not re.match(r'^[a-zA-Z0-9_\-]+$', world_name):
        raise HTTPException(status_code=400, detail="Nombre de mundo inválido (solo letras, números, _ y -)")
    base = DEFAULT_SERVERS_PATH / modpack
    if (base / world_name).exists():
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre")
    # Update server.properties
    save_server_property(modpack, "level-type", level_type)
    save_server_property(modpack, "level-seed", seed)
    if activate == "1":
        save_server_property(modpack, "level-name", world_name)
    return JSONResponse({"success": True, "world_name": world_name, "message": "Mundo configurado. Se generará al iniciar el servidor."})


@app.delete("/api/modpacks/{modpack}/worlds/{world_name}")
async def delete_world(modpack: str, world_name: str):
    """Delete a world folder. Cannot delete the currently active world."""
    base = DEFAULT_SERVERS_PATH / modpack
    world_path = base / world_name
    # Safety checks
    try:
        world_path.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not world_path.exists():
        raise HTTPException(status_code=404, detail="El mundo no existe")
    props = parse_server_properties(modpack)
    active = props.get("level-name", "world")
    if world_name == active:
        raise HTTPException(status_code=400, detail="No puedes borrar el mundo activo. Cambia a otro primero.")
    shutil.rmtree(world_path)
    # Also delete nether/end sibling folders if present
    for suffix in ["_nether", "_the_end"]:
        sibling = base / (world_name + suffix)
        if sibling.exists():
            shutil.rmtree(sibling)
    return JSONResponse({"success": True})


# ── Logs & crash reports ──────────────────────────────────────────────────────

@app.get("/api/modpacks/{modpack}/logs")
async def get_log_list(modpack: str):
    base = DEFAULT_SERVERS_PATH / modpack
    logs_dir = base / "logs"
    crash_dir = base / "crash-reports"
    logs = []
    if logs_dir.exists():
        for f in sorted(logs_dir.iterdir(), reverse=True):
            if f.is_file() and f.suffix in {".log", ".gz", ".txt"}:
                logs.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "log"})
    crashes = []
    if crash_dir.exists():
        for f in sorted(crash_dir.iterdir(), reverse=True):
            if f.is_file():
                crashes.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "crash"})
    return JSONResponse({"logs": logs[:20], "crashes": crashes[:30]})


@app.get("/api/modpacks/{modpack}/logs/{filename}")
async def get_log_file(modpack: str, filename: str):
    # Security: no path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=403, detail="Nombre de archivo inválido")
    base = DEFAULT_SERVERS_PATH / modpack
    # Try logs/ and crash-reports/
    candidates = [base / "logs" / filename, base / "crash-reports" / filename]
    file_path = None
    for c in candidates:
        if c.exists():
            file_path = c
            break
    if file_path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    # Handle gzipped logs
    if filename.endswith(".gz"):
        import gzip
        with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    else:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    # Analyze for culprit mods
    culprits = analyze_crash(raw, modpack)
    return JSONResponse({"content": raw, "culprits": culprits, "filename": filename})


def analyze_crash(text: str, modpack: str):
    """Try to identify which mod caused the crash by cross-referencing stack trace with installed mods."""
    import re
    culprits = []
    lines = text.split("\n")
    # Collect mod jar names
    mod_names = detect_installed_mods(modpack)
    # Common patterns that indicate a mod in the stack trace
    # e.g. "at com.example.mymod.SomeClass" or jar references
    suspicious_lines = []
    in_exception = False
    for line in lines:
        low = line.lower()
        if any(k in low for k in ["exception", "error", "caused by", "fatal"]):
            in_exception = True
        if in_exception and line.strip().startswith("at "):
            suspicious_lines.append(line.strip())
        if in_exception and line.strip() == "":
            in_exception = False
    # Match suspicious lines against known mod jars
    found = set()
    for jar in mod_names:
        # Strip version suffix from jar name for matching
        base_name = re.sub(r"[-_][0-9].*$", "", jar.replace(".jar", "").replace(".zip", "")).lower()
        if len(base_name) < 4:
            continue
        # Check if any suspicious line or the full text mentions this mod
        for sl in suspicious_lines:
            if base_name in sl.lower():
                found.add(jar)
                break
        # Also check raw text for the mod name
        if base_name in text.lower():
            # Only add if it appears near an exception
            found.add(jar)
    # Also extract "Caused by" messages
    caused_by = []
    for line in lines:
        if line.strip().lower().startswith("caused by:"):
            caused_by.append(line.strip())
    return {"mods": list(found), "caused_by": caused_by[:5]}


@app.get("/api/disk-usage")
async def disk_usage():
    try:
        total, used, free = shutil.disk_usage("/")
        gb = 1024 ** 3
        return JSONResponse({
            "total_gb": round(total / gb, 1),
            "used_gb": round(used / gb, 1),
            "free_gb": round(free / gb, 1),
            "percent_used": round((used / total) * 100, 1),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/server/status")
async def server_status():
    global mc_process, mc_running_modpack
    with mc_process_lock:
        running = mc_process is not None and mc_process.poll() is None
    return JSONResponse({
        "running": running,
        "modpack": mc_running_modpack if running else None,
    })


@app.post("/api/server/start")
async def server_start(modpack: str = Form(...)):
    global mc_process, mc_running_modpack, mc_output_lines
    with mc_process_lock:
        if mc_process is not None and mc_process.poll() is None:
            raise HTTPException(status_code=400, detail="Ya hay un servidor en marcha")
        server_dir = DEFAULT_SERVERS_PATH / modpack
        script = None
        for candidate in ["startserver.sh", "start.sh", "run.sh"]:
            p = server_dir / candidate
            if p.exists():
                script = p
                break
        if script is None:
            raise HTTPException(status_code=404, detail="No se encontró script de arranque (startserver.sh / start.sh / run.sh) en " + str(server_dir))

        # Patch the script in memory to disable restart loops, then write a temp copy
        import re as _re
        script_content = script.read_bytes()
        # Patch: force RESTART=false wherever it's set to true inside the script
        script_content = _re.sub(rb'(?m)^(\s*RESTART\s*=\s*)["\']?true["\']?', rb'\1false', script_content)
        # Write patched script to temp file
        import tempfile, stat
        tmp = tempfile.NamedTemporaryFile(
            mode='wb', suffix='.sh', dir=str(server_dir), delete=False
        )
        tmp.write(script_content)
        tmp.close()
        patched_script = tmp.name
        os.chmod(patched_script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)

        with mc_output_lock:
            mc_output_lines.clear()
        import subprocess
        proc = subprocess.Popen(
            ["bash", patched_script],
            cwd=str(server_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            start_new_session=True,
            env={**os.environ, "RESTART": "false", "WAIT_FOR_USER_INPUT": "false"},
        )
        mc_process = proc
        mc_running_modpack = modpack
        # Pass patched_script so the reader thread can delete it after the process ends
        t = threading.Thread(target=_reader_thread, args=(proc, patched_script), daemon=True)
        t.start()
    return JSONResponse({"success": True, "modpack": modpack})


@app.post("/api/server/stop")
async def server_stop():
    global mc_process
    with mc_process_lock:
        if mc_process is None or mc_process.poll() is not None:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        try:
            import signal
            os.killpg(os.getpgid(mc_process.pid), signal.SIGKILL)
        except Exception:
            try:
                mc_process.kill()
            except Exception:
                pass
    return JSONResponse({"success": True})


@app.post("/api/server/command")
async def server_command(cmd: str = Form(...)):
    global mc_process
    with mc_process_lock:
        if mc_process is None or mc_process.poll() is not None:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        try:
            mc_process.stdin.write((cmd.strip() + "\n").encode("utf-8"))
            mc_process.stdin.flush()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"success": True})


@app.get("/api/server/logs")
async def server_logs():
    """SSE endpoint: streams new lines to the client."""
    import queue

    q = queue.Queue()
    with mc_sse_lock:
        mc_sse_clients.add(q)

    # Send buffered history first
    with mc_output_lock:
        history = list(mc_output_lines)

    async def event_stream():
        try:
            # Send history
            for line in history:
                yield "data: " + line + "\n\n"
            # Stream new lines
            loop = asyncio.get_event_loop()
            while True:
                try:
                    line = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                    yield "data: " + line + "\n\n"
                    if line == "__STOPPED__":
                        break
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            with mc_sse_lock:
                mc_sse_clients.discard(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def clean_orphan_locks():
    """Remove session.lock files left by crashed servers.
    Only removes them if no Java server process is running."""
    cleaned = []
    try:
        if not DEFAULT_SERVERS_PATH.exists():
            return cleaned
        for modpack_dir in DEFAULT_SERVERS_PATH.iterdir():
            if not modpack_dir.is_dir() or modpack_dir.name.startswith('.'):
                continue
            # Find all session.lock files inside this modpack
            for lock in modpack_dir.rglob('session.lock'):
                try:
                    lock.unlink()
                    cleaned.append(str(lock.relative_to(DEFAULT_SERVERS_PATH)))
                except Exception as e:
                    pass
    except Exception:
        pass
    return cleaned


def kill_orphan_servers():
    """Kill any leftover Minecraft server Java processes from previous runs."""
    import subprocess
    killed = []
    try:
        result = subprocess.run(
            ["pgrep", "-f", "-l", "java"],
            capture_output=True, text=True
        )
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, cmdline = parts[0], parts[1]
            # Only kill Java processes that look like MC servers
            mc_keywords = ["forge", "neoforge", "fabric", "quilt",
                           "minecraft", "server.jar", "startserver",
                           "ServerStarterJar"]
            if any(k.lower() in cmdline.lower() for k in mc_keywords):
                try:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    killed.append(pid + " (" + cmdline[:60] + ")")
                except Exception:
                    pass
    except FileNotFoundError:
        # pgrep not available, try ps
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True
            )
            for line in result.stdout.split("\n"):
                if "java" not in line.lower():
                    continue
                mc_keywords = ["forge", "neoforge", "fabric", "quilt",
                               "minecraft", "server.jar", "startserver"]
                if any(k.lower() in line.lower() for k in mc_keywords):
                    pid = line.split()[1]
                    try:
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                        killed.append(pid)
                    except Exception:
                        pass
        except Exception:
            pass
    return killed


def kill_port_25565():
    """Kill any process using port 25565 (Minecraft default port)."""
    killed = []
    try:
        import subprocess
        result = subprocess.run(
            ["ss", "-tlnp", "sport", "=", ":25565"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if "25565" in line and "pid=" in line:
                import re
                for pid_str in re.findall(r'pid=(\d+)', line):
                    pid = int(pid_str)
                    try:
                        os.kill(pid, 9)
                        killed.append(pid)
                    except Exception:
                        pass
    except Exception:
        pass
    # Fallback: use fuser if ss didn't work
    if not killed:
        try:
            result = subprocess.run(
                ["fuser", "25565/tcp"],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.split():
                try:
                    pid = int(pid_str.strip())
                    os.kill(pid, 9)
                    killed.append(pid)
                except Exception:
                    pass
        except Exception:
            pass
    return killed


if __name__ == "__main__":
    print("Minecraft Server Deployer arrancando...")
    print("Liberando puerto 25565 si está ocupado...")
    port_killed = kill_port_25565()
    if port_killed:
        print(f"  Eliminados {len(port_killed)} proceso(s) en el puerto 25565: {port_killed}")
        import time; time.sleep(1)
    else:
        print("  Puerto 25565 libre.")
    print("Buscando procesos huérfanos de servidores anteriores...")
    killed = kill_orphan_servers()
    if killed:
        print(f"  Eliminados {len(killed)} proceso(s) huérfano(s):")
        for k in killed:
            print(f"    - {k}")
    else:
        print("  No se encontraron procesos huérfanos.")
    print("Limpiando session.lock abandonados...")
    locks = clean_orphan_locks()
    if locks:
        print(f"  Eliminados {len(locks)} session.lock abandonado(s):")
        for l in locks:
            print(f"    - {l}")
    else:
        print("  No se encontraron session.lock abandonados.")
    print("Carpeta por defecto: " + str(DEFAULT_SERVERS_PATH))
    print("Accede desde tu red local en: http://<IP-DE-ESTE-EQUIPO>:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
