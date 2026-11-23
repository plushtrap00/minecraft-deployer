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


_cache: tuple = (None, None, {})


def _load() -> dict:
    """Se lee en cada petición a /api/ (para el idioma): con caché por mtime."""
    global _cache
    try:
        mtime = PREFS_FILE.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache[0] == PREFS_FILE and _cache[1] == mtime:
        return dict(_cache[2])
    try:
        data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    data = data if isinstance(data, dict) else {}
    _cache = (PREFS_FILE, mtime, data)
    return dict(data)


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


# ── Logros ───────────────────────────────────────────────────────────────────
# Van con la cuenta (no con el navegador) para que se vean igual en cualquier
# dispositivo. «achievements» = {id: fecha en ms}; «ach_seen» = {id: [valores
# ya vistos]} para los logros de «haz todas las X» (temas, secciones...).
_ACH_ID_MAX = 40
_ACH_MAX_ITEMS = 200
_ACH_SEEN_MAX_VALUES = 50
_ACH_VALUE_MAX = 60


def _valid_ach_id(value) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= _ACH_ID_MAX
            and all(c.isalnum() or c == "-" for c in value))


def get_achievements(username: str) -> dict:
    with _lock:
        entry = _load().get(username) or {}
    unlocked = entry.get("achievements") if isinstance(entry.get("achievements"), dict) else {}
    seen = entry.get("ach_seen") if isinstance(entry.get("ach_seen"), dict) else {}
    return {"unlocked": dict(unlocked), "seen": {k: list(v) for k, v in seen.items() if isinstance(v, list)}}


def merge_achievements(username: str, unlocked: dict | None = None, seen: dict | None = None) -> dict:
    """
    Añade logros conseguidos y valores vistos sin quitar nada: si el mismo
    logro llega dos veces (dos navegadores), se queda con la fecha más antigua.
    Devuelve el estado completo tras la mezcla.
    """
    with _lock:
        data = _load()
        current = data.get(username)
        entry: dict = current if isinstance(current, dict) else {}
        have = entry.get("achievements") if isinstance(entry.get("achievements"), dict) else {}
        have_seen = entry.get("ach_seen") if isinstance(entry.get("ach_seen"), dict) else {}
        changed = False
        for ach_id, when in (unlocked or {}).items():
            if not _valid_ach_id(ach_id) or isinstance(when, bool) or not isinstance(when, (int, float)) or when <= 0:
                continue
            if ach_id not in have and len(have) >= _ACH_MAX_ITEMS:
                continue
            when = int(when)
            if ach_id not in have or when < have[ach_id]:
                have[ach_id] = when
                changed = True
        for ach_id, values in (seen or {}).items():
            if not _valid_ach_id(ach_id) or not isinstance(values, list):
                continue
            if ach_id not in have_seen and len(have_seen) >= _ACH_MAX_ITEMS:
                continue
            bucket = have_seen.get(ach_id) if isinstance(have_seen.get(ach_id), list) else []
            for value in values:
                if (isinstance(value, str) and 0 < len(value) <= _ACH_VALUE_MAX
                        and value not in bucket and len(bucket) < _ACH_SEEN_MAX_VALUES):
                    bucket.append(value)
                    changed = True
            have_seen[ach_id] = bucket
        if changed:
            entry["achievements"] = have
            entry["ach_seen"] = have_seen
            data[username] = entry
            _write(data)
    return {"unlocked": dict(have), "seen": {k: list(v) for k, v in have_seen.items()}}
