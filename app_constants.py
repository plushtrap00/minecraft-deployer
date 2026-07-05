"""
app_constants.py - Constantes de comportamiento ajustables de la app.

A diferencia de config.py (que también lee .env: secretos + configuración
específica de cada instalación, en gitignore), este módulo lee .APP_CONSTANTS
(JSON) en la raíz del repo. Ese archivo SÍ se versiona en git: son solo
números de ajuste (timeouts, límites, tamaños de caché) compartidos por
todas las instalaciones, sin nada sensible — por eso es seguro commitearlo.

Editable desde el panel de administración (routes/config_admin.py). Como el
resto de módulos leen estos valores una sola vez al importarse, un cambio
guardado desde ahí no toma efecto hasta reiniciar la app.
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
        key: {"value": current.get(key, DEFAULTS[key]), "description": DESCRIPTIONS.get(key, "")}
        for key in DEFAULTS
    }


def save(new_values: dict) -> None:
    """
    Valida que sean todas números enteros y escribe .APP_CONSTANTS. No aplica
    en caliente: como el resto de módulos leen estos valores una sola vez al
    importarse, hace falta reiniciar la app para que tomen efecto.
    """
    merged = dict(_values)
    for key, raw in new_values.items():
        if key not in DEFAULTS:
            continue
        try:
            merged[key] = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'"{key}" debe ser un número entero')
    _CONSTANTS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
