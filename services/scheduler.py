"""
services/scheduler.py - Hilo en segundo plano que, cada pocos segundos:

- toma una muestra de rendimiento por minuto del servidor encendido
  (services/history.py), aunque nadie tenga el panel abierto;
- hace las copias automáticas del mundo cada N horas mientras está encendido;
- ejecuta las tareas programadas (services/automation.py) a su hora, con
  avisos previos a los jugadores para reinicios y paradas.

Las horas son las del sistema donde corre el panel (en Docker suele ser UTC
si no se configura TZ): el panel muestra esa hora junto a las tareas.
"""
import threading
import time
from datetime import datetime, timedelta

from fastapi import HTTPException

from services import automation, backups, history, server_control
from services import process as proc_module
from services.metrics import mc_metrics
from services.notify import notify

TICK_SECONDS = 15
SAMPLE_SECONDS = 60

_thread = None
_stop = threading.Event()
_done_keys: dict = {}            # (tarea, fecha y hora, fase) ya ejecutados
_task_status: dict = {}          # tarea -> {"at", "ok", "message"} de la última vez
_backup_running = threading.Event()
_last_sample = 0.0
_last_prune = 0.0


def task_status() -> dict:
    return dict(_task_status)


def describe_task(task: dict) -> str:
    if task["kind"] == "command":
        return f"comando «{task['command']}»"
    if task["kind"] == "start":
        return f"encender {task['modpack']}"
    return automation.TASK_KINDS[task["kind"]].lower()


def _phases(task: dict) -> list:
    """Minutos antes de la hora en que hay que hacer algo: avisos y la acción (0)."""
    warn = task.get("warn_minutes") or 0
    phases = {0}
    if warn:
        phases.add(warn)
        if warn > 1:
            phases.add(1)
    return sorted(phases, reverse=True)


def due_phases(task: dict, now: datetime) -> list:
    """Fases de una tarea que tocan en este minuto: [(minutos_antes, clave)]."""
    due = []
    if not task.get("enabled"):
        return due
    for minutes in _phases(task):
        target = now + timedelta(minutes=minutes)
        if target.strftime("%H:%M") == task["time"] and target.weekday() in task["days"]:
            due.append((minutes, (task["id"], target.strftime("%Y-%m-%d %H:%M"), minutes)))
    return due


def _warn_text(task: dict, minutes: int) -> str:
    action = "se reiniciará" if task["kind"] == "restart" else "se va a parar"
    unit = "minuto" if minutes == 1 else "minutos"
    return f"El servidor {action} en {minutes} {unit}."


def run_task(task: dict) -> str:
    """Ejecuta la acción de una tarea. Devuelve un texto con el resultado o lanza."""
    kind = task["kind"]
    if kind == "start":
        if server_control.is_running():
            return "ya había un servidor encendido"
        server_control.start_server(task["modpack"])
        return f"{task['modpack']} arrancando"
    modpack = server_control.running_modpack()
    if not modpack:
        return "no había ningún servidor encendido"
    if kind == "restart":
        server_control.say("Reiniciando el servidor…")
        time.sleep(3)
        server_control.restart_server()
        return f"{modpack} reiniciado"
    if kind == "stop":
        server_control.say("Parando el servidor…")
        time.sleep(3)
        server_control.stop_server()
        return f"{modpack} parado"
    if kind == "command":
        server_control.send_command(task["command"])
        return f"comando enviado a {modpack}"
    if kind == "backup":
        settings = automation.load()["backups"]
        result = backups.create_backup(modpack, "task", keep=settings["keep"])
        return f"copia {result['name']}"
    raise ValueError("Tipo de tarea desconocido")


def run_task_in_background(task: dict) -> None:
    def work():
        try:
            message = run_task(task)
            _task_status[task["id"]] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": True, "message": message}
            notify("task", f"⏰ Tarea programada ({describe_task(task)}): {message}.")
        except server_control.PendingModsError as e:
            _fail(task, "faltan mods por instalar: " + ", ".join(e.pending))
        except HTTPException as e:
            _fail(task, str(e.detail))
        except Exception as e:
            _fail(task, str(e))

    threading.Thread(target=work, daemon=True, name="tarea-" + task["id"]).start()


def _fail(task: dict, message: str) -> None:
    _task_status[task["id"]] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": False, "message": message}
    notify("task", f"⚠️ La tarea programada ({describe_task(task)}) ha fallado: {message}")


def _check_tasks(now: datetime) -> None:
    for task in automation.load()["tasks"]:
        for minutes, key in due_phases(task, now):
            if key in _done_keys:
                continue
            _done_keys[key] = time.time()
            if minutes > 0:
                if server_control.is_running():
                    server_control.say(_warn_text(task, minutes))
            else:
                run_task_in_background(task)
    # Las claves de hace más de un día ya no pueden repetirse.
    old = time.time() - 86400
    for key in [k for k, at in _done_keys.items() if at < old]:
        _done_keys.pop(key, None)


def _maybe_auto_backup() -> None:
    settings = automation.load()["backups"]
    modpack = server_control.running_modpack()
    if not settings["enabled"] or not modpack or not proc_module.mc_ready or _backup_running.is_set():
        return
    last = backups.last_backup_time(modpack, reasons=("auto",))
    started = proc_module.mc_ready_since or time.time()
    # La primera automática de cada sesión, a las N horas de arrancar (no al
    # momento: si se acaba de encender no hay nada nuevo que guardar).
    reference = max(last or 0, started)
    if time.time() - reference < settings["interval_hours"] * 3600:
        return

    def work():
        _backup_running.set()
        try:
            result = backups.create_backup(modpack, "auto", keep=settings["keep"])
            notify("backup_done", f"💾 Copia automática de {modpack} hecha ({result['size'] // 1048576} MB).")
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            server_control.deployer_line(f"La copia automática ha fallado: {detail}")
            notify("backup_failed", f"⚠️ La copia automática de {modpack} ha fallado: {detail}")
        finally:
            _backup_running.clear()

    threading.Thread(target=work, daemon=True, name="copia-automatica").start()


def _maybe_sample() -> None:
    global _last_sample, _last_prune
    now = time.time()
    if now - _last_sample < SAMPLE_SECONDS:
        return
    modpack = server_control.running_modpack()
    if not modpack or not proc_module.mc_ready:
        return
    _last_sample = now
    server_control.refresh_metrics()
    history.append(modpack, {
        "t": now,
        "tps": mc_metrics.get("tps"),
        "mspt": mc_metrics.get("mspt"),
        "players": len(mc_metrics.get("players_online") or []),
        "ram": mc_metrics.get("ram_used_mb"),
    })
    if now - _last_prune > 3600:
        _last_prune = now
        history.prune_all()


def _loop() -> None:
    steps = (
        ("tareas", lambda: _check_tasks(datetime.now())),
        ("copias", _maybe_auto_backup),
        ("historial", _maybe_sample),
    )
    while not _stop.wait(TICK_SECONDS):
        for name, step in steps:
            try:
                step()
            except Exception as e:
                print(f"[planificador] {name}: {e!r}", flush=True)


def start() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="planificador")
        _thread.start()


def stop() -> None:
    _stop.set()
