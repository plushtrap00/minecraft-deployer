"""
services/pending_mods.py - Mods que un modpack necesita pero que hay que
instalar a mano (CurseForge no deja descargar algunos): la lista que se guarda
al instalar, cómo se va resolviendo al subir cada .jar y la comprobación
completa por SSE.
"""
import re
import json
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.mod_checks import _KNOWN_CLIENT_ONLY_FINGERPRINTS, _dedup_fingerprint
from services.mod_metadata import compare_mod_versions, read_mod_metadata

# ── Mods pendientes de instalar manualmente ─────────────────────────────────────
# Cuando el autor de un modpack de CurseForge bloquea la descarga por terceros
# para un mod concreto, la API no da ninguna URL con la que resolverlo (ver
# skipped_no_url en services/modpack_install.py) — el resto del modpack se
# instala igual, pero ese mod se queda fuera. Estos nombres se guardan aquí para
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
    """
    Lectura simple: si mods-pendientes.json no está vacío, faltan mods por
    instalar a mano. De paso descarta (autolimpieza barata, sin abrir ningún
    jar) cualquier entrada que calce con _KNOWN_CLIENT_ONLY_FINGERPRINTS —
    esto pasa cuando el propio mod bloqueado para terceros ES uno de esos
    conocidos (services/modpack_install.py ya evita que ENTREN nuevos así,
    pero un mods-pendientes.json de antes de ese chequeo puede seguir
    teniendo uno): no tiene sentido pedir instalar a mano algo que ya se sabe
    que no hace falta en el servidor.
    """
    path = DEFAULT_SERVERS_PATH / modpack / PENDING_MODS_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    still_pending = [name for name in data if not _KNOWN_CLIENT_ONLY_FINGERPRINTS.get(_dedup_fingerprint(name))]
    _write_pending_mods_list(modpack, still_pending, data)
    return still_pending


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
    por ese mismo flujo (process_mod_jar), sin abrir el jar de nuevo aquí.
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
