"""
user_prefs.py - Preferencias de cada cuenta (por ahora, el idioma del panel).

Se guardan en SERVERS_PATH/.global/user_prefs.json, junto a automation.json,
para que sobrevivan a una reinstalación de la app o a reconstruir el
contenedor (en Docker esa carpeta es un volumen). Las del administrador van
aquí también: su cuenta vive en el .env, no en users.json.
"""
import json
import threading

from config import DEFAULT_SERVERS_PATH

PREFS_FILE = DEFAULT_SERVERS_PATH / ".global" / "user_prefs.json"
_lock = threading.Lock()


def _load() -> dict:
    try:
        data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PREFS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PREFS_FILE)


def get_lang(username: str) -> str | None:
    """Idioma elegido por esa cuenta, o None si todavía no ha elegido."""
    with _lock:
        value = (_load().get(username) or {}).get("lang")
    return value if isinstance(value, str) else None


def set_lang(username: str, lang: str) -> None:
    with _lock:
        data = _load()
        current = data.get(username)
        entry: dict = current if isinstance(current, dict) else {}
        entry["lang"] = lang
        data[username] = entry
        _write(data)


def forget(username: str) -> None:
    """Borra las preferencias de una cuenta eliminada."""
    with _lock:
        data = _load()
        if data.pop(username, None) is not None:
            _write(data)
