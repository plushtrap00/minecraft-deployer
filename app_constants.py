"""
app_constants.py - Constantes de comportamiento ajustables de la app.

Igual que config.py, este módulo lee un archivo local en gitignore:
.APP_CONSTANTS (JSON) en la raíz del repo. A diferencia de .env, no tiene
nada sensible (son solo números de ajuste: timeouts, límites, tamaños de
caché) — pero SÍ se modifica en cada instalación desde el panel de
administración (routes/config_admin.py), así que no puede versionarse en
git: si estuviera trackeado, un `git pull` fallaría en cuanto el usuario
guardara un cambio desde el panel y luego el repo remoto tocara ese mismo
archivo (pasó de verdad: ver commit que lo sacó de git). DEFAULTS de abajo
es la única fuente de verdad de qué claves existen y sus valores de
fábrica; el archivo se autogenera con esos valores la primera vez que se
importa este módulo si no existe todavía (install.sh también se asegura de
generarlo explícitamente).

Editable desde el panel de administración. Como el resto de módulos leen
estos valores una sola vez al importarse, un cambio guardado desde ahí no
toma efecto hasta reiniciar la app.
"""
import json
from pathlib import Path

_CONSTANTS_PATH = Path(__file__).parent / ".APP_CONSTANTS"

# Valores por defecto y única fuente de verdad de qué claves existen: save()
# rechaza cualquier clave que no esté acá, y _load() ignora las que sobren en
# el archivo (por si quedó una clave vieja de una versión anterior).
DEFAULTS = {
    "MAX_LOG_LINES": 500,
    "LOG_CRASH_RETENTION_COUNT": 5,
    "GRACEFUL_STOP_TIMEOUT_SECONDS": 30,
    "AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS": 30,
    "AUTO_UPDATE_GIT_TIMEOUT_SECONDS": 30,
    "HTTP_TIMEOUT_SECONDS": 15,
    "MOD_DOWNLOAD_TIMEOUT_SECONDS": 60,
    "MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS": 3600,
    "CURSEFORGE_FILES_PAGE_SIZE": 50,
    "CURSEFORGE_FILES_MAX": 300,
    "CURSEFORGE_BULK_FILES_CHUNK": 50,
    "JWT_TOKEN_EXPIRE_HOURS": 168,
    "LOGIN_MAX_FAILED_ATTEMPTS": 5,
    "LOGIN_ATTEMPT_WINDOW_SECONDS": 300,
    "LOGIN_LOCKOUT_SECONDS": 300,
    "MOD_SEARCH_PAGE_SIZE": 20,
    "TEMP_DIR_MAX_AGE_SECONDS": 7200,
    "MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT": 40,
}

# Agrupación de cada constante para el formulario del panel de administración
# (que las separa en secciones plegables en vez de una lista larga única).
CATEGORIES = {
    "MAX_LOG_LINES": "Logs",
    "LOG_CRASH_RETENTION_COUNT": "Logs",
    "GRACEFUL_STOP_TIMEOUT_SECONDS": "Servidor de Minecraft",
    "AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS": "Auto-actualización",
    "AUTO_UPDATE_GIT_TIMEOUT_SECONDS": "Auto-actualización",
    "HTTP_TIMEOUT_SECONDS": "Mods y modpacks",
    "MOD_DOWNLOAD_TIMEOUT_SECONDS": "Mods y modpacks",
    "MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS": "Mods y modpacks",
    "CURSEFORGE_FILES_PAGE_SIZE": "Mods y modpacks",
    "CURSEFORGE_FILES_MAX": "Mods y modpacks",
    "CURSEFORGE_BULK_FILES_CHUNK": "Mods y modpacks",
    "MOD_SEARCH_PAGE_SIZE": "Mods y modpacks",
    "MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT": "Mods y modpacks",
    "JWT_TOKEN_EXPIRE_HOURS": "Sesión y login",
    "LOGIN_MAX_FAILED_ATTEMPTS": "Sesión y login",
    "LOGIN_ATTEMPT_WINDOW_SECONDS": "Sesión y login",
    "LOGIN_LOCKOUT_SECONDS": "Sesión y login",
    "TEMP_DIR_MAX_AGE_SECONDS": "Otros",
}

# Texto explicativo para el formulario del panel de administración.
DESCRIPTIONS = {
    "MAX_LOG_LINES": "Líneas de consola que se guardan en memoria para el visor de logs en vivo.",
    "LOG_CRASH_RETENTION_COUNT": "Cuántos logs rotados y crash reports se conservan por modpack antes de borrar los más viejos.",
    "GRACEFUL_STOP_TIMEOUT_SECONDS": "Segundos que se espera un apagado limpio (save-all + stop) antes de forzar el cierre del servidor.",
    "AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS": "Segundos de espera tras arrancar antes del primer chequeo de auto-actualización.",
    "AUTO_UPDATE_GIT_TIMEOUT_SECONDS": "Segundos máximos para cada operación de git (fetch/pull) de la auto-actualización.",
    "HTTP_TIMEOUT_SECONDS": "Segundos de espera para las peticiones a las APIs de Modrinth/CurseForge/Mojang.",
    "MOD_DOWNLOAD_TIMEOUT_SECONDS": "Segundos de espera al descargar el archivo de un mod o modpack.",
    "MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS": "Cuánto tiempo se cachean las categorías de Modrinth/CurseForge antes de refrescarlas.",
    "CURSEFORGE_FILES_PAGE_SIZE": "Tamaño de página al pedir archivos de un mod a la API de CurseForge.",
    "CURSEFORGE_FILES_MAX": "Tope máximo de archivos a traer por mod desde CurseForge.",
    "CURSEFORGE_BULK_FILES_CHUNK": "Cuántos archivos se resuelven a la vez en una sola llamada a la API de CurseForge al instalar un modpack.",
    "JWT_TOKEN_EXPIRE_HOURS": "Horas de validez de la sesión antes de tener que volver a iniciar sesión.",
    "LOGIN_MAX_FAILED_ATTEMPTS": "Intentos fallidos de inicio de sesión permitidos antes de bloquear temporalmente.",
    "LOGIN_ATTEMPT_WINDOW_SECONDS": "Ventana de tiempo en la que se cuentan los intentos fallidos de inicio de sesión.",
    "LOGIN_LOCKOUT_SECONDS": "Segundos que queda bloqueada una cuenta tras superar el máximo de intentos fallidos.",
    "MOD_SEARCH_PAGE_SIZE": "Resultados por página al buscar mods online.",
    "TEMP_DIR_MAX_AGE_SECONDS": "Antigüedad máxima de archivos temporales (subidas en curso) antes de limpiarlos.",
    "MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT": "Porcentaje mínimo de mods coincidentes con un servidor ya existente para avisar de una posible instalación duplicada al descargar un modpack.",
}


def _load() -> dict:
    if not _CONSTANTS_PATH.exists():
        _CONSTANTS_PATH.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return dict(DEFAULTS)
    try:
        data = json.loads(_CONSTANTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    for key, value in data.items():
        if key in DEFAULTS:
            merged[key] = value
    return merged


_values = _load()

MAX_LOG_LINES = _values["MAX_LOG_LINES"]
LOG_CRASH_RETENTION_COUNT = _values["LOG_CRASH_RETENTION_COUNT"]
GRACEFUL_STOP_TIMEOUT_SECONDS = _values["GRACEFUL_STOP_TIMEOUT_SECONDS"]
AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS = _values["AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS"]
AUTO_UPDATE_GIT_TIMEOUT_SECONDS = _values["AUTO_UPDATE_GIT_TIMEOUT_SECONDS"]
HTTP_TIMEOUT_SECONDS = _values["HTTP_TIMEOUT_SECONDS"]
MOD_DOWNLOAD_TIMEOUT_SECONDS = _values["MOD_DOWNLOAD_TIMEOUT_SECONDS"]
MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS = _values["MOD_SEARCH_CATEGORIES_CACHE_TTL_SECONDS"]
CURSEFORGE_FILES_PAGE_SIZE = _values["CURSEFORGE_FILES_PAGE_SIZE"]
CURSEFORGE_FILES_MAX = _values["CURSEFORGE_FILES_MAX"]
CURSEFORGE_BULK_FILES_CHUNK = _values["CURSEFORGE_BULK_FILES_CHUNK"]
JWT_TOKEN_EXPIRE_HOURS = _values["JWT_TOKEN_EXPIRE_HOURS"]
LOGIN_MAX_FAILED_ATTEMPTS = _values["LOGIN_MAX_FAILED_ATTEMPTS"]
LOGIN_ATTEMPT_WINDOW_SECONDS = _values["LOGIN_ATTEMPT_WINDOW_SECONDS"]
LOGIN_LOCKOUT_SECONDS = _values["LOGIN_LOCKOUT_SECONDS"]
MOD_SEARCH_PAGE_SIZE = _values["MOD_SEARCH_PAGE_SIZE"]
TEMP_DIR_MAX_AGE_SECONDS = _values["TEMP_DIR_MAX_AGE_SECONDS"]
MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT = _values["MODPACK_DUPLICATE_MATCH_THRESHOLD_PERCENT"]


def get_all() -> dict:
    """
    Para el panel de administración: valor guardado en disco + descripción de
    cada constante. Relee el archivo en cada llamada (a diferencia de las
    variables de módulo de arriba, que se cargan una sola vez al importar):
    así, justo después de guardar cambios, el panel los refleja de inmediato
    aunque el proceso en marcha siga usando los valores viejos hasta reiniciar.
    """
    current = _load()
    return {
        key: {
            "value": current.get(key, DEFAULTS[key]),
            "description": DESCRIPTIONS.get(key, ""),
            "category": CATEGORIES.get(key, "Otros"),
        }
        for key in DEFAULTS
    }


def save(new_values: dict) -> bool:
    """
    Valida que sean todas números enteros y escribe .APP_CONSTANTS. No aplica
    en caliente: como el resto de módulos leen estos valores una sola vez al
    importarse, hace falta reiniciar la app para que tomen efecto.

    Devuelve si algo cambió de verdad respecto a lo que ya había en disco —
    el panel de administración lo usa para no ofrecer un reinicio cuando el
    usuario guarda sin haber tocado ningún valor. Parte de _load() (no de
    _values, la copia cacheada al importar el módulo) para comparar contra el
    estado real en disco, no contra uno que puede llevar rato desactualizado.
    """
    merged = _load()
    changed = False
    for key, raw in new_values.items():
        if key not in DEFAULTS:
            continue
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'"{key}" debe ser un número entero')
        if merged.get(key) != parsed:
            changed = True
        merged[key] = parsed
    if changed:
        _CONSTANTS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed
