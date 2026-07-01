"""
services/utils.py - Utilidades generales de la aplicación.

Contiene:
- get_system_ram_gb(): RAM total del sistema desde /proc/meminfo
- get_modpacks(): lista de modpacks instalados
- get_mod_configs(): árbol de archivos de config de un modpack
- get_kubejs_files(): árbol de archivos KubeJS
- get_world_files(): árbol de archivos de texto editables de un mundo
- extract_archive(): descomprimir ZIP/TAR/RAR
- configure_jvm_ram(): modificar RAM en user_jvm_args.txt / variables.txt
"""
import os
import re
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
            result = os.system(f"unrar x '{archive_path}' '{dest_path}/'")
            if result != 0:
                raise HTTPException(
                    status_code=500,
                    detail="Para RAR instala: pip install rarfile && sudo apt install unrar"
                )
            return {"files_extracted": -1, "format": "RAR (via unrar)"}

    else:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: {filename}")


def configure_jvm_ram(dest_path: Path, ram_min: str, ram_max: str) -> str | None:
    """
    Modifica la configuración de RAM JVM en user_jvm_args.txt o variables.txt.
    Devuelve el nombre del archivo modificado, o None si no se encontró ninguno.
    """
    # Intentar user_jvm_args.txt primero
    jvm_path = dest_path / "user_jvm_args.txt"
    if jvm_path.exists():
        lines = jvm_path.read_text(encoding="utf-8").splitlines(keepends=True)
        xms_found = xmx_found = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("-Xms") and not stripped.startswith("#"):
                new_lines.append(f"-Xms{ram_min}\n")
                xms_found = True
            elif stripped.startswith("-Xmx") and not stripped.startswith("#"):
                new_lines.append(f"-Xmx{ram_max}\n")
                xmx_found = True
            else:
                new_lines.append(line)
        if not xms_found:
            new_lines.insert(0, f"-Xms{ram_min}\n")
        if not xmx_found:
            new_lines.insert(0 if not xms_found else 1, f"-Xmx{ram_max}\n")
        jvm_path.write_text("".join(new_lines), encoding="utf-8")
        return "user_jvm_args.txt"

    # Intentar variables.txt
    vars_path = dest_path / "variables.txt"
    if vars_path.exists():
        content = vars_path.read_text(encoding="utf-8")
        xms_found = bool(re.search(r'-Xms\S+', content, re.IGNORECASE))
        xmx_found = bool(re.search(r'-Xmx\S+', content, re.IGNORECASE))
        lines = content.splitlines(keepends=True)
        new_lines = []
        for line in lines:
            # Buscar línea con JAVA_ARGS que contenga -Xms/-Xmx
            if re.search(r'JAVA_ARGS\s*=', line, re.IGNORECASE):
                # Extraer el valor entre comillas si existe
                m = re.match(r'(\s*JAVA_ARGS\s*=\s*")([^"]*)"', line)
                if m:
                    args = m.group(2)
                    args = re.sub(r'-Xms\S+', f'-Xms{ram_min}', args, flags=re.IGNORECASE)
                    args = re.sub(r'-Xmx\S+', f'-Xmx{ram_max}', args, flags=re.IGNORECASE)
                    if not xms_found:
                        args = f'-Xms{ram_min} ' + args
                    if not xmx_found:
                        args = f'-Xmx{ram_max} ' + args
                    new_lines.append(f'{m.group(1)}{args}"\n')
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        vars_path.write_text("".join(new_lines), encoding="utf-8")
        return "variables.txt"

    return None
