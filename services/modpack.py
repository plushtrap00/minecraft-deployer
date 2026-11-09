"""
services/modpack.py - Lógica de negocio relacionada con modpacks.

Contiene:
- Detección de versión de Minecraft y modloader (NeoForge, Forge, Fabric, Quilt, Vanilla)
- Detección de mods instalados
- Parseo y guardado de server.properties
- Activación forzada de RCON antes de arrancar (ensure_rcon_enabled)
- Gestión de mundos (listar, activar, crear, borrar)
- Limpieza de logs y crash reports antiguos

El resto de lo relacionado con mods está en módulos propios:
mod_metadata.py (leer un .jar, comparar versiones), mod_checks.py (solo
cliente, duplicados, process_mod_jar), pending_mods.py (mods que instalar a
mano) y crash_analysis.py (leer crash reports).
"""
import re
import secrets
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from app_constants import LOG_CRASH_RETENTION_COUNT
from services.secure_files import atomic_write_text

# ── Detección de versión ───────────────────────────────────────────────────────

FORGE_MC_MAP = {
    "54": "1.21.1", "53": "1.21", "52": "1.20.6", "51": "1.20.4",
    "49": "1.20.2", "47": "1.20.1", "45": "1.20", "44": "1.19.4",
    "43": "1.19.3", "42": "1.19.2", "41": "1.19", "40": "1.18.2",
    "39": "1.18.1", "38": "1.18", "37": "1.17.1", "36": "1.16.5",
}


def mc_from_neoforge(ver: str) -> str | None:
    """Deriva la versión de MC a partir de la versión de NeoForge."""
    m = re.match(r'^(\d+)\.(\d+)\.', ver)
    if m:
        major, minor = m.group(1), m.group(2)
        return f"1.{major}.{minor}" if minor != "0" else f"1.{major}"
    return None


def mc_from_forge(ver: str) -> str | None:
    """Deriva la versión de MC a partir de la versión mayor de Forge."""
    m = re.match(r'^(\d+)\.', ver)
    if m:
        return FORGE_MC_MAP.get(m.group(1))
    return None


_version_cache: dict = {}  # modpack_name -> (dir_mtime, result)


def detect_modpack_version(modpack: str) -> dict:
    """
    Detecta la versión de MC y el modloader de un modpack.
    Orden de prioridad: variables.txt > jar filenames > server.properties (vanilla).
    Resultado cacheado por mtime del directorio.
    """
    base = DEFAULT_SERVERS_PATH / modpack
    try:
        mtime = base.stat().st_mtime
    except Exception:
        mtime = None

    if modpack in _version_cache:
        cached_mtime, cached_result = _version_cache[modpack]
        if cached_mtime == mtime:
            return cached_result

    result = _detect_modpack_version_impl(base)
    _version_cache[modpack] = (mtime, result)
    return result


def _detect_modpack_version_impl(base: Path) -> dict:
    result = {"mc_version": None, "modloader": None, "modloader_version": None}

    # 1. variables.txt
    for fname in ["variables.txt", "Variables.txt"]:
        vfile = base / fname
        if not vfile.exists():
            continue
        text = vfile.read_text(encoding="utf-8", errors="replace")
        for line in text.split("\n"):
            line = line.strip()
            m = re.match(r'^MINECRAFT_VERSION\s*=\s*(.+)$', line)
            if m:
                result["mc_version"] = m.group(1).strip().strip('"')
            m = re.match(r'^MODLOADER\s*=\s*(.+)$', line)
            if m:
                result["modloader"] = m.group(1).strip().strip('"')
            m = re.match(r'^MODLOADER_VERSION\s*=\s*(.+)$', line)
            if m:
                result["modloader_version"] = m.group(1).strip().strip('"')
        if not result["mc_version"] and result["modloader_version"] and result["modloader"]:
            ml = result["modloader"].lower()
            if "neoforge" in ml:
                result["mc_version"] = mc_from_neoforge(result["modloader_version"])
            elif "forge" in ml:
                result["mc_version"] = mc_from_forge(result["modloader_version"])
        if result["mc_version"] or result["modloader"]:
            return result

    # 2. Nombres de jars en la raíz o en libraries/
    for search_dir in [base, base / "libraries"]:
        if not search_dir.exists():
            continue
        for f in search_dir.iterdir():
            name = f.name.lower()
            m = re.match(r'neoforge[-_](1\.[\d.]+)[-_]([\d.]+)', name)
            if m:
                result.update(mc_version=m.group(1), modloader="NeoForge", modloader_version=m.group(2))
                return result
            m = re.match(r'neoforge[-_](\d+\.[\d.]+)', name)
            if m:
                ver = m.group(1)
                result.update(modloader="NeoForge", modloader_version=ver, mc_version=mc_from_neoforge(ver))
                return result
            m = re.match(r'forge[-_]([\d.]+)[-_]([\d.]+)', name)
            if m:
                result.update(mc_version=m.group(1), modloader="Forge", modloader_version=m.group(2))
                return result
            m = re.match(r'forge[-_](\d+\.[\d.]+)', name)
            if m:
                ver = m.group(1)
                result.update(modloader="Forge", modloader_version=ver, mc_version=mc_from_forge(ver))
                return result
            m = re.match(r'fabric.*mc\.([\d.]+)', name)
            if m:
                result.update(mc_version=m.group(1), modloader="Fabric")
                return result
            m = re.match(r'quilt.*mc\.([\d.]+)', name)
            if m:
                result.update(mc_version=m.group(1), modloader="Quilt")
                return result

    # 3. server.properties existe → Vanilla
    if (base / "server.properties").exists():
        result["modloader"] = "Vanilla"

    return result


# ── Mods instalados ────────────────────────────────────────────────────────────

def detect_installed_mods(modpack: str) -> set:
    """Devuelve el conjunto de nombres de jar (en minúsculas) instalados en mods/."""
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return set()
    return {
        f.name.lower()
        for f in mods_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".jar", ".zip"}
    }


def has_mod_keyword(mod_names: set, keyword: str) -> bool:
    return any(keyword in name for name in mod_names)


# ── server.properties ──────────────────────────────────────────────────────────

def parse_server_properties(modpack: str) -> dict:
    """Lee server.properties y devuelve un dict {clave: valor}."""
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    props = {}
    if not props_file.exists():
        return props
    for line in props_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        props[key.strip()] = val.strip()
    return props


def save_server_property(modpack: str, key: str, value: str) -> bool:
    """Actualiza una propiedad en server.properties preservando comentarios y orden."""
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        return False
    lines = props_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                new_lines.append(f"{key}={value}\n")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    atomic_write_text(props_file, "".join(new_lines))
    return True


def ensure_rcon_enabled(modpack: str) -> dict | None:
    """
    Fuerza RCON activado en server.properties antes de arrancar el servidor.
    Genera una contraseña aleatoria si no hay una configurada, y desactiva
    broadcast-rcon-to-ops para que el feedback de los comandos ejecutados por
    RCON (ej. list/tps para refrescar métricas) no llene la consola/log.
    Devuelve {"host": str, "port": int, "password": str} o None si server.properties
    no existe aún. "host" es el valor de server-ip (127.0.0.1 si está vacío), porque
    Minecraft solo escucha RCON en esa dirección cuando server-ip está fijado.
    """
    props_file = DEFAULT_SERVERS_PATH / modpack / "server.properties"
    if not props_file.exists():
        return None

    props = parse_server_properties(modpack)

    if props.get("enable-rcon") != "true":
        save_server_property(modpack, "enable-rcon", "true")

    password = props.get("rcon.password", "").strip()
    if not password:
        password = secrets.token_urlsafe(18)
        save_server_property(modpack, "rcon.password", password)

    port_str = props.get("rcon.port", "").strip()
    port = int(port_str) if port_str.isdigit() else 25575
    if not port_str:
        save_server_property(modpack, "rcon.port", str(port))

    if props.get("broadcast-rcon-to-ops") != "false":
        save_server_property(modpack, "broadcast-rcon-to-ops", "false")

    host = props.get("server-ip", "").strip() or "127.0.0.1"

    return {"host": host, "port": port, "password": password}


# ── Gestión de mundos ──────────────────────────────────────────────────────────

def get_worlds(modpack: str) -> dict:
    """
    Detecta los mundos de un modpack.
    Un mundo es una carpeta que contiene un directorio 'region/' o 'level.dat'.
    Devuelve {active_world, worlds: [...]}.
    """
    base = DEFAULT_SERVERS_PATH / modpack
    props = parse_server_properties(modpack)
    active = props.get("level-name", "world")

    worlds = []
    if base.exists():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            if (d / "region").exists() or (d / "level.dat").exists():
                size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / (1024 * 1024)
                worlds.append({
                    "name": d.name,
                    "active": d.name == active,
                    "has_nether": (d / "DIM-1" / "region").exists(),
                    "has_end": (d / "DIM1" / "region").exists(),
                    "size_mb": round(size_mb, 1),
                })

    return {"active_world": active, "worlds": worlds}


# ── Logs & crash reports ────────────────────────────────────────────────────────

_CURRENT_LOG_FILENAMES = {"latest.log", "debug.log"}


def prune_old_logs_and_crashes(modpack: str, keep: int = LOG_CRASH_RETENTION_COUNT) -> None:
    """
    Borra los logs rotados (logs/*.log.gz de sesiones anteriores) y los crash
    reports más viejos, dejando solo los `keep` más recientes de cada carpeta.
    latest.log y debug.log no cuentan para este límite ni se tocan nunca: son
    los de la sesión actual, no logs rotados de sesiones pasadas.

    Se ordena por fecha de modificación real (mtime), no por nombre: los
    crash reports sí llevan la fecha en el nombre ("crash-2024-01-15_
    10.23.45-server.txt"), pero los logs rotados no siempre ("debug-1.log.gz"
    vs "debug-5.log.gz" — el orden real depende de cómo numere el rotador de
    log4j2, no es necesariamente ascendente/descendente por fecha). mtime es
    fiable para los dos casos por igual, y es el mismo criterio que usa
    get_log_list() para listarlos, para que "los últimos `keep` que se ven" y
    "los últimos `keep` que se conservan" sean siempre los mismos.
    """
    base = DEFAULT_SERVERS_PATH / modpack

    logs_dir = base / "logs"
    if logs_dir.exists():
        rotated = sorted(
            (f for f in logs_dir.iterdir() if f.is_file() and f.name not in _CURRENT_LOG_FILENAMES),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in rotated[keep:]:
            try:
                old.unlink()
            except Exception:
                pass

    crash_dir = base / "crash-reports"
    if crash_dir.exists():
        crashes = sorted(
            (f for f in crash_dir.iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old in crashes[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
