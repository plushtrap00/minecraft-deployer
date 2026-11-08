"""
services/mod_metadata.py - Leer lo que dice un .jar de mod de sí mismo
(mods.toml / neoforge.mods.toml / fabric.mod.json / quilt.mod.json / el
MANIFEST) y comparar versiones: de mods entre sí y de Minecraft contra lo que
el mod declara que soporta. También el índice mod_id → archivo de una
carpeta mods/ y el nombre legible de un archivo de mod.
"""
import re
import json
import zipfile
import io
from itertools import zip_longest
from pathlib import Path


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
