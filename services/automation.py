"""
services/automation.py - Ajustes de automatización, guardados en
SERVERS_PATH/.global/automation.json:

- auto_restart: volver a arrancar el servidor si se cae (con un límite de
  intentos para no entrar en bucle si cae nada más arrancar).
- backups: copias automáticas del mundo mientras el servidor está encendido.
- tasks: tareas programadas (reiniciar, parar, encender, comando o copia a una
  hora y unos días de la semana).

No van en el .env porque no son secretos ni de la instalación: se cambian
desde el panel y se aplican al momento.
"""
import json
import re
import threading
import uuid

from config import DEFAULT_SERVERS_PATH

AUTOMATION_FILE = DEFAULT_SERVERS_PATH / ".global" / "automation.json"
_lock = threading.Lock()

TASK_KINDS = {
    "restart": "Reiniciar el servidor",
    "stop": "Parar el servidor",
    "start": "Encender un servidor",
    "command": "Ejecutar un comando",
    "backup": "Hacer una copia del mundo",
}
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

DEFAULTS = {
    "auto_restart": {"enabled": True, "max_attempts": 3, "window_minutes": 10},
    "backups": {"enabled": False, "interval_hours": 6, "keep": 5},
    "tasks": [],
}


def _clamp_int(value, low, high, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clean_task(raw: dict) -> dict:
    """Valida una tarea. Lanza ValueError con un mensaje para el usuario."""
    if not isinstance(raw, dict):
        raise ValueError("Tarea no válida")
    kind = raw.get("kind")
    if kind not in TASK_KINDS:
        raise ValueError("Tipo de tarea desconocido")
    time_text = str(raw.get("time", "")).strip()
    if not _TIME_RE.match(time_text):
        raise ValueError("La hora tiene que ser HH:MM (por ejemplo 05:00)")
    days = sorted({int(d) for d in raw.get("days", []) if str(d).isdigit() and 0 <= int(d) <= 6})
    if not days:
        raise ValueError("Elige al menos un día")
    task = {
        "id": str(raw.get("id") or uuid.uuid4().hex[:12]),
        "enabled": bool(raw.get("enabled", True)),
        "kind": kind,
        "time": time_text,
        "days": days,
        "warn_minutes": _clamp_int(raw.get("warn_minutes", 0), 0, 30, 0) if kind in ("restart", "stop") else 0,
        "command": "",
        "modpack": "",
    }
    if kind == "command":
        command = str(raw.get("command", "")).strip().lstrip("/")
        if not command or any(ch in command for ch in "\r\n\x00"):
            raise ValueError("Escribe el comando (una sola línea)")
        task["command"] = command[:400]
    if kind == "start":
        modpack = str(raw.get("modpack", "")).strip()
        if not modpack or modpack.startswith(".") or "/" in modpack or "\\" in modpack:
            raise ValueError("Elige qué servidor encender")
        task["modpack"] = modpack
    return task


def _normalize(data: dict) -> dict:
    data = data if isinstance(data, dict) else {}
    restart = {**DEFAULTS["auto_restart"], **(data.get("auto_restart") or {})}
    backups = {**DEFAULTS["backups"], **(data.get("backups") or {})}
    tasks = []
    for raw in data.get("tasks") or []:
        try:
            tasks.append(_clean_task(raw))
        except (ValueError, TypeError):
            continue
    return {
        "auto_restart": {
            "enabled": bool(restart["enabled"]),
            "max_attempts": _clamp_int(restart["max_attempts"], 1, 10, 3),
            "window_minutes": _clamp_int(restart["window_minutes"], 1, 120, 10),
        },
        "backups": {
            "enabled": bool(backups["enabled"]),
            "interval_hours": _clamp_int(backups["interval_hours"], 1, 168, 6),
            "keep": _clamp_int(backups["keep"], 1, 100, 5),
        },
        "tasks": tasks,
    }


def load() -> dict:
    with _lock:
        try:
            data = json.loads(AUTOMATION_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    return _normalize(data)


def _write(data: dict) -> None:
    AUTOMATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTOMATION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(AUTOMATION_FILE)


def save_settings(auto_restart: dict | None = None, backups: dict | None = None) -> dict:
    current = load()
    if auto_restart is not None:
        current["auto_restart"] = {**current["auto_restart"], **auto_restart}
    if backups is not None:
        current["backups"] = {**current["backups"], **backups}
    data = _normalize(current)
    with _lock:
        _write(data)
    return data


def save_task(raw: dict) -> dict:
    """Crea o actualiza (si trae un id que ya existe) una tarea."""
    task = _clean_task(raw)
    current = load()
    tasks = [t for t in current["tasks"] if t["id"] != task["id"]]
    if len(tasks) >= 50:
        raise ValueError("Como mucho 50 tareas")
    existing_ids = [t["id"] for t in current["tasks"]]
    if task["id"] in existing_ids:
        index = existing_ids.index(task["id"])
        tasks.insert(index, task)
    else:
        tasks.append(task)
    current["tasks"] = tasks
    with _lock:
        _write(current)
    return task


def delete_task(task_id: str) -> bool:
    current = load()
    tasks = [t for t in current["tasks"] if t["id"] != task_id]
    if len(tasks) == len(current["tasks"]):
        return False
    current["tasks"] = tasks
    with _lock:
        _write(current)
    return True
