"""
services/pack_install_duplicates.py - Antes de instalar un modpack, avisa si
ya hay un servidor instalado con casi los mismos mods.
"""
from config import DEFAULT_SERVERS_PATH
from app_constants import MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT
from services.mod_checks import _dedup_fingerprint
from services.modpack import detect_modpack_version
from services.utils import get_modpacks


def _installed_mod_fingerprints(server_name: str) -> set:
    """
    Huellas "sin versión" (ver _dedup_fingerprint) de los mods ya instalados en
    un servidor, incluidos los .disabled — que un mod esté deshabilitado no
    significa que el modpack no sea ese, así que cuenta de todas formas para esta
    comparación.
    """
    mods_dir = DEFAULT_SERVERS_PATH / server_name / "mods"
    if not mods_dir.exists():
        return set()
    fingerprints = set()
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        low = f.name.lower()
        if low.endswith(".jar") or low.endswith(".zip") or low.endswith(".jar.disabled") or low.endswith(".zip.disabled"):
            fingerprints.add(_dedup_fingerprint(f.name))
    return fingerprints


def find_similar_installed_modpacks(filenames: list, mc_version: str | None) -> list:
    """
    Compara los nombres de archivo de una versión de modpack candidata a
    instalar contra los mods ya instalados en cada servidor existente, usando
    la misma huella "sin versión/loader/MC" que ya usa
    find_possible_duplicate_mods() (services/mod_checks.py) para detectar
    duplicados dentro de un mismo modpack. Así, actualizar un mod (que cambia
    el número de versión en el nombre del jar) o añadir mods sueltos a mano no
    rompe la detección: solo importa si el "núcleo" del nombre original sigue
    presente.

    El % se calcula sobre el TOTAL de archivos del modpack candidato, no sobre
    lo instalado en el servidor: añadir mods extra a un servidor no baja el
    porcentaje, solo quitar o reemplazar los que vinieron originalmente con
    el pack sí lo hace.

    No requiere descargar ningún mod: filenames viene de
    get_modrinth_modpack_mods()/get_curseforge_modpack_mods(), que solo leen
    el índice/manifest del pack, y lo instalado se compara por nombre de
    archivo en disco.
    """
    pack_fingerprints = {
        fp for fp in (_dedup_fingerprint(name) for name in filenames if name)
        if len(fp) >= 4
    }
    if not pack_fingerprints:
        return []

    matches = []
    for server_name in get_modpacks():
        if mc_version:
            server_mc = detect_modpack_version(server_name).get("mc_version")
            if server_mc and server_mc != mc_version:
                continue
        installed_fingerprints = _installed_mod_fingerprints(server_name)
        if not installed_fingerprints:
            continue
        matched = pack_fingerprints & installed_fingerprints
        if not matched:
            continue
        overlap_pct = round(len(matched) * 100 / len(pack_fingerprints))
        if overlap_pct >= MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT:
            matches.append({
                "server_name": server_name, "overlap_pct": overlap_pct,
                "matched_count": len(matched), "total_count": len(pack_fingerprints),
            })

    matches.sort(key=lambda m: m["overlap_pct"], reverse=True)
    return matches
