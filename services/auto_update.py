"""
services/auto_update.py - Detección (y aplicación manual) de actualizaciones
de la app desde origin/main.

Cada AUTO_UPDATE_INTERVAL_SECONDS comprueba si hay commits nuevos en
origin/main — pero SOLO hasta la primera vez que encuentra alguno: una vez
detectado, deja de volver a preguntarle a GitHub (no tiene sentido seguir
comprobando algo que ya se sabe) y se queda mostrando ese estado hasta que
se aplique. Aplicar la actualización (git pull + reinicio) ya NO es
automático: lo dispara el botón "Actualizar" del panel, vía apply_update(),
que revisa de nuevo en ese momento que no haya ningún servidor de Minecraft
corriendo ni ninguna subida/instalación en curso (services.busy) antes de
tocar nada.

Junto al número de commits pendientes se guardan las novedades que traen
(pending_changes()): las entradas del historial de version.py de origin/main
más nuevas que la versión instalada, que ya están escritas para el usuario y
en castellano. Las traducciones van aparte, un archivo por idioma en
static/i18n/changelog/<idioma>.json ({versión: texto}), y se leen también de
origin/main; localize_status() da a cada cuenta las de su idioma. Los commits que no suben versión ni dejan entrada aparecen por
su asunto, para que ninguno quede sin explicar.

Antes de reiniciar se comprueba que la versión nueva carga (ver
update_guard.py): si no, se vuelve sola a la anterior, y lo mismo si después
del reinicio no llega a arrancar o a responder.

El reinicio posterior sale con código de error controlado — funciona igual
tanto si la app corre nativa bajo systemd (Restart=on-failure) como en Docker
(restart: unless-stopped), sin necesitar llamar a systemctl/docker ni darle
permisos de sudo extra al proceso.

Deshabilitado por defecto (AUTO_UPDATE_ENABLED=false): ni siquiera comprobar
solo es algo que un usuario debería pedir a propósito en su .env.
"""
import ast
import json
import os
import re
import sys
import time
import threading
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import update_guard

from config import AUTO_UPDATE_ENABLED, AUTO_UPDATE_INTERVAL_SECONDS, WEB_PORT
from app_constants import AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS, AUTO_UPDATE_GIT_TIMEOUT_SECONDS
from services import process as proc_module
from services import i18n
from services.busy import is_busy, busy_reasons
from version import APP_VERSION

_REPO_DIR = Path(__file__).resolve().parent.parent
# Historiales traducidos, relativo al repo (se piden a git con esta ruta).
CHANGELOG_DIR = "static/i18n/changelog"
_INITIAL_DELAY_SECONDS = AUTO_UPDATE_CHECK_INITIAL_DELAY_SECONDS
_GIT_TIMEOUT_SECONDS = AUTO_UPDATE_GIT_TIMEOUT_SECONDS

_status = {
    "enabled": AUTO_UPDATE_ENABLED,
    "interval_seconds": AUTO_UPDATE_INTERVAL_SECONDS,
    "in_docker": None,
    "last_check": None,
    "commits_behind": 0,
    "last_error": None,
    # Qué trae la actualización pendiente (ver pending_changes()); vacío y
    # None mientras no haya commits nuevos.
    "remote_version": None,
    "changes": [],
    "other_commits": [],
}

# Se enciende cuando se guarda un cambio real en .env o .APP_CONSTANTS (ver
# routes/config_admin.py) para que el panel pueda ofrecer reiniciar más tarde
# desde el monitor de sistema, no solo en el momento de guardar. No hace
# falta apagarlo a mano: al reiniciar, este módulo se reimporta desde cero y
# vuelve a False solo.
_restart_pending = False


def mark_restart_pending() -> None:
    global _restart_pending
    _restart_pending = True


def _log(message: str) -> None:
    print(f"[auto-update] {message}", flush=True)


def running_in_docker() -> bool:
    """
    /.dockerenv es la comprobación estándar (Docker lo crea en todo contenedor);
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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _commits_behind() -> int:
    fetch = _git(["fetch", "--quiet", "origin"])
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch falló: {fetch.stderr.strip()}")
    count = _git(["rev-list", "HEAD..origin/main", "--count"])
    if count.returncode != 0:
        raise RuntimeError(f"git rev-list falló: {count.stderr.strip()}")
    return int(count.stdout.strip() or "0")


# Una entrada del historial de version.py: "- 2.1.7 (2026-11-20): texto",
# con el texto siguiendo en las líneas sangradas de debajo.
_HISTORY_ENTRY_RE = re.compile(
    r"^- (\d+(?:\.\d+)+) \((\d{4}-\d{2}-\d{2})\): (.*?)(?=^- |\Z)",
    re.MULTILINE | re.DOTALL,
)
# Asunto de un commit que sube versión: "... (v2.1.7)".
_SUBJECT_VERSION_RE = re.compile(r"\(v(\d+(?:\.\d+)+)\)\s*$")


def _version_tuple(version: str) -> tuple:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def parse_version_file(source: str) -> tuple:
    """
    Saca de un version.py (como texto, sin ejecutarlo) su APP_VERSION y las
    entradas del historial del docstring: (versión, [{version, date, text}]).
    """
    tree = ast.parse(source)
    version = None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "APP_VERSION"
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            version = node.value.value
    entries = []
    for match in _HISTORY_ENTRY_RE.finditer(ast.get_docstring(tree) or ""):
        text = " ".join(match.group(3).split())
        entries.append({"version": match.group(1), "date": match.group(2), "text": text})
    return version, entries


def parse_changelog(source: str) -> dict:
    """Un historial traducido (static/i18n/changelog/<idioma>.json): {versión: texto}."""
    try:
        data = json.loads(source)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: " ".join(value.split()) for key, value in data.items()
            if not key.startswith("//") and isinstance(value, str) and value.strip()}


def pending_changes(local_version: str, remote_source: str, commit_subjects: list,
                    changelogs: dict | None = None) -> dict:
    """
    Qué trae la actualización: las entradas del historial remoto más nuevas
    que local_version (de la más reciente a la más antigua) y los asuntos de
    los commits pendientes cuya versión no tiene entrada (o que no suben
    versión).

    changelogs ({idioma: {versión: texto}}) son los historiales traducidos;
    cada entrada guarda los suyos en "texts" y localize_status() elige.
    """
    remote_version, entries = None, []
    if remote_source:
        try:
            remote_version, entries = parse_version_file(remote_source)
        except SyntaxError:
            pass
    local = _version_tuple(local_version)
    changes = [e for e in entries if _version_tuple(e["version"]) > local]
    for change in changes:
        change["texts"] = {lang: table[change["version"]]
                           for lang, table in (changelogs or {}).items() if change["version"] in table}
    covered = {e["version"] for e in changes}
    other = []
    for subject in commit_subjects:
        match = _SUBJECT_VERSION_RE.search(subject)
        if not (match and match.group(1) in covered):
            other.append(subject)
    return {"remote_version": remote_version, "changes": changes, "other_commits": other}


def _fetch_pending_changes() -> dict:
    """Novedades de HEAD..origin/main; nunca falla (sin datos si git falla)."""
    subjects = []
    log = _git(["log", "--format=%s", "HEAD..origin/main"])
    if log.returncode == 0:
        subjects = [line.strip() for line in log.stdout.splitlines() if line.strip()]
    show = _git(["show", "origin/main:version.py"])
    remote_source = show.stdout if show.returncode == 0 else ""
    # Los historiales traducidos, también los de origin/main: los locales aún
    # no tienen las entradas nuevas.
    changelogs = {}
    for lang in i18n.LANGS:
        if lang == i18n.DEFAULT_LANG:
            continue
        shown = _git(["show", f"origin/main:{CHANGELOG_DIR}/{lang}.json"])
        if shown.returncode == 0:
            changelogs[lang] = parse_changelog(shown.stdout)
    return pending_changes(APP_VERSION, remote_source, subjects, changelogs)


def localize_status(status: dict, lang: str) -> dict:
    """El estado con el texto de cada novedad en el idioma pedido (si no, en español)."""
    changes = [{key: value for key, value in change.items() if key != "texts"}
               | {"text": (change.get("texts") or {}).get(lang, change["text"])}
               for change in status.get("changes") or []]
    return {**status, "changes": changes}


def _store_check_result(behind: int) -> None:
    _status["last_check"] = time.time()
    _status["commits_behind"] = behind
    _status["last_error"] = None
    if behind > 0:
        _status.update(_fetch_pending_changes())
    else:
        _status.update({"remote_version": None, "changes": [], "other_commits": []})


def _pull() -> None:
    result = _git(["pull", "--quiet", "--ff-only", "origin", "main"])
    if result.returncode != 0:
        raise RuntimeError(f"git pull falló: {result.stderr.strip()}")


# Tiempo máximo para instalar librerías nuevas y para probar a cargar la
# versión nueva antes de reiniciar.
_PIP_TIMEOUT_SECONDS = 900
_IMPORT_CHECK_TIMEOUT_SECONDS = 180


def _local_changes() -> list:
    """Archivos de la app (versionados) cambiados a mano: el pull los pisaría o fallaría."""
    result = _git(["status", "--porcelain", "--untracked-files=no"])
    if result.returncode != 0:
        raise RuntimeError(f"git status falló: {result.stderr.strip()}")
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def _requirements() -> bytes:
    try:
        return (_REPO_DIR / "requirements.txt").read_bytes()
    except OSError:
        return b""


def _install_requirements() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt"],
        cwd=_REPO_DIR, capture_output=True, text=True, timeout=_PIP_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[-600:] or f"pip salió con código {result.returncode}")


def _check_new_version_loads() -> None:
    """Carga la versión nueva en otro proceso (sin arrancarla) para ver que no está rota."""
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=_REPO_DIR, capture_output=True, text=True, timeout=_IMPORT_CHECK_TIMEOUT_SECONDS,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        lines = [line for line in (result.stderr or result.stdout).strip().splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else f"python salió con código {result.returncode}")


def _version_on_disk() -> str:
    try:
        return parse_version_file((_REPO_DIR / "version.py").read_text(encoding="utf-8"))[0] or "?"
    except OSError:
        return "?"


def _server_running() -> bool:
    with proc_module.mc_process_lock:
        proc = proc_module.mc_process
        return proc is not None and proc.poll() is None


def _check_and_update_once() -> None:
    if _status["commits_behind"] > 0:
        # Ya se sabe que hay una actualización pendiente: no tiene sentido
        # seguir preguntándole a GitHub cada ciclo. Se queda así hasta que
        # apply_update() la aplique (y con eso, la app se reinicia y este
        # estado vuelve a arrancar en 0 de todas formas).
        return
    try:
        behind = _commits_behind()
    except Exception as e:
        _status["last_error"] = str(e)
        _log(f"no se pudo comprobar actualizaciones: {e}")
        return

    _store_check_result(behind)
    if behind > 0:
        _log(f"hay {behind} commit(s) nuevos disponibles — esperando que se aplique desde el panel.")


def _loop() -> None:
    time.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        _check_and_update_once()
        time.sleep(AUTO_UPDATE_INTERVAL_SECONDS)


def check_now() -> dict:
    """
    Fuerza una comprobación inmediata contra GitHub (botón "Comprobar ahora"
    del panel) — a diferencia de _check_and_update_once() (el bucle en
    segundo plano), SIEMPRE vuelve a preguntarle a GitHub aunque ya se supiera
    de una actualización pendiente, porque aquí es el usuario quien lo pide
    explícitamente. Funciona aunque AUTO_UPDATE_ENABLED esté en false: revisar
    a mano es una acción independiente de que la comprobación automática esté
    activado.
    """
    try:
        behind = _commits_behind()
    except Exception as e:
        _status["last_check"] = time.time()
        _status["last_error"] = str(e)
        raise RuntimeError(str(e))
    _store_check_result(behind)
    return get_status()


def apply_update() -> None:
    """
    Dispara el pull + reinicio bajo demanda (botón "Actualizar" del panel).
    Lanza RuntimeError con un mensaje legible si no es seguro hacerlo ahora
    mismo. No reinicia la app ella misma: eso lo hace schedule_restart(),
    llamado aparte por el route handler DESPUÉS de mandar la respuesta HTTP,
    para que el cliente llegue a recibir la confirmación antes de que el
    proceso muera.
    """
    if _server_running():
        raise RuntimeError("No se puede actualizar: hay un servidor de Minecraft en marcha.")
    if is_busy():
        raise RuntimeError(f"No se puede actualizar: hay una operación en curso ({', '.join(busy_reasons())}).")

    changed = _local_changes()
    if changed:
        raise RuntimeError(
            f"No se puede actualizar: hay archivos de la app modificados a mano ({', '.join(changed[:5])}). "
            "Deshaz esos cambios o guárdalos aparte antes de actualizar."
        )

    _log("aplicando actualización pedida desde el panel...")
    previous = update_guard.head(_REPO_DIR)
    old_requirements = _requirements()
    _pull()
    target = update_guard.head(_REPO_DIR)
    if target == previous:
        _store_check_result(0)
        return

    def undo(message: str) -> None:
        update_guard.reset_to(previous, _REPO_DIR)
        if _requirements() != new_requirements:
            try:
                _install_requirements()
            except Exception as e:
                _log(f"no se pudieron reinstalar las librerías de la versión anterior: {e}")
        _log(message)
        _status["last_error"] = message
        raise RuntimeError(message)

    new_requirements = _requirements()
    if new_requirements != old_requirements:
        _log("la versión nueva cambia requirements.txt: instalando librerías...")
        try:
            _install_requirements()
        except Exception as e:
            undo(f"La actualización necesita librerías nuevas y no se pudieron instalar; se ha vuelto a la versión anterior. Error: {e}")
    try:
        _check_new_version_loads()
    except Exception as e:
        undo(f"La versión nueva no se puede cargar; se ha vuelto a la versión anterior. Error: {e}")

    update_guard.begin(previous, target, APP_VERSION, _version_on_disk(), _REPO_DIR)
    _store_check_result(0)


def restart_now() -> None:
    """
    Reinicio manual sin tocar el repo (botón "Guardar y reiniciar" del panel
    de administración, tras cambiar .env o .APP_CONSTANTS). Mismas dos
    condiciones de seguridad que apply_update(); el reinicio en sí también lo
    dispara aparte schedule_restart(), llamado por el route handler.
    """
    if _server_running():
        raise RuntimeError("No se puede reiniciar: hay un servidor de Minecraft en marcha.")
    if is_busy():
        raise RuntimeError(f"No se puede reiniciar: hay una operación en curso ({', '.join(busy_reasons())}).")
    _log("reinicio manual pedido desde el panel de administración...")


def schedule_restart(delay_seconds: float = 1.0) -> None:
    in_docker = running_in_docker()
    _log(f"reiniciando en {delay_seconds}s ({'contenedor' if in_docker else 'servicio systemd'})...")
    # Salir con código != 0 basta para los dos casos: systemd (Restart=on-
    # failure) y Docker (restart: unless-stopped, que reinicia sin importar el
    # código de salida) lo relanzan solos.
    threading.Timer(delay_seconds, lambda: os._exit(1)).start()


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


def start_health_check() -> None:
    """
    Tras arrancar una versión recién instalada, comprueba que el panel
    responde de verdad (no basta con que el proceso viva). Si responde, se da
    por buena; si no lo hace a tiempo, se vuelve a la anterior y se reinicia.
    """
    if update_guard.read_state(_REPO_DIR).get("status") != "verifying":
        return

    def run():
        deadline = time.monotonic() + update_guard.HEALTH_TIMEOUT_SECONDS
        url = f"http://127.0.0.1:{WEB_PORT}/api/auth/verify"
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                urllib.request.urlopen(url, timeout=5).close()
                alive = True
            except urllib.error.HTTPError:
                alive = True  # 401 sin sesión: el panel contesta, que es lo que importa
            except (OSError, ValueError):
                alive = False
            if alive:
                if update_guard.confirm_ok(_REPO_DIR):
                    _log(f"la versión {APP_VERSION} arranca y responde: actualización confirmada.")
                return
        try:
            if update_guard.rollback(f"la versión {APP_VERSION} arrancó pero no respondía", _REPO_DIR):
                schedule_restart()
        except Exception as e:
            _log(f"no se pudo volver a la versión anterior: {e}")

    threading.Thread(target=run, daemon=True, name="update-health").start()


def last_update() -> dict | None:
    """Resultado de la última actualización aplicada (para avisar si se deshizo)."""
    state = update_guard.read_state(_REPO_DIR)
    if not state.get("status"):
        return None
    return {key: state.get(key) for key in ("status", "from_version", "to_version", "error", "at")}


def get_status() -> dict:
    return {
        **_status,
        "server_running": _server_running(),
        "busy": is_busy(),
        "busy_reasons": busy_reasons(),
        "restart_pending": _restart_pending,
        "last_update": last_update(),
    }
