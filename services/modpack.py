"""
services/modpack.py - Lógica de negocio relacionada con modpacks.

Contiene:
- Detección de versión de Minecraft y modloader (NeoForge, Forge, Fabric, Quilt, Vanilla)
- Lectura de metadatos de mods (.jar)
- Comprobación de compatibilidad de versión
- Detección de mods instalados
- Parseo y guardado de server.properties
- Activación forzada de RCON antes de arrancar (ensure_rcon_enabled)
- Gestión de mundos (listar, activar, crear, borrar)
- Análisis de crash reports
"""
import re
import json
import zipfile
import io
import secrets
from itertools import zip_longest
from pathlib import Path

from config import DEFAULT_SERVERS_PATH

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


# ── Metadatos de mods ──────────────────────────────────────────────────────────

_NO_METADATA_ERROR = "No se encontró metadata de mod (mods.toml / fabric.mod.json)"


def _mc_versions_from_toml(text: str, mod_id: str | None) -> list:
    """
    Extrae el/los versionRange del bloque [[dependencies.<mod_id>]] cuyo modId
    sea "minecraft". Un mods.toml también declara ahí el rango del propio loader
    (neoforge/forge) y, si el jar empaqueta varios mods, bloques de otros modIds;
    hay que anclarse al bloque de ESTE mod para no confundir un rango con otro.
    """
    if not mod_id:
        return []
    versions = []
    header_re = re.compile(r'\[\[\s*dependencies\.["\']?' + re.escape(mod_id) + r'["\']?\s*\]\]', re.IGNORECASE)
    blocks = header_re.split(text)[1:]
    for block in blocks:
        end = re.search(r'\n\s*\[', block)
        block_text = block[:end.start()] if end else block
        if re.search(r'modId\s*=\s*[\'"]minecraft[\'"]', block_text, re.IGNORECASE):
            vm = re.search(r'versionRange\s*=\s*[\'"]([^\'"]+)[\'"]', block_text)
            if vm:
                versions.append(vm.group(1))
    return versions


def read_mod_metadata(jar_bytes: bytes) -> dict:
    """
    Lee los metadatos de un mod desde sus bytes JAR.
    Soporta NeoForge/Forge (mods.toml), Fabric (fabric.mod.json) y Quilt.
    Devuelve: {mc_versions, modloader, mod_id, mod_version, error}
    """
    result = {"mc_versions": [], "modloader": None, "mod_id": None, "mod_version": None, "error": None}
    try:
        with zipfile.ZipFile(io.BytesIO(jar_bytes)) as zf:
            names = zf.namelist()

            # NeoForge / Forge
            toml_file = None
            if "META-INF/neoforge.mods.toml" in names:
                toml_file = "META-INF/neoforge.mods.toml"
                result["modloader"] = "NeoForge"
            elif "META-INF/mods.toml" in names:
                toml_file = "META-INF/mods.toml"
                result["modloader"] = "NeoForge/Forge"

            if toml_file:
                text = zf.read(toml_file).decode("utf-8", errors="replace")
                m = re.search(r'modId\s*=\s*[\'"]([^\'"]+)[\'"]', text)
                if m:
                    result["mod_id"] = m.group(1)
                m = re.search(r'^version\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.MULTILINE)
                if m:
                    result["mod_version"] = m.group(1)
                result["mc_versions"] = _mc_versions_from_toml(text, result["mod_id"])
                return result

            # Fabric
            if "fabric.mod.json" in names:
                result["modloader"] = "Fabric"
                data = json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="replace"))
                result["mod_id"] = data.get("id")
                result["mod_version"] = data.get("version")
                depends = data.get("depends", {})
                mc = depends.get("minecraft") or depends.get("fabricloader")
                if mc:
                    result["mc_versions"] = [mc] if isinstance(mc, str) else mc
                return result

            # Quilt
            if "quilt.mod.json" in names:
                result["modloader"] = "Quilt"
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="replace"))
                meta = data.get("quilt_loader", {})
                result["mod_id"] = meta.get("id")
                result["mod_version"] = meta.get("version")
                for dep in meta.get("depends", []):
                    if isinstance(dep, dict) and dep.get("id") == "minecraft":
                        v = dep.get("versions")
                        if v:
                            result["mc_versions"] = [v] if isinstance(v, str) else v
                return result

            result["error"] = _NO_METADATA_ERROR

    except Exception as e:
        result["error"] = str(e)

    return result


def compare_mod_versions(v1: str, v2: str) -> int:
    """
    Compara dos versiones de mod comparando sus segmentos numéricos (ignora sufijos
    como '+build' o '-forge'). Devuelve -1 si v1 < v2, 1 si v1 > v2, 0 si son iguales.
    """
    def parts(v):
        return [int(x) for x in re.findall(r'\d+', v or '')]

    for a, b in zip_longest(parts(v1), parts(v2), fillvalue=0):
        if a != b:
            return -1 if a < b else 1
    return 0


def find_installed_mod_by_id(mods_dir: Path, mod_id: str):
    """
    Busca en mods_dir un jar ya instalado cuyo mod_id coincida con el dado.
    Devuelve (Path, meta dict) o (None, None) si no hay coincidencia.
    """
    if not mod_id:
        return None, None
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        try:
            existing_meta = read_mod_metadata(f.read_bytes())
        except Exception:
            continue
        if existing_meta.get("mod_id") and existing_meta["mod_id"] == mod_id:
            return f, existing_meta
    return None, None


def mod_display_name(filename: str) -> str:
    """Deriva un nombre legible a partir del nombre de archivo de un mod."""
    p = Path(filename)
    stem = p.stem if not p.name.endswith(".disabled") else p.stem.replace(".jar", "").replace(".zip", "")
    clean = re.sub(r'[-_+][0-9].*$', '', stem)
    clean = re.sub(r'[-_](forge|fabric|neoforge|mc|minecraft).*$', '', clean, flags=re.IGNORECASE)
    clean = clean.replace("-", " ").replace("_", " ").strip()
    return clean or stem


def process_mod_jar(mods_dir: Path, filename: str, jar_bytes: bytes, server_mc: str) -> dict:
    """
    Evalúa un .jar de mod contra los mods ya instalados en mods_dir y, si corresponde,
    lo instala. Usado tanto por la subida individual como por la subida masiva (zip/carpeta).

    Si status == "needs_confirmation" NO se escribe nada en disco: quien llama decide
    qué hacer con jar_bytes (p.ej. guardarlos a la espera de que el usuario confirme
    si quiere degradar la versión instalada).

    Devuelve dict con: status, filename, display_name, mod_id, mod_version, detail,
    y según el caso: existing_filename, existing_version, replaced_filename, previous_version.
    status: "added" | "already_installed" | "needs_confirmation" | "incompatible" | "invalid"
    """
    display_name = mod_display_name(filename)
    meta = read_mod_metadata(jar_bytes)

    # Un jar sin mods.toml/fabric.mod.json/quilt.mod.json reconocible no es
    # necesariamente inválido: puede ser una librería/módulo de carga temprana
    # (p.ej. Kotlin for Forge, Drippy) que legítimamente no declara esa metadata.
    if meta.get("error") and meta["error"] != _NO_METADATA_ERROR:
        return {
            "status": "invalid", "filename": filename, "display_name": display_name,
            "mod_id": None, "mod_version": None,
            "detail": meta["error"],
        }

    if server_mc and meta["mc_versions"] and not mc_version_compatible(server_mc, meta["mc_versions"]):
        return {
            "status": "incompatible", "filename": filename, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "detail": f"Incompatible: requiere MC {', '.join(meta['mc_versions'])} pero el servidor es {server_mc}",
        }

    existing_path, existing_meta = find_installed_mod_by_id(mods_dir, meta.get("mod_id"))

    if existing_path:
        cmp = compare_mod_versions(meta.get("mod_version"), existing_meta.get("mod_version"))
        if cmp < 0:
            return {
                "status": "needs_confirmation", "filename": filename, "display_name": display_name,
                "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
                "existing_filename": existing_path.name, "existing_version": existing_meta.get("mod_version"),
                "detail": f"Versión más antigua (v{meta.get('mod_version')}) que la instalada "
                          f"(v{existing_meta.get('mod_version')} en {existing_path.name})",
            }
        if cmp == 0:
            return {
                "status": "already_installed", "filename": filename, "display_name": display_name,
                "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
                "existing_filename": existing_path.name,
                "detail": f"Ya está instalada la misma versión (v{meta.get('mod_version')})",
            }
        was_disabled = existing_path.name.endswith(".disabled")
        replaced_filename = existing_path.name
        previous_version = existing_meta.get("mod_version")
        existing_path.unlink()
        dest = mods_dir / (filename + ".disabled" if was_disabled else filename)
        dest.write_bytes(jar_bytes)
        return {
            "status": "added", "filename": dest.name, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "replaced_filename": replaced_filename, "previous_version": previous_version,
            "detail": f"Actualizado desde v{previous_version}",
        }

    dest = mods_dir / filename
    if dest.exists():
        # No pudimos identificar el mod_id (sin metadata reconocible), pero ya hay
        # un archivo con el mismo nombre: lo más probable es que sea el mismo mod.
        return {
            "status": "already_installed", "filename": filename, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "existing_filename": filename,
            "detail": f"{filename} ya existe en mods/",
        }
    dest.write_bytes(jar_bytes)
    return {
        "status": "added", "filename": filename, "display_name": display_name,
        "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
        "detail": None,
    }


def mc_version_compatible(server_mc: str, mod_versions: list) -> bool:
    """
    Comprueba si la versión del servidor es compatible con los rangos de versión del mod.
    Soporta: exacto, wildcard (1.21.x), rangos Maven ([1.21,1.22)).

    El límite superior de un rango se trata como inclusivo aunque esté escrito con
    paréntesis ')': en la práctica muchísimos mods declaran p.ej. "[1.21,1.21.1)"
    para una versión con la que en verdad sí son compatibles (la propia NeoForge
    no aplica este campo de forma estricta), así que ser laxos aquí evita bloquear
    instalaciones válidas. Rangos que no podemos interpretar (p.ej. variables de
    plantilla sin resolver como "${minecraft_version_range}") se ignoran en vez de
    contar como incompatibilidad.
    """
    if not server_mc or not mod_versions:
        return True

    def ver_tuple(v: str):
        return tuple(int(x) for x in v.split('.') if x.isdigit())

    recognized_any = False
    for vrange in mod_versions:
        vrange = vrange.strip()
        if not vrange or '$' in vrange or '{' in vrange:
            continue
        if vrange == server_mc:
            return True
        # Versión "pelada" sin rango, p.ej. "1.21": se toma como prefijo (equivale a "1.21.x")
        if re.match(r'^\d+(\.\d+)*$', vrange):
            recognized_any = True
            if server_mc == vrange or server_mc.startswith(vrange + '.'):
                return True
            continue
        if re.match(r'^[\d.]+[.*x]$', vrange):
            recognized_any = True
            prefix = re.sub(r'[.*x]+$', '', vrange).rstrip('.')
            if server_mc.startswith(prefix):
                return True
            continue
        # Rango Maven de valor único: [1.21.1] significa exactamente 1.21.1
        m_exact = re.match(r'^\[([\d.]+)\]$', vrange)
        if m_exact:
            recognized_any = True
            if ver_tuple(server_mc) == ver_tuple(m_exact.group(1)):
                return True
            continue
        m = re.match(r'^[\[\(]([\d.]*),\s*([\d.]*)[\]\)]$', vrange)
        if m:
            recognized_any = True
            lo, hi = m.group(1), m.group(2)
            sv = ver_tuple(server_mc)
            ok = True
            if lo:
                ok = ok and (sv >= ver_tuple(lo) if vrange[0] == '[' else sv > ver_tuple(lo))
            if hi:
                ok = ok and sv <= ver_tuple(hi)
            if ok:
                return True

    return not recognized_any


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
    props_file.write_text("".join(new_lines), encoding="utf-8")
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


# ── Análisis de crash reports ──────────────────────────────────────────────────

def analyze_crash(text: str, modpack: str) -> list:
    """
    Intenta identificar qué mod causó el crash comparando el stack trace
    con los jars instalados en mods/.
    Devuelve una lista de strings con pistas.
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    culprits = []

    if mods_dir.exists():
        mod_jars = [f.name for f in mods_dir.iterdir() if f.is_file() and f.suffix == ".jar"]
        for jar in mod_jars:
            mod_id = re.sub(r'[-_+][0-9].*$', '', jar.replace('.jar', ''))
            if mod_id.lower() in text.lower():
                culprits.append(f"Posible culpable: {jar}")

    # Buscar líneas de excepción relevantes
    for line in text.splitlines():
        if "Caused by:" in line or "Exception" in line:
            culprits.append(line.strip())
            if len(culprits) >= 5:
                break

    return culprits
