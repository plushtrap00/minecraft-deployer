"""
update_guard.py - Red de seguridad de las actualizaciones de la app.

Solo usa la librería estándar a propósito: tiene que funcionar aunque la
versión nueva traiga una dependencia rota o un módulo que no carga.

Cómo funciona (ver también services/auto_update.apply_update):

1. Antes de reiniciar, la versión que está corriendo hace el git pull,
   instala las librerías nuevas si requirements.txt cambió y comprueba en un
   proceso aparte que `import main` funciona. Si algo de eso falla, vuelve al
   commit anterior sin reiniciar (rollback()).
2. Si todo va bien, apunta aquí el commit anterior y el nuevo con el estado
   «verifying» (begin()) y se reinicia.
3. Cada arranque llama a on_boot() lo primero de todo (main.py). Si el
   estado sigue en «verifying», cuenta un arranque más; al pasar de
   MAX_BOOTS (la versión nueva se ha caído al arrancar), vuelve al commit
   anterior y se relanza con él.
4. Ya arrancada, services/auto_update.start_health_check() se llama a sí
   misma por HTTP: si responde, el estado pasa a «ok»; si en
   HEALTH_TIMEOUT_SECONDS no responde, también vuelve atrás.

El estado vive en .update_state.json en la carpeta de la app (gitignored):
git reset --hard no lo toca y no depende de que el .env se pueda leer.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
STATE_FILE = REPO_DIR / ".update_state.json"
# Arranques que se le permiten a una versión nueva antes de darla por rota.
MAX_BOOTS = 2
HEALTH_TIMEOUT_SECONDS = 90
GIT_TIMEOUT_SECONDS = 60


def _state_file(repo: Path | None) -> Path:
    return (repo or REPO_DIR) / STATE_FILE.name


def read_state(repo: Path | None = None) -> dict:
    try:
        data = json.loads(_state_file(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict, repo: Path | None = None) -> None:
    target = _state_file(repo)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def _git(args: list, repo: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo or REPO_DIR, capture_output=True, text=True,
                          timeout=GIT_TIMEOUT_SECONDS)


def head(repo: Path | None = None) -> str:
    result = _git(["rev-parse", "HEAD"], repo)
    if result.returncode != 0:
        raise RuntimeError(f"git rev-parse falló: {result.stderr.strip()}")
    return result.stdout.strip()


def reset_to(commit: str, repo: Path | None = None) -> None:
    result = _git(["reset", "--hard", "--quiet", commit], repo)
    if result.returncode != 0:
        raise RuntimeError(f"git reset falló: {result.stderr.strip()}")


def begin(previous: str, target: str, from_version: str, to_version: str, repo: Path | None = None) -> None:
    """La versión nueva ya está en disco y ha pasado la comprobación previa."""
    _write_state({
        "status": "verifying", "previous": previous, "target": target,
        "from_version": from_version, "to_version": to_version,
        "boots": 0, "at": time.time(), "error": None,
    }, repo)


def confirm_ok(repo: Path | None = None) -> bool:
    """La versión nueva responde: se da por buena. True si había algo que confirmar."""
    state = read_state(repo)
    if state.get("status") != "verifying":
        return False
    state.update({"status": "ok", "confirmed_at": time.time()})
    _write_state(state, repo)
    return True


def rollback(reason: str, repo: Path | None = None) -> bool:
    """Vuelve al commit de antes de la actualización. True si lo ha hecho."""
    state = read_state(repo)
    previous = state.get("previous")
    if state.get("status") != "verifying" or not previous:
        return False
    reset_to(previous, repo)
    state.update({"status": "rolled_back", "error": reason, "rolled_back_at": time.time()})
    _write_state(state, repo)
    print(f"[actualización] {reason} — se ha vuelto a la versión anterior ({previous[:7]}).", flush=True)
    return True


def on_boot(repo: Path | None = None, restart=None) -> None:
    """Lo primero de main.py: cuenta arranques de una versión sin confirmar."""
    try:
        state = read_state(repo)
        if state.get("status") != "verifying":
            return
        state["boots"] = int(state.get("boots") or 0) + 1
        _write_state(state, repo)
        if state["boots"] <= MAX_BOOTS:
            return
        if rollback(f"la versión {state.get('to_version') or '?'} no ha conseguido arrancar "
                    f"({MAX_BOOTS} intentos)", repo):
            if restart:
                restart()
                return
            # El main.py que se está ejecutando ya es el de la versión rota: se
            # relanza el proceso para cargar el de la anterior. En Linux execv
            # sustituye este proceso sin que systemd/Docker noten nada; en
            # Windows execv crea otro y termina este, así que allí se sale con
            # error y se deja que lo relance quien lo vigila.
            if os.name == "posix":
                os.execv(sys.executable, [sys.executable, *sys.argv])
            sys.exit(1)
    except Exception as e:  # la red de seguridad nunca debe impedir arrancar
        print(f"[actualización] no se pudo comprobar el estado de la última actualización: {e}", flush=True)
