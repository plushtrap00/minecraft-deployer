"""
services/mod_checks.py - Comprobaciones sobre los mods de un servidor:
- si un mod es solo de cliente (y en un servidor dedicado sobra o lo rompe),
- posibles duplicados (dos versiones del mismo mod),
- process_mod_jar: lo que se hace con cada .jar que se sube o descarga
  (metadatos, compatibilidad, si sustituye a uno ya instalado...).
"""
import re
from collections import defaultdict
from pathlib import Path

from services.mod_metadata import _NO_METADATA_ERROR, _fmt_ver, compare_mod_versions, find_installed_mod_by_id, mc_version_compatible, mod_display_name, read_mod_metadata

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


_DEDUP_CUT_RE = re.compile(
    r'[-_\s]+\d|\b(?:forge|fabric|neoforge|quilt|mc|minecraft)\b',
    re.IGNORECASE,
)


def _dedup_fingerprint(filename: str) -> str:
    """
    Huella agresiva para agrupar por parecido de nombre: todo lo que viene
    antes del primer número de versión o palabra de loader/MC, en minúsculas
    y sin separadores. A diferencia de mod_display_name (pensado para verse
    bien), aquí el separador antes de la palabra de loader puede ser un
    espacio ("Custom Nether Portals - Neoforge - MC 1.21.1- 2.0.0" también
    calza con "custom_nether_portals-neoforge-1.21.1-1.0.0").
    """
    p = Path(filename)
    stem = p.stem if not p.name.endswith(".disabled") else p.stem.replace(".jar", "").replace(".zip", "")
    m = _DEDUP_CUT_RE.search(stem)
    core = stem[:m.start()] if m else stem
    return re.sub(r'[^a-z0-9]', '', core.lower())


# _KNOWN_CLIENT_ONLY_MOD_IDS está clavado por mod_id real (tal cual lo declara
# cada mod, p.ej. "euphoria_patcher" con guion bajo) — para comparar contra
# nombres de archivo (que es todo lo que hay antes de descargar un mod, o lo
# único que queda guardado en mods-pendientes.json) hace falta normalizar
# ambos lados con el mismo criterio, o un caso como "euphoria_patcher"
# (fingerprint "euphoriapatcher", sin guion bajo) nunca calzaría. Se define
# aquí abajo, no junto al dict de arriba, porque necesita _dedup_fingerprint()
# ya declarada.
_KNOWN_CLIENT_ONLY_FINGERPRINTS = {
    _dedup_fingerprint(mod_id): reason for mod_id, reason in _KNOWN_CLIENT_ONLY_MOD_IDS.items()
}


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
