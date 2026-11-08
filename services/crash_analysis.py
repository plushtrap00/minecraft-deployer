"""
services/crash_analysis.py - Leer un crash report de Minecraft: la
descripción, la excepción, la cadena de «Caused by» y qué mods aparecen en
la traza, para señalar al culpable más probable.
"""
import re

from config import DEFAULT_SERVERS_PATH
from services.mod_checks import _dedup_fingerprint

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
