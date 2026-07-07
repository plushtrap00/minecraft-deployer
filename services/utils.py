"""
services/utils.py - Utilidades generales de la aplicación.

Contiene:
- get_system_ram_gb(): RAM total del sistema desde /proc/meminfo
- get_modpacks(): lista de modpacks instalados
- get_mod_configs(): árbol de archivos de config de un modpack
- get_kubejs_files(): árbol de archivos KubeJS
- get_world_files(): árbol de archivos de texto editables de un mundo
- extract_archive(): descomprimir ZIP/TAR/RAR
- detect_jvm_ram() / configure_jvm_ram(): leer/modificar RAM en
  user_jvm_args.txt, variables.txt, o el propio script de arranque
"""
import os
import re
import subprocess
import zipfile
import tarfile
from pathlib import Path
from fastapi import HTTPException

from config import DEFAULT_SERVERS_PATH, CONFIG_EXTENSIONS

KUBEJS_EXTENSIONS = {".js", ".ts", ".json", ".yaml", ".yml", ".txt", ".md"}
WORLD_EXTENSIONS = {".json", ".txt", ".mcfunction", ".yaml", ".yml", ".mcmeta"}

_configs_cache: dict = {}      # modpack -> (dir_mtime, result)
_kubejs_cache: dict = {}       # modpack -> (dir_mtime, result)
_world_files_cache: dict = {}  # (modpack, world_name) -> (dir_mtime, result)


def get_system_ram_gb() -> float | None:
    """Devuelve la RAM total del sistema en GB leyendo /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    return None


def get_modpacks() -> list[str]:
    """Devuelve la lista de nombres de modpacks instalados (carpetas en servers-minecraft/)."""
    if not DEFAULT_SERVERS_PATH.exists():
        return []
    return [
        item.name
        for item in sorted(DEFAULT_SERVERS_PATH.iterdir())
        if item.is_dir() and not item.name.startswith(".")
    ]


def get_mod_configs(modpack_name: str) -> dict:
    """
    Devuelve un dict {mod_key: [lista de rutas relativas]} con los archivos
    de configuración de un modpack, agrupados por subcarpeta bajo config/.
    Los archivos en la raíz de config/ se agrupan bajo '__root__'.
    Resultado cacheado por mtime del directorio config/.
    """
    config_dir = DEFAULT_SERVERS_PATH / modpack_name / "config"
    if not config_dir.exists():
        return {}

    try:
        mtime = config_dir.stat().st_mtime
    except Exception:
        mtime = None

    if modpack_name in _configs_cache:
        cached_mtime, cached_result = _configs_cache[modpack_name]
        if cached_mtime == mtime:
            return cached_result

    mods: dict = {}
    for path in sorted(config_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in CONFIG_EXTENSIONS:
            continue
        rel = path.relative_to(config_dir)
        parts = rel.parts
        mod_key = "__root__" if len(parts) == 1 else parts[0]
        mods.setdefault(mod_key, []).append(str(rel))

    _configs_cache[modpack_name] = (mtime, mods)
    return mods


def get_kubejs_files(modpack_name: str) -> dict:
    """
    Devuelve un dict {grupo: [lista de rutas relativas]} con los archivos
    KubeJS de un modpack, agrupados por subcarpeta bajo kubejs/.
    Resultado cacheado por mtime del directorio kubejs/.
    """
    kubejs_dir = DEFAULT_SERVERS_PATH / modpack_name / "kubejs"
    if not kubejs_dir.exists():
        return {}

    try:
        mtime = kubejs_dir.stat().st_mtime
    except Exception:
        mtime = None

    if modpack_name in _kubejs_cache:
        cached_mtime, cached_result = _kubejs_cache[modpack_name]
        if cached_mtime == mtime:
            return cached_result

    groups: dict = {}
    for path in sorted(kubejs_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in KUBEJS_EXTENSIONS:
            continue
        rel = path.relative_to(kubejs_dir)
        parts = rel.parts
        group = parts[0] if len(parts) > 1 else "__root__"
        groups.setdefault(group, []).append(str(rel))

    _kubejs_cache[modpack_name] = (mtime, groups)
    return groups


def invalidate_kubejs_cache(modpack_name: str) -> None:
    _kubejs_cache.pop(modpack_name, None)


def get_world_files(modpack_name: str, world_name: str) -> dict:
    """
    Devuelve un dict {carpeta: [lista de rutas relativas]} con los archivos de
    texto editables de un mundo (stats/, advancements/, datapacks/...).
    Excluye binarios como level.dat, region/*.mca y playerdata/*.dat.
    Resultado cacheado por mtime de la carpeta del mundo.
    """
    world_dir = DEFAULT_SERVERS_PATH / modpack_name / world_name
    if not world_dir.exists():
        return {}

    try:
        mtime = world_dir.stat().st_mtime
    except Exception:
        mtime = None

    cache_key = (modpack_name, world_name)
    if cache_key in _world_files_cache:
        cached_mtime, cached_result = _world_files_cache[cache_key]
        if cached_mtime == mtime:
            return cached_result

    groups: dict = {}
    for path in sorted(world_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WORLD_EXTENSIONS:
            continue
        rel = path.relative_to(world_dir)
        parts = rel.parts
        group = parts[0] if len(parts) > 1 else "__root__"
        groups.setdefault(group, []).append(str(rel))

    _world_files_cache[cache_key] = (mtime, groups)
    return groups


def extract_archive(archive_path: Path, dest_path: Path) -> dict:
    """
    Descomprime un archivo en dest_path.
    Soporta: .zip, .tar.gz, .tgz, .tar.bz2, .tar, .rar
    """
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
            # Lista de argumentos, nunca shell=True con un string interpolado:
            # así el nombre de carpeta/archivo no puede escapar la "comilla" e
            # inyectar comandos de shell (antes usaba os.system con f-string).
            result = subprocess.run(
                ["unrar", "x", str(archive_path), str(dest_path) + "/"],
                capture_output=True,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail="Para RAR instala: pip install rarfile && sudo apt install unrar"
                )
            return {"files_extracted": -1, "format": "RAR (via unrar)"}

    else:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: {filename}")


# Cada modpack puede guardar la RAM de la JVM en un sitio distinto según cómo
# se haya instalado, y no hay forma de saber cuál usa sin mirar — de ahí que
# tanto detectar como modificar prueben, en el mismo orden de prioridad:
# 1. user_jvm_args.txt: lo generan los instaladores oficiales de Forge/
#    NeoForge modernos. -Xms/-Xmx pueden venir en líneas separadas o
#    combinados en una sola (ej. "-Xmx12G -Xms4G"), y a veces con más flags
#    JVM pegados en esa misma línea (ej. "-Xmx12G -Xms4G -XX:+UseG1GC") — por
#    eso se sustituye el token exacto con regex en vez de reemplazar la línea
#    entera, que perdería cualquier flag que compartiera línea con -Xmx/-Xms.
# 2. variables.txt: formato más viejo (scripts de itzg/docker-minecraft-server
#    y similares), con los flags dentro de JAVA_ARGS="...".
# 3. El propio script de arranque (run.sh/start.sh/startserver.sh): vanilla,
#    Fabric y Quilt (ver _write_run_script en services/server_create.py)
#    embeben "-Xms... -Xmx..." directo en la línea "java ...", sin ningún
#    archivo de configuración aparte.
# Si no aparece en NINGUNO de los tres, se da por no detectable: mejor avisar
# que "no se puede editar la RAM de este modpack desde aquí" que insertar
# flags a ciegas en un script cuya estructura no se conoce.
_XMS_RE = re.compile(r'-Xms\S+', re.IGNORECASE)
_XMX_RE = re.compile(r'-Xmx\S+', re.IGNORECASE)
_RAM_SCRIPT_NAMES = ("run.sh", "start.sh", "startserver.sh")


def _detect_ram_in_text(text: str) -> tuple[str | None, str | None]:
    xms_m = re.search(r'-Xms(\S+)', text, re.IGNORECASE)
    xmx_m = re.search(r'-Xmx(\S+)', text, re.IGNORECASE)
    return (xms_m.group(1) if xms_m else None, xmx_m.group(1) if xmx_m else None)


def detect_jvm_ram(server_dir: Path) -> dict:
    """
    Detecta la RAM configurada actualmente, sin modificar nada. Devuelve
    {"ram_min", "ram_max", "source"} — source es el nombre del archivo donde
    se encontró (o None si no se pudo detectar en ninguno de los tres sitios
    que prueba configure_jvm_ram()).
    """
    jvm_path = server_dir / "user_jvm_args.txt"
    if jvm_path.exists():
        active_text = "\n".join(
            line for line in jvm_path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        ram_min, ram_max = _detect_ram_in_text(active_text)
        if ram_min or ram_max:
            return {"ram_min": ram_min, "ram_max": ram_max, "source": "user_jvm_args.txt"}

    vars_path = server_dir / "variables.txt"
    if vars_path.exists():
        m = re.search(r'JAVA_ARGS\s*=\s*"([^"]*)"', vars_path.read_text(encoding="utf-8"), re.IGNORECASE)
        if m:
            ram_min, ram_max = _detect_ram_in_text(m.group(1))
            if ram_min or ram_max:
                return {"ram_min": ram_min, "ram_max": ram_max, "source": "variables.txt"}

    for script_name in _RAM_SCRIPT_NAMES:
        script_path = server_dir / script_name
        if not script_path.exists():
            continue
        ram_min, ram_max = _detect_ram_in_text(script_path.read_text(encoding="utf-8", errors="replace"))
        if ram_min or ram_max:
            return {"ram_min": ram_min, "ram_max": ram_max, "source": script_name}

    return {"ram_min": None, "ram_max": None, "source": None}


def configure_jvm_ram(dest_path: Path, ram_min: str, ram_max: str) -> str | None:
    """
    Modifica la configuración de RAM JVM (ver detect_jvm_ram para dónde
    busca). Devuelve el nombre del archivo modificado, o None si no se
    encontró ninguno de los tres sitios conocidos (no se toca nada en ese caso).
    """
    # 1. user_jvm_args.txt
    jvm_path = dest_path / "user_jvm_args.txt"
    if jvm_path.exists():
        lines = jvm_path.read_text(encoding="utf-8").splitlines(keepends=True)
        xms_found = xmx_found = False
        new_lines = []
        for line in lines:
            if line.lstrip().startswith("#"):
                new_lines.append(line)
                continue
            new_line = line
            if _XMS_RE.search(new_line):
                new_line = _XMS_RE.sub(f"-Xms{ram_min}", new_line)
                xms_found = True
            if _XMX_RE.search(new_line):
                new_line = _XMX_RE.sub(f"-Xmx{ram_max}", new_line)
                xmx_found = True
            new_lines.append(new_line)
        if not xms_found:
            new_lines.insert(0, f"-Xms{ram_min}\n")
        if not xmx_found:
            new_lines.insert(0 if not xms_found else 1, f"-Xmx{ram_max}\n")
        jvm_path.write_text("".join(new_lines), encoding="utf-8")
        return "user_jvm_args.txt"

    # 2. variables.txt (JAVA_ARGS="...")
    vars_path = dest_path / "variables.txt"
    if vars_path.exists():
        content = vars_path.read_text(encoding="utf-8")
        if re.search(r'JAVA_ARGS\s*=', content, re.IGNORECASE):
            xms_found = bool(_XMS_RE.search(content))
            xmx_found = bool(_XMX_RE.search(content))
            lines = content.splitlines(keepends=True)
            new_lines = []
            for line in lines:
                # El tercer grupo captura desde la comilla de cierre hasta el
                # final de la línea INCLUYENDO su salto de línea — con solo
                # ".*" (sin \n) el \n final quedaba fuera de todos los grupos
                # y se perdía al reconstruir la línea, fusionándola con la
                # siguiente.
                m = re.match(r'(\s*JAVA_ARGS\s*=\s*")([^"]*)("[^\n]*\n?)', line, re.IGNORECASE)
                if not m:
                    new_lines.append(line)
                    continue
                args = m.group(2)
                args = _XMS_RE.sub(f"-Xms{ram_min}", args) if xms_found else f"-Xms{ram_min} " + args
                args = _XMX_RE.sub(f"-Xmx{ram_max}", args) if xmx_found else f"-Xmx{ram_max} " + args
                new_lines.append(f"{m.group(1)}{args}{m.group(3)}")
            vars_path.write_text("".join(new_lines), encoding="utf-8")
            return "variables.txt"

    # 3. Script de arranque (vanilla/Fabric/Quilt): solo si YA tiene -Xms/-Xmx
    # embebidos — insertarlos a ciegas en un script de estructura desconocida
    # podría romperlo.
    for script_name in _RAM_SCRIPT_NAMES:
        script_path = dest_path / script_name
        if not script_path.exists():
            continue
        text = script_path.read_text(encoding="utf-8", errors="replace")
        if not (_XMS_RE.search(text) or _XMX_RE.search(text)):
            continue
        new_text = _XMS_RE.sub(f"-Xms{ram_min}", text)
        new_text = _XMX_RE.sub(f"-Xmx{ram_max}", new_text)
        script_path.write_text(new_text, encoding="utf-8")
        return script_name

    return None
