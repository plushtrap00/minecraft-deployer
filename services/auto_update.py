"""
services/auto_update.py - Auto-actualización de la app desde origin/main.

Cada AUTO_UPDATE_INTERVAL_SECONDS comprueba si hay commits nuevos en
origin/main. Si los hay, y NO hay ningún servidor de Minecraft corriendo NI
ninguna subida/instalación en curso (services.busy), hace git pull y se
reinicia sola saliendo con código de error controlado — funciona igual tanto
si la app corre nativa bajo systemd (Restart=on-failure) como en Docker
(restart: unless-stopped), sin necesitar llamar a systemctl/docker ni darle
permisos de sudo extra al proceso.

Deshabilitado por defecto (AUTO_UPDATE_ENABLED=false): que la app se actualice
y reinicie sola es un cambio de comportamiento grande como para activarlo sin
que el usuario lo pida explícitamente en su .env.
"""
import os
import time
import threading
import subprocess
from pathlib import Path

from config import AUTO_UPDATE_ENABLED, AUTO_UPDATE_INTERVAL_SECONDS
from services import process as proc_module
from services.busy import is_busy, busy_reasons

_REPO_DIR = Path(__file__).resolve().parent.parent
_INITIAL_DELAY_SECONDS = 30
_GIT_TIMEOUT_SECONDS = 30

_status = {
    "enabled": AUTO_UPDATE_ENABLED,
    "interval_seconds": AUTO_UPDATE_INTERVAL_SECONDS,
    "in_docker": None,
    "last_check": None,
    "commits_behind": 0,
    "last_error": None,
}


def _log(message: str) -> None:
    print(f"[auto-update] {message}", flush=True)


def running_in_docker() -> bool:
    """
    /.dockerenv es el chequeo estándar (Docker lo crea en todo contenedor);
    /proc/1/cgroup como respaldo para runtimes que no lo generan (p.ej. algunas
    versiones de Podman) pero sí dejan rastro de containerd/kubepods ahí.
    """
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
        return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))
    except Exception:
        return False


def _git(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(_REPO_DIR),
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
    )


def _commits_behind() -> int:
    fetch = _git(["fetch", "--quiet", "origin"])
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch falló: {fetch.stderr.strip()}")
    count = _git(["rev-list", "HEAD..origin/main", "--count"])
    if count.returncode != 0:
        raise RuntimeError(f"git rev-list falló: {count.stderr.strip()}")
    return int(count.stdout.strip() or "0")


def _pull() -> None:
    result = _git(["pull", "--quiet", "origin", "main"])
    if result.returncode != 0:
        raise RuntimeError(f"git pull falló: {result.stderr.strip()}")


def _server_running() -> bool:
    with proc_module.mc_process_lock:
        proc = proc_module.mc_process
        return proc is not None and proc.poll() is None


def _check_and_update_once() -> None:
    try:
        behind = _commits_behind()
    except Exception as e:
        _status["last_error"] = str(e)
        _log(f"no se pudo comprobar actualizaciones: {e}")
        return

    _status["last_check"] = time.time()
    _status["commits_behind"] = behind
    _status["last_error"] = None
    if behind <= 0:
        return

    if _server_running():
        _log(f"hay {behind} commit(s) nuevos, pero hay un servidor de Minecraft en marcha — se pospone.")
        return
    if is_busy():
        _log(f"hay {behind} commit(s) nuevos, pero hay una operación en curso ({', '.join(busy_reasons())}) — se pospone.")
        return

    _log(f"aplicando {behind} commit(s) nuevos...")
    try:
        _pull()
    except Exception as e:
        _status["last_error"] = str(e)
        _log(f"git pull falló: {e}")
        return

    in_docker = running_in_docker()
    _log(f"actualización aplicada, reiniciando ({'contenedor' if in_docker else 'servicio systemd'})...")
    # Salir con código != 0 alcanza para los dos casos: systemd (Restart=on-
    # failure) y Docker (restart: unless-stopped, que reinicia sin importar el
    # código de salida) lo relanzan solos.
    os._exit(1)


def _loop() -> None:
    time.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        _check_and_update_once()
        time.sleep(AUTO_UPDATE_INTERVAL_SECONDS)


def start() -> None:
    _status["in_docker"] = running_in_docker()
    if not AUTO_UPDATE_ENABLED:
        _log("deshabilitado (AUTO_UPDATE_ENABLED=false en .env)")
        return
    _log(
        f"habilitado, comprobando cada {AUTO_UPDATE_INTERVAL_SECONDS}s "
        f"(entorno detectado: {'Docker' if _status['in_docker'] else 'nativo/systemd'})"
    )
    threading.Thread(target=_loop, daemon=True).start()


def get_status() -> dict:
    return {
        **_status,
        "server_running": _server_running(),
        "busy": is_busy(),
        "busy_reasons": busy_reasons(),
    }
