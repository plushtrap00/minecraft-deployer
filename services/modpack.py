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
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from app_constants import LOG_CRASH_RETENTION_COUNT

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


def _mods_block(text: str) -> str:
    """
    Recorta el texto del mods.toml a la (primera) tabla [[mods]]. Sin esto, un
    re.search("modId=...") suelto puede matchear el modId de un bloque
    [[dependencies.X]] (que también tiene su propio "modId=") si ese bloque
    aparece antes que [[mods]] en el archivo, confundiendo el modId del propio
    mod con el de una de sus dependencias.
    """
    m = re.search(r'\[\[\s*mods\s*\]\]', text, re.IGNORECASE)
    if not m:
        return text
    rest = text[m.end():]
    end = re.search(r'\n\s*\[', rest)
    return rest[:end.start()] if end else rest


def _toml_dep_side(text: str, mod_id: str | None, dep_modid: str) -> str | None:
    """
    Extrae el campo side= del bloque [[dependencies.<mod_id>]] cuyo modId sea
    dep_modid (forge/neoforge) — no es un campo oficial a nivel de mod como el
    "environment" de Fabric, es una convención de comunidad para marcar que LA
    DEPENDENCIA DEL PROPIO LOADER solo hace falta en un lado. Mismo anclaje que
    _toml_dep_version_ranges para no confundir bloques de distintos modIds.
    """
    if not mod_id:
        return None
    header_re = re.compile(r'\[\[\s*dependencies\.["\']?' + re.escape(mod_id) + r'["\']?\s*\]\]', re.IGNORECASE)
    blocks = header_re.split(text)[1:]
    for block in blocks:
        end = re.search(r'\n\s*\[', block)
        block_text = block[:end.start()] if end else block
        if re.search(r'modId\s*=\s*[\'"]' + re.escape(dep_modid) + r'[\'"]', block_text, re.IGNORECASE):
            sm = re.search(r'side\s*=\s*[\'"]([^\'"]+)[\'"]', block_text, re.IGNORECASE)
            if sm:
                return sm.group(1)
    return None


def _toml_dep_version_ranges(text: str, mod_id: str | None, dep_modid: str) -> list:
    """
    Extrae el/los versionRange del bloque [[dependencies.<mod_id>]] cuyo modId
    sea dep_modid (p.ej. "minecraft", "neoforge" o "forge"). Un mods.toml declara
    ahí tanto el rango de MC como el del propio loader y, si el jar empaqueta
    varios mods, bloques de otros modIds; hay que anclarse al bloque de ESTE mod
    para no confundir un rango con otro.
    """
    if not mod_id:
        return []
    versions = []
    header_re = re.compile(r'\[\[\s*dependencies\.["\']?' + re.escape(mod_id) + r'["\']?\s*\]\]', re.IGNORECASE)
    blocks = header_re.split(text)[1:]
    for block in blocks:
        end = re.search(r'\n\s*\[', block)
        block_text = block[:end.start()] if end else block
        if re.search(r'modId\s*=\s*[\'"]' + re.escape(dep_modid) + r'[\'"]', block_text, re.IGNORECASE):
            vm = re.search(r'versionRange\s*=\s*[\'"]([^\'"]+)[\'"]', block_text)
            if vm:
                versions.append(vm.group(1))
    return versions


def _manifest_implementation_version(zf: zipfile.ZipFile) -> str | None:
    """
    mods.toml admite "${file.jarVersion}" como valor de version: no es un
    string real, es un token que NeoForge/Forge resuelve en tiempo de
    ejecución leyendo Implementation-Version del MANIFEST.MF del propio jar.
    Como nosotros no somos el loader, tenemos que resolverlo igual a mano.
    """
    if "META-INF/MANIFEST.MF" not in zf.namelist():
        return None
    text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    m = re.search(r'^Implementation-Version:\s*(.+)$', text, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip() or None


def read_mod_metadata(jar_bytes: bytes) -> dict:
    """
    Lee los metadatos de un mod desde sus bytes JAR.
    Soporta NeoForge/Forge (mods.toml), Fabric (fabric.mod.json) y Quilt.
    Devuelve: {mc_versions, modloader, mod_id, mod_version, side, error}

    "side" es el valor CRUDO declarado por el propio mod (sin normalizar):
    "client"/"server"/"*" para Fabric (campo oficial del loader), o el string
    de side= de su bloque de dependencia del loader para NeoForge/Forge
    (convención de comunidad, no oficial). None si no declara nada — usar
    classify_mod_side() para interpretarlo, no este campo directamente.
    """
    result = {
        "mc_versions": [], "loader_versions": {}, "modloader": None,
        "mod_id": None, "mod_version": None, "side": None, "error": None,
    }
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
                mods_block = _mods_block(text)
                m = re.search(r'modId\s*=\s*[\'"]([^\'"]+)[\'"]', mods_block)
                if m:
                    result["mod_id"] = m.group(1)
                m = re.search(r'^[ \t]*version\s*=\s*[\'"]([^\'"]+)[\'"]', mods_block, re.MULTILINE)
                if m:
                    result["mod_version"] = m.group(1)
                if result["mod_version"] and "${" in result["mod_version"]:
                    result["mod_version"] = _manifest_implementation_version(zf)
                result["mc_versions"] = _toml_dep_version_ranges(text, result["mod_id"], "minecraft")
                for loader_key in ("neoforge", "forge"):
                    ranges = _toml_dep_version_ranges(text, result["mod_id"], loader_key)
                    if ranges:
                        result["loader_versions"][loader_key] = ranges
                    # side= en el bloque de dependencia del propio loader: convención
                    # de comunidad para "esta dependencia (y por ende el mod) solo
                    # hace falta en un lado". No todos los mods client-only la declaran.
                    side = _toml_dep_side(text, result["mod_id"], loader_key)
                    if side:
                        result["side"] = side
                return result

            # Fabric
            if "fabric.mod.json" in names:
                result["modloader"] = "Fabric"
                data = json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="replace"))
                result["mod_id"] = data.get("id")
                result["mod_version"] = data.get("version")
                if result["mod_version"] and "${" in result["mod_version"]:
                    result["mod_version"] = _manifest_implementation_version(zf)
                # "environment" SÍ es un campo oficial del spec de Fabric Loader
                # ("client"/"server"/"*"), a diferencia del "side" de Forge/NeoForge:
                # el propio loader lo usa para decidir si cargar el mod en un
                # dedicated server, así que cuando está declarado es una señal fiable.
                result["side"] = data.get("environment")
                depends = data.get("depends", {})
                mc = depends.get("minecraft")
                if mc:
                    result["mc_versions"] = [mc] if isinstance(mc, str) else mc
                loader_ver = depends.get("fabricloader")
                if loader_ver:
                    result["loader_versions"]["fabric"] = [loader_ver] if isinstance(loader_ver, str) else loader_ver
                return result

            # Quilt: no se extrae "side" aquí — a diferencia de Fabric, no hay
            # consenso claro sobre dónde vive un campo de entorno equivalente en
            # este manifest, y prefiero dejarlo en None (sin señal) antes que
            # arriesgarme a leer la clave equivocada y reportar un side falso.
            if "quilt.mod.json" in names:
                result["modloader"] = "Quilt"
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="replace"))
                meta = data.get("quilt_loader", {})
                result["mod_id"] = meta.get("id")
                result["mod_version"] = meta.get("version")
                if result["mod_version"] and "${" in result["mod_version"]:
                    result["mod_version"] = _manifest_implementation_version(zf)
                for dep in meta.get("depends", []):
                    if not isinstance(dep, dict):
                        continue
                    dep_id = dep.get("id")
                    v = dep.get("versions")
                    if not v:
                        continue
                    v = [v] if isinstance(v, str) else v
                    if dep_id == "minecraft":
                        result["mc_versions"] = v
                    elif dep_id in ("quilt_loader", "fabricloader"):
                        result["loader_versions"]["quilt"] = v
                return result

            result["error"] = _NO_METADATA_ERROR

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Detección de mods client-only ──────────────────────────────────────────────
#
# No hay una forma 100% fiable de saber esto para todos los loaders:
# - Fabric declara "environment" en su spec oficial (el propio loader lo usa
#   para decidir si cargar el mod en un dedicated server) → confianza alta.
# - Forge/NeoForge no tienen un campo equivalente a nivel de mod; lo más
#   cercano es que algunos mods marquen side="CLIENT" en el bloque de
#   dependencia de su propio loader, una convención de comunidad no aplicada
#   de forma consistente → confianza media, y solo cuando está presente.
# - Sin ninguna declaración (el caso más común en la práctica), se asume que
#   el mod hace falta en el server en vez de marcarlo "desconocido" — la
#   inmensa mayoría de los mods sin esta metadata sí son necesarios ahí.
# - Un valor de side/environment presente pero irreconocible si cuenta como
#   señal ambigua real → "unknown", en vez de adivinar.
#
# Caso aparte: mods de renderizado/apariencia que declaran side="BOTH" (en vez
# de "CLIENT") pese a que en la práctica revientan un servidor dedicado porque
# su propio código referencia clases de cliente (LWJGL, ClientLevel,
# ShaderInstance...) sin comprobar antes en qué lado están corriendo — la
# metadata por sí sola no basta para detectarlos, así que van en una lista
# explícita, confirmada mod a mod (viendo el .jar real y/o el traceback del
# crash), no una suposición genérica por nombre o categoría.
_KNOWN_CLIENT_ONLY_MOD_IDS = {
    "sodium": 'optimización de renderizado — usa LWJGL, que no existe en un servidor dedicado',
    "embeddium": 'optimización de renderizado — usa LWJGL, que no existe en un servidor dedicado',
    "rubidium": 'optimización de renderizado — usa LWJGL, que no existe en un servidor dedicado',
    "iris": 'shaders — renderizado de cliente',
    "oculus": 'shaders — renderizado de cliente',
    "euphoria_patcher": 'parche de shaders — referencia clases de cliente (LWJGL/ClientLevel) aunque declara side="BOTH"',
    "darkmodeeverywhere": 'tema visual del cliente — referencia clases de renderizado de cliente aunque declara side="BOTH"',
    "drippyloadingscreen": 'pantalla de carga del cliente — referencia clases de cliente (Screen) aunque declara side="BOTH"',
}


def classify_mod_side(meta: dict) -> dict:
    """
    Devuelve {"category": "server"|"client_only"|"unknown", "confidence":
    "high"|"medium"|None, "reason": str|None} a partir del dict que devuelve
    read_mod_metadata().
    """
    mod_id = meta.get("mod_id")
    if mod_id in _KNOWN_CLIENT_ONLY_MOD_IDS:
        return {
            "category": "client_only", "confidence": "high",
            "reason": _KNOWN_CLIENT_ONLY_MOD_IDS[mod_id],
        }

    modloader = meta.get("modloader") or ""
    side = meta.get("side")

    if modloader == "Fabric":
        if side == "client":
            return {
                "category": "client_only", "confidence": "high",
                "reason": 'fabric.mod.json declara "environment": "client"',
            }
        if side in (None, "*", "server"):
            return {"category": "server", "confidence": None, "reason": None}
        return {
            "category": "unknown", "confidence": None,
            "reason": f'valor de "environment" no reconocido: {side!r}',
        }

    if modloader in ("NeoForge", "NeoForge/Forge"):
        if side:
            side_upper = side.upper()
            if side_upper == "CLIENT":
                return {
                    "category": "client_only", "confidence": "medium",
                    "reason": 'mods.toml declara side="CLIENT" para la dependencia del propio loader (convención no oficial)',
                }
            if side_upper in ("SERVER", "BOTH"):
                return {"category": "server", "confidence": None, "reason": None}
            return {
                "category": "unknown", "confidence": None,
                "reason": f'valor de "side" no reconocido: {side!r}',
            }
        return {"category": "server", "confidence": None, "reason": None}

    # Quilt u otros: sin señal fiable extraída todavía (ver comentario en
    # read_mod_metadata), se trata igual que "sin declaración".
    return {"category": "server", "confidence": None, "reason": None}


def classify_installed_mods(mods_dir: Path) -> dict:
    """
    Categoriza los mods instalados (incluidos los .disabled) en server /
    client_only / unknown según su metadata de side/environment. Los jars sin
    metadata reconocible (result["error"] set) se excluyen: no hay base para
    clasificarlos, y ya se reportan aparte en el flujo normal de instalación.
    """
    if not mods_dir.exists():
        return {"server": [], "client_only": [], "unknown": []}

    buckets: dict = {"server": [], "client_only": [], "unknown": []}
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        try:
            meta = read_mod_metadata(f.read_bytes())
        except Exception:
            continue
        if meta.get("error"):
            continue

        classification = classify_mod_side(meta)
        entry = {
            "filename": f.name,
            "display_name": mod_display_name(f.name),
            "mod_id": meta.get("mod_id"),
            "enabled": not f.name.endswith(".disabled"),
        }
        if classification["confidence"]:
            entry["confidence"] = classification["confidence"]
        if classification["reason"]:
            entry["reason"] = classification["reason"]
        buckets[classification["category"]].append(entry)

    return buckets


_PRERELEASE_MARKER_RE = re.compile(r'alpha|beta|rc|pre|snapshot|dev', re.IGNORECASE)


def compare_mod_versions(v1: str, v2: str) -> int:
    """
    Compara dos versiones de mod comparando sus segmentos numéricos. Devuelve
    -1 si v1 < v2, 1 si v1 > v2, 0 si son iguales.

    Antes de comparar, separa un posible marcador de pre-release (alpha/beta/
    rc/pre/snapshot/dev): a igual número base, una versión SIN ese marcador
    es más nueva que una CON él (p.ej. "6.0.0" es más nueva que
    "6.0.0-beta.83", aunque "83" sea numéricamente más grande que nada). Si
    ambas tienen o ambas no tienen marcador, se comparan todos los segmentos
    numéricos completos (incluido el del propio marcador) para no perder el
    orden dentro de esa franja (p.ej. beta.83 vs beta.90).
    """
    def parts(v):
        return [int(x) for x in re.findall(r'\d+', v or '')]

    def split_prerelease(v):
        v = v or ''
        m = _PRERELEASE_MARKER_RE.search(v)
        return (v[:m.start()], True) if m else (v, False)

    core1, pre1 = split_prerelease(v1)
    core2, pre2 = split_prerelease(v2)

    core_cmp = 0
    for a, b in zip_longest(parts(core1), parts(core2), fillvalue=0):
        if a != b:
            core_cmp = -1 if a < b else 1
            break
    if core_cmp != 0:
        return core_cmp
    if pre1 != pre2:
        return 1 if pre2 else -1

    for a, b in zip_longest(parts(v1), parts(v2), fillvalue=0):
        if a != b:
            return -1 if a < b else 1
    return 0


def build_mod_id_index(mods_dir: Path) -> dict:
    """
    Escanea mods_dir UNA sola vez y arma un índice mod_id -> (Path, meta).

    Sin esto, procesar un lote de N mods contra M ya instalados llamaba a
    find_installed_mod_by_id() N veces, y cada llamada volvía a leer y
    parsear los M jars instalados desde cero (O(N×M): con 300+ mods en ambos
    lados eso son decenas de miles de aperturas de zip). Con el índice armado
    una vez, cada búsqueda es O(1) y el costo total baja a O(N+M).
    """
    index = {}
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        try:
            meta = read_mod_metadata(f.read_bytes())
        except Exception:
            continue
        mod_id = meta.get("mod_id")
        if mod_id:
            index[mod_id] = (f, meta)
    return index


def find_installed_mod_by_id(mods_dir: Path, mod_id: str, index: dict | None = None):
    """
    Busca en mods_dir un jar ya instalado cuyo mod_id coincida con el dado.
    Devuelve (Path, meta dict) o (None, None) si no hay coincidencia.

    Si se pasa `index` (de build_mod_id_index), la búsqueda es O(1) y no
    vuelve a leer nada de disco; si no, escanea mods_dir como antes.
    """
    if not mod_id:
        return None, None
    if index is not None:
        return index.get(mod_id, (None, None))
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


def _fmt_ver(v: str | None) -> str:
    return f"v{v}" if v else "versión desconocida"


_DEDUP_CUT_RE = re.compile(
    r'[-_\s]+\d|\b(?:forge|fabric|neoforge|quilt|mc|minecraft)\b',
    re.IGNORECASE,
)


def _dedup_fingerprint(filename: str) -> str:
    """
    Huella agresiva para agrupar por parecido de nombre: todo lo que viene
    antes del primer número de versión o palabra de loader/MC, en minúsculas
    y sin separadores. A diferencia de mod_display_name (pensado para verse
    bien), acá el separador antes de la palabra de loader puede ser un
    espacio ("Custom Nether Portals - Neoforge - MC 1.21.1- 2.0.0" también
    calza con "custom_nether_portals-neoforge-1.21.1-1.0.0").
    """
    p = Path(filename)
    stem = p.stem if not p.name.endswith(".disabled") else p.stem.replace(".jar", "").replace(".zip", "")
    m = _DEDUP_CUT_RE.search(stem)
    core = stem[:m.start()] if m else stem
    return re.sub(r'[^a-z0-9]', '', core.lower())


def find_possible_duplicate_mods(mods_dir: Path) -> list:
    """
    Agrupa los mods instalados en posibles duplicados. No se puede confiar del
    todo en el mod_id (un mod puede cambiar el suyo entre versiones, como pasó
    con Custom Nether Portals 1.0.0 -> 2.0.0: "custom_nether_portals" pasó a
    ser "customnetherportals"), así que se buscan dos señales por separado:

    - "high": dos o más archivos con el MISMO mod_id (debería ser raro si
      todo se instaló por la app, pero puede pasar con archivos puestos a mano).
    - "medium": mismo nombre "normalizado" (sin espacios/guiones/mayúsculas)
      pero mod_id distinto — heurística por parecido de nombre, no 100%
      confiable, así que se marca con confianza menor.

    Devuelve una lista de grupos: [{"confidence", "reason", "mods": [...]}]
    """
    if not mods_dir.exists():
        return []

    entries = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        try:
            meta = read_mod_metadata(f.read_bytes())
        except Exception:
            continue
        entries.append({
            "filename": f.name,
            "mod_id": meta.get("mod_id"),
            "mod_version": meta.get("mod_version"),
            "display_name": mod_display_name(f.name),
            "fingerprint": _dedup_fingerprint(f.name),
        })

    groups = []
    seen_files = set()

    by_mod_id = defaultdict(list)
    for e in entries:
        if e["mod_id"]:
            by_mod_id[e["mod_id"]].append(e)
    for mod_id, group in by_mod_id.items():
        if len(group) > 1:
            groups.append({
                "confidence": "high",
                "reason": f'mismo mod_id ("{mod_id}")',
                "mods": [{"filename": g["filename"], "display_name": g["display_name"], "mod_version": g["mod_version"]} for g in group],
            })
            seen_files.update(g["filename"] for g in group)

    by_fingerprint = defaultdict(list)
    for e in entries:
        if e["filename"] in seen_files or len(e["fingerprint"]) < 4:
            continue
        by_fingerprint[e["fingerprint"]].append(e)
    for fingerprint, group in by_fingerprint.items():
        if len(group) > 1:
            groups.append({
                "confidence": "medium",
                "reason": "nombre muy parecido",
                "mods": [{"filename": g["filename"], "display_name": g["display_name"], "mod_version": g["mod_version"]} for g in group],
            })

    return groups


def process_mod_jar(mods_dir: Path, filename: str, jar_bytes: bytes, server_mc: str, mod_index: dict | None = None) -> dict:
    """
    Evalúa un .jar de mod contra los mods ya instalados en mods_dir y, si corresponde,
    lo instala. Usado tanto por la subida individual como por la subida masiva (zip/carpeta).

    Si status == "needs_confirmation" NO se escribe nada en disco: quien llama decide
    qué hacer con jar_bytes (p.ej. guardarlos a la espera de que el usuario confirme
    si quiere degradar la versión instalada).

    mod_index (de build_mod_id_index): si se pasa, se usa para no reescanear
    mods_dir en cada llamada, y se actualiza in-place cuando este mod queda
    instalado/reemplazado, para que el resto del lote lo vea sin volver a leer
    nada de disco.

    Devuelve dict con: status, filename, display_name, mod_id, mod_version, detail,
    y según el caso: reason, existing_filename, existing_version, replaced_filename, previous_version.
    status: "added" | "already_installed" | "needs_confirmation" | "incompatible" | "invalid"
    reason (solo con status == "needs_confirmation"): "downgrade" | "client_only"
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

    # Se comprueba ANTES que la compatibilidad de versión: un mod de cliente
    # (p.ej. Sodium) puede crashear el servidor al arrancar (usa LWJGL, que no
    # existe en un dedicado) sin dejar ni rastro en los logs — mejor avisar y
    # dejar decidir, que instalarlo en silencio y que el servidor deje de
    # arrancar sin explicación. classify_installed_mods() ya detectaba esto
    # DESPUÉS de instalado (panel "🖥️ Mods solo-cliente"); esto lo hace ANTES.
    classification = classify_mod_side(meta)
    if classification["category"] == "client_only":
        return {
            "status": "needs_confirmation", "reason": "client_only",
            "filename": filename, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "detail": "Este mod parece ser solo de cliente"
                      + (f" ({classification['reason']})" if classification["reason"] else "")
                      + " — normalmente no hace falta (y puede impedir que el servidor arranque).",
        }

    if server_mc and meta["mc_versions"] and not mc_version_compatible(server_mc, meta["mc_versions"]):
        return {
            "status": "incompatible", "filename": filename, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "detail": f"Incompatible: requiere MC {', '.join(meta['mc_versions'])} pero el servidor es {server_mc}",
        }

    existing_path, existing_meta = find_installed_mod_by_id(mods_dir, meta.get("mod_id"), mod_index)

    if existing_path:
        cmp = compare_mod_versions(meta.get("mod_version"), existing_meta.get("mod_version"))
        if cmp < 0:
            return {
                "status": "needs_confirmation", "reason": "downgrade",
                "filename": filename, "display_name": display_name,
                "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
                "existing_filename": existing_path.name, "existing_version": existing_meta.get("mod_version"),
                "detail": f"Versión más antigua ({_fmt_ver(meta.get('mod_version'))}) que la instalada "
                          f"({_fmt_ver(existing_meta.get('mod_version'))} en {existing_path.name})",
            }
        if cmp == 0:
            return {
                "status": "already_installed", "filename": filename, "display_name": display_name,
                "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
                "existing_filename": existing_path.name,
                "detail": f"Ya está instalado ({_fmt_ver(meta.get('mod_version'))})",
            }
        was_disabled = existing_path.name.endswith(".disabled")
        replaced_filename = existing_path.name
        previous_version = existing_meta.get("mod_version")
        existing_path.unlink()
        dest = mods_dir / (filename + ".disabled" if was_disabled else filename)
        dest.write_bytes(jar_bytes)
        if mod_index is not None and meta.get("mod_id"):
            mod_index[meta["mod_id"]] = (dest, meta)
        return {
            "status": "added", "filename": dest.name, "display_name": display_name,
            "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
            "replaced_filename": replaced_filename, "previous_version": previous_version,
            "detail": f"Actualizado desde {_fmt_ver(previous_version)}",
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
    if mod_index is not None and meta.get("mod_id"):
        mod_index[meta["mod_id"]] = (dest, meta)
    return {
        "status": "added", "filename": filename, "display_name": display_name,
        "mod_id": meta.get("mod_id"), "mod_version": meta.get("mod_version"),
        "detail": None,
    }


def mc_version_compatible(server_mc: str, mod_versions: list, bare_as_minimum: bool = False) -> bool:
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

    bare_as_minimum: una versión "pelada" sin rango (p.ej. "21.1.228") se
    interpreta por defecto como prefijo/wildcard (equivale a "21.1.228.x"),
    que tiene sentido para versiones de Minecraft ("1.21" ~ "1.21.x"). Para
    versiones de LOADER (neoforge/forge/...) esa misma forma casi siempre
    significa "mínimo requerido", así que el chequeo de compatibilidad de
    modloader pasa bare_as_minimum=True para tratarla como ">=" en vez de
    exigir que el prefijo calce literalmente.
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
        # Versión "pelada" sin rango, p.ej. "1.21"
        if re.match(r'^\d+(\.\d+)*$', vrange):
            recognized_any = True
            if bare_as_minimum:
                if ver_tuple(server_mc) >= ver_tuple(vrange):
                    return True
            elif server_mc == vrange or server_mc.startswith(vrange + '.'):
                return True
            continue
        if re.match(r'^[\d.]+[.*x]$', vrange):
            recognized_any = True
            prefix = re.sub(r'[.*x]+$', '', vrange).rstrip('.')
            if server_mc.startswith(prefix):
                return True
            continue
        # Rango Maven de valor único: [1.21.1] significa exactamente 1.21.1 en
        # la especificación formal — pero igual que con el resto de esta
        # función, se trata como prefijo (no exacto): un mod que declara
        # "[1.21]" en la práctica también funciona en parches menores como
        # 1.21.1 (NeoForge no aplica este campo de forma estricta), así que
        # exigir coincidencia exacta bloqueaba instalaciones válidas.
        m_exact = re.match(r'^\[([\d.]+)\]$', vrange)
        if m_exact:
            recognized_any = True
            declared = m_exact.group(1)
            if server_mc == declared or server_mc.startswith(declared + '.'):
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


# ── Mods pendientes de instalar manualmente ─────────────────────────────────────
# Cuando el autor de un modpack de CurseForge bloquea la descarga por terceros
# para un mod concreto, la API no da ninguna URL con la que resolverlo (ver
# skipped_no_url en services/modpack_install.py) — el resto del modpack se
# instala igual, pero ese mod se queda fuera. Estos nombres se guardan acá para
# que server_start() (routes/server.py) se niegue a arrancar ese modpack
# mientras sigan sin estar de verdad en mods/, en vez de dejar arrancar un
# servidor a medias sin que nadie se dé cuenta hasta que un jugador lo note.
#
# Dos formas de comprobar, para dos situaciones distintas:
# - get_pending_mods() es una simple lectura de JSON (sin abrir ningún jar) —
#   la usan el listado de modpacks y (como primer chequeo) el arranque del
#   servidor, así que tiene que ser instantánea.
# - check_pending_mods_stream() SÍ abre cada mod instalado para comparar su
#   mod_id/versión real, así que puede tardar unos segundos en modpacks
#   grandes — solo se dispara desde el frontend justo antes de arrancar el
#   servidor, y SOLO si get_pending_mods() ya dijo que queda algo pendiente
#   (si no hay nada pendiente, no tiene sentido pagar ese costo). Cubre el
#   caso de un mod copiado a mano por SFTP en vez de subido desde el panel
#   (resolve_pending_mods(), más abajo, solo se entera de las subidas que
#   pasan por la propia app).

PENDING_MODS_FILENAME = "mods-pendientes.json"


def write_pending_mods(modpack: str, filenames: list) -> None:
    """Se llama una sola vez, justo tras instalar el modpack (ver install_curseforge_modpack_stream)."""
    path = DEFAULT_SERVERS_PATH / modpack / PENDING_MODS_FILENAME
    names = sorted({n.strip() for n in filenames if n and n.strip()})
    if not names:
        return
    path.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")


def get_pending_mods(modpack: str) -> list:
    """Lectura simple: si mods-pendientes.json no está vacío, faltan mods por instalar a mano."""
    path = DEFAULT_SERVERS_PATH / modpack / PENDING_MODS_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_pending_mods_list(modpack: str, still_pending: list, previous: list) -> None:
    if still_pending == previous:
        return
    path = DEFAULT_SERVERS_PATH / modpack / PENDING_MODS_FILENAME
    if still_pending:
        path.write_text(json.dumps(still_pending, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


_VERSION_TOKEN_RE = re.compile(r'\d+(?:\.\d+){1,3}')


def _extract_filename_version(filename: str) -> str | None:
    """
    Mejor esfuerzo para sacar "la versión" de un nombre de archivo cuando es lo
    único que hay: un mod pendiente nunca se llegó a descargar, así que no hay
    metadata real que leer, solo el nombre que traía en CurseForge. Se asume la
    convención más común — versión de mod al final, justo antes de la
    extensión (ej. "bwncr-neoforge-1.21.1-3.20.4.jar" -> "3.20.4") — que no
    siempre acierta (hay packs que no siguen ese orden), por eso
    _pending_entry_resolved_by() solo la usa como desempate cuando SÍ hay una
    versión real del lado instalado con la que comparar.
    """
    stem = filename
    for suffix in (".disabled", ".jar", ".zip"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    matches = _VERSION_TOKEN_RE.findall(stem)
    return matches[-1] if matches else None


def _pending_entry_resolved_by(name: str, candidate_fp: str, candidate_modid_fp: str, candidate_version: str | None) -> bool:
    """
    True si un mod instalado (candidate_fp/candidate_modid_fp/candidate_version,
    ver resolve_pending_mods y check_pending_mods_stream) resuelve el pendiente
    `name`: calza por nombre "core" (mismo _dedup_fingerprint, ignora
    versión/loader/MC — el mismo criterio que ya usa
    find_possible_duplicate_mods()) O por mod_id real — así se reconoce aunque
    se haya bajado con otro nombre de archivo (build nueva, bajado de
    Modrinth en vez de CurseForge...) — Y su versión es igual o superior a la
    que se puede extraer del nombre pendiente, o directamente si no hay
    versión que comparar de ningún lado.
    """
    target_fp = _dedup_fingerprint(name)
    if not target_fp or not (target_fp == candidate_fp or (candidate_modid_fp and target_fp == candidate_modid_fp)):
        return False
    target_version = _extract_filename_version(name)
    if target_version and candidate_version and compare_mod_versions(candidate_version, target_version) < 0:
        return False  # mismo mod, pero la versión instalada es más vieja que la pedida
    return True


def resolve_pending_mods(modpack: str, filename: str, mod_id: str | None, mod_version: str | None) -> list:
    """
    Se llama justo después de instalar un mod (subida individual, en lote, o
    al confirmar un lote — ver routes/modpacks.py) con su metadata YA leída
    por ese mismo flujo (process_mod_jar), sin abrir el jar de nuevo acá.
    Devuelve la lista de pendientes que queda tras esto.
    """
    path = DEFAULT_SERVERS_PATH / modpack / PENDING_MODS_FILENAME
    if not path.exists():
        return []
    try:
        names = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(names, list) or not names:
        path.unlink(missing_ok=True)
        return []

    candidate_fp = _dedup_fingerprint(filename)
    candidate_modid_fp = re.sub(r'[^a-z0-9]', '', (mod_id or "").lower())
    still_pending = [n for n in names if not _pending_entry_resolved_by(n, candidate_fp, candidate_modid_fp, mod_version)]
    _write_pending_mods_list(modpack, still_pending, names)
    return still_pending


def _scan_installed_mod_candidates(mods_dir: Path):
    """
    Generador: por cada archivo en mods/, yield (filename, candidate). Abre
    cada .jar para leer su mod_id y versión REALES (mods.toml/fabric.mod.json
    vía read_mod_metadata) en vez de fiarse solo del nombre de archivo.
    candidate es None para archivos que no son .jar (p.ej. un .zip suelto),
    que no se pueden abrir para leer metadata.
    """
    if not mods_dir.exists():
        return
    files = sorted((f for f in mods_dir.iterdir() if f.is_file()), key=lambda f: f.name.lower())
    for f in files:
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            yield f.name, None
            continue
        real_name = f.name[: -len(".disabled")] if f.name.endswith(".disabled") else f.name
        try:
            meta = read_mod_metadata(f.read_bytes())
        except Exception:
            meta = {}
        yield f.name, {
            "filename_fp": _dedup_fingerprint(real_name),
            "modid_fp": re.sub(r'[^a-z0-9]', '', (meta.get("mod_id") or "").lower()),
            "mod_version": meta.get("mod_version"),
        }


def check_pending_mods_stream(modpack: str):
    """
    Re-chequeo completo con progreso: abre cada mod instalado para comparar
    con lo pendiente, por si algo se resolvió por una vía que resolve_pending_mods()
    no ve (copiado a mano por SFTP en vez de subido desde el panel). Solo
    tiene sentido llamarlo cuando get_pending_mods() ya dijo que queda algo
    pendiente — el frontend (botón "Iniciar servidor") se encarga de ese
    chequeo rápido antes de disparar este, para no pagar el costo de abrir
    jars cuando no hace falta.
    """
    names = get_pending_mods(modpack)
    if not names:
        yield {"type": "done", "pending_mods": []}
        return

    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    total = sum(1 for f in mods_dir.iterdir() if f.is_file()) if mods_dir.exists() else 0
    still_pending = list(names)
    for i, (filename, candidate) in enumerate(_scan_installed_mod_candidates(mods_dir), start=1):
        if candidate:
            still_pending = [
                n for n in still_pending
                if not _pending_entry_resolved_by(n, candidate["filename_fp"], candidate["modid_fp"], candidate["mod_version"])
            ]
        yield {"type": "progress", "index": i, "total": total, "filename": filename}

    _write_pending_mods_list(modpack, still_pending, names)
    yield {"type": "done", "pending_mods": still_pending}


# ── Análisis de crash reports ──────────────────────────────────────────────────

# Marcan el final de la parte "útil" de un crash report de Forge/NeoForge (el
# resumen de la excepción + su stack trace) y el principio de las secciones
# de contexto (mod list completa, detalles de sistema, hilos...) — formato
# estable desde hace años en ambos loaders. Se usa el que aparezca primero.
_CRASH_REGION_END_RE = re.compile(
    r'^(--------+|-- (Head|Affected level|System Details) --|A detailed walkthrough)',
    re.MULTILINE,
)
_CRASH_DESCRIPTION_RE = re.compile(r'^Description:\s*(.*)$', re.MULTILINE)
_CRASH_EXCEPTION_LINE_RE = re.compile(r'^\s*(?:Caused by:\s*)?[\w.$]+(?:Exception|Error)\b.*$', re.MULTILINE)
_CRASH_CAUSED_BY_RE = re.compile(r'^\s*Caused by:.*$', re.MULTILINE)


def _crash_stack_region(text: str) -> str:
    """
    Aísla el resumen de excepción + stack trace real de un crash report,
    cortando antes de las secciones de contexto (Mod List, System Details...).
    Sin esto, buscar el nombre de un mod "en cualquier parte del archivo" da
    falsos positivos constantes: CUALQUIER mod instalado aparece en la Mod
    List de todo crash report, esté relacionado o no con lo que falló.
    """
    desc_match = _CRASH_DESCRIPTION_RE.search(text)
    start = desc_match.end() if desc_match else 0
    end_match = _CRASH_REGION_END_RE.search(text, pos=start)
    end = end_match.start() if end_match else len(text)
    region = text[start:end]
    # Fallback defensivo: un crash que no sea de Forge/NeoForge (o un texto
    # cualquiera pegado en logs/) puede no tener ninguno de estos marcadores;
    # mejor analizar el texto completo que quedarse con una región vacía.
    return region if region.strip() else text


def analyze_crash(text: str, modpack: str) -> dict:
    """
    Intenta identificar qué mod causó el crash, buscando solo dentro de la
    región de stack trace real (ver _crash_stack_region), no en el archivo
    entero. Devuelve {"exception_summary", "caused_by_chain", "culprit_mods"}.
    """
    region = _crash_stack_region(text)

    exception_summary = None
    exc_match = _CRASH_EXCEPTION_LINE_RE.search(region)
    if exc_match:
        exception_summary = exc_match.group(0).strip()
    else:
        desc_match = _CRASH_DESCRIPTION_RE.search(text)
        if desc_match and desc_match.group(1).strip():
            exception_summary = desc_match.group(1).strip()

    caused_by_chain = []
    for line in _CRASH_CAUSED_BY_RE.findall(region):
        stripped = line.strip()
        if stripped not in caused_by_chain:
            caused_by_chain.append(stripped)

    culprit_mods = []
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if mods_dir.exists():
        # _dedup_fingerprint() (ya usada para detectar mods duplicados) corta
        # también en palabras de loader ("-neoforge", "-fabric"...), no solo
        # en el primer número — sin eso, "sodium-neoforge-0.8.12+mc1.21.1.jar"
        # se reducía a "sodium-neoforge", que nunca aparece tal cual en un
        # stack trace real (los paquetes Java van con puntos, no guiones; ahí
        # sí aparece "sodium" solo, ej. "me.jellysquid.mods.sodium.client...").
        # Se descartan fingerprints muy cortos (<4) por la misma razón que ya
        # aplica find_possible_duplicate_mods(): con pocas letras, el riesgo
        # de que calcen por casualidad en cualquier parte del trace es alto.
        region_lower = region.lower()
        ranked = []
        for f in mods_dir.iterdir():
            if not (f.is_file() and f.suffix == ".jar"):
                continue
            fp = _dedup_fingerprint(f.name)
            if len(fp) < 4:
                continue
            pos = region_lower.find(fp)
            if pos != -1:
                ranked.append((pos, f.name))
        ranked.sort()
        culprit_mods = [name for _pos, name in ranked[:5]]

    return {
        "exception_summary": exception_summary,
        "caused_by_chain": caused_by_chain,
        "culprit_mods": culprit_mods,
    }
