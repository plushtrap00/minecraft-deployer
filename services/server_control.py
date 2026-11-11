"""
services/server_control.py - Arrancar, parar y reiniciar el servidor de
Minecraft desde cualquier sitio: los botones del panel (routes/server.py),
las tareas programadas y el reinicio automático tras una caída
(services/scheduler.py) usan las mismas funciones.

También recibe los sucesos del hilo lector de la consola (services/process.py):
servidor listo, jugadores que entran o salen y el final del proceso, para
avisar por Telegram/Discord y volver a arrancar si se ha caído.
"""
import os
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager

from fastapi import HTTPException

from app_constants import GRACEFUL_STOP_TIMEOUT_SECONDS
from services import process as proc_module
from services.metrics import mc_metrics, read_proc_ram, _parse_metrics_line
from services.modpack import ensure_rcon_enabled, detect_modpack_version, prune_old_logs_and_crashes
from services.pending_mods import get_pending_mods
from services.notify import notify
from services.rcon import RconConnection, RconError
from routes.deps import modpack_path

# Una sola operación de arrancar/parar/reiniciar a la vez (botón del panel,
# tarea programada y reinicio tras caída podrían coincidir).
_control_lock = threading.RLock()


class PendingModsError(Exception):
    def __init__(self, pending: list):
        super().__init__("Faltan mods por instalar")
        self.pending = pending


def is_running() -> bool:
    with proc_module.mc_process_lock:
        proc = proc_module.mc_process
        return proc is not None and proc.poll() is None


def running_modpack() -> str | None:
    return proc_module.mc_running_modpack if is_running() else None


def deployer_line(text: str) -> None:
    """Línea propia del panel en la consola (en amarillo)."""
    proc_module._broadcast("\x1b[33m[Deployer] " + text + "\x1b[0m")


# ── Arrancar ──────────────────────────────────────────────────────────────────
_SOURCE_VARIABLES_RE = re.compile(
    rb'(?m)^([ \t]*(?:source|\.)[ \t]+["\']?(?:\./)?variables\.txt["\']?[ \t]*)(\r?)$'
)


def patch_sourced_variables(script: bytes) -> bytes:
    """
    Los start.sh de ServerPackCreator leen RESTART y WAIT_FOR_USER_INPUT de
    variables.txt («source ./variables.txt») al ejecutarse, así que ni el
    parche de RESTART de arriba ni las variables de entorno del Popen les
    afectan. Justo después de esa línea se fuerzan las dos a false: con
    WAIT_FOR_USER_INPUT=true, al cerrarse Minecraft por su cuenta (caída o
    /stop en el juego) el script se quedaba en «Press any key to continue»
    esperando una tecla que nunca llega, y el panel lo seguía viendo en marcha.
    """
    return _SOURCE_VARIABLES_RE.sub(rb'\1\2\nRESTART=false\2\nWAIT_FOR_USER_INPUT=false\2', script)


def start_server(modpack: str, force: bool = False, keep_output: bool = False) -> None:
    """
    Arranca el servidor. Lanza HTTPException (400/404) o PendingModsError si
    no se puede. keep_output: no vaciar la consola (al volver a arrancar tras
    una caída, para que se siga viendo qué pasó).
    """
    with _control_lock, proc_module.mc_process_lock:
        if proc_module.mc_process is not None and proc_module.mc_process.poll() is None:
            raise HTTPException(status_code=400, detail="Ya hay un servidor en marcha")

        server_dir = modpack_path(modpack)

        # Modpacks de CurseForge instalados con algún mod bloqueado por el autor
        # para descarga por terceros avisan antes de arrancar, pero se puede
        # arrancar igualmente a propósito con force (el aviso volverá a salir en
        # el siguiente intento normal). get_pending_mods() solo lee
        # mods-pendientes.json, así que es instantáneo.
        pending_mods = [] if force else get_pending_mods(modpack)
        if pending_mods:
            raise PendingModsError(pending_mods)

        script = next(
            (server_dir / s for s in ["startserver.sh", "start.sh", "run.sh"] if (server_dir / s).exists()),
            None
        )
        if script is None:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró script de arranque (startserver.sh / start.sh / run.sh) en {server_dir}"
            )

        # Parchear RESTART=true → false para evitar bucles de reinicio del propio script
        script_content = script.read_bytes()
        script_content = re.sub(
            rb'(?m)^(\s*RESTART\s*=\s*)["\']?true["\']?',
            rb'\1false',
            script_content
        )
        script_content = patch_sourced_variables(script_content)
        tmp = tempfile.NamedTemporaryFile(mode='wb', suffix='.sh', dir=str(server_dir), delete=False)
        tmp.write(script_content)
        tmp.close()
        patched_script = tmp.name
        os.chmod(patched_script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)

        if not keep_output:
            with proc_module.mc_output_lock:
                proc_module.mc_output_lines.clear()

        # Antes de cada sesión se podan los logs rotados y crash reports viejos.
        prune_old_logs_and_crashes(modpack)

        # Si se cambió online-mode desde la instalación, los ops/whitelist/bans
        # tienen los UUID del otro modo y Minecraft no reconocería a nadie.
        try:
            from services.players import adapt_player_uuids
            adapted = adapt_player_uuids(modpack)
        except Exception:
            adapted = []
        if adapted:
            deployer_line("Jugadores adaptados al online-mode actual del servidor: " + ", ".join(adapted))

        rcon_info = ensure_rcon_enabled(modpack)
        if rcon_info:
            proc_module.mc_rcon_host = rcon_info["host"]
            proc_module.mc_rcon_port = rcon_info["port"]
            proc_module.mc_rcon_password = rcon_info["password"]
            proc_module.mc_rcon_conn = RconConnection(
                rcon_info["host"], rcon_info["port"], rcon_info["password"]
            )
        else:
            proc_module.mc_rcon_host = None
            proc_module.mc_rcon_port = None
            proc_module.mc_rcon_password = None
            proc_module.mc_rcon_conn = None

        proc_module.mc_modloader = detect_modpack_version(modpack).get("modloader")
        proc_module.mc_stop_requested = False

        proc = subprocess.Popen(
            ["bash", patched_script],
            cwd=str(server_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            start_new_session=True,
            env={**os.environ, "RESTART": "false", "WAIT_FOR_USER_INPUT": "false"},
        )
        proc_module.mc_process = proc
        proc_module.mc_running_modpack = modpack

        threading.Thread(target=proc_module._reader_thread, args=(proc, patched_script), daemon=True).start()
        threading.Thread(target=proc_module._script_watchdog, args=(proc,), daemon=True).start()

        if proc_module.mc_rcon_conn is not None:
            threading.Thread(
                target=_rcon_warmup, args=(proc_module.mc_rcon_conn, proc), daemon=True
            ).start()


def _rcon_warmup(conn: RconConnection, proc: subprocess.Popen):
    """Autentica el RCON en cuanto el puerto esté disponible."""
    while proc.poll() is None:
        try:
            conn.command("list")
            return
        except (RconError, OSError):
            time.sleep(5)


# ── Parar ─────────────────────────────────────────────────────────────────────
def stop_server(timeout: float = GRACEFUL_STOP_TIMEOUT_SECONDS) -> bool:
    """
    Para el servidor guardando antes el mundo. Bloquea hasta que termina (hay
    que llamarla desde un hilo). Devuelve True si cerró por las buenas.
    Lanza HTTPException(400) si no hay servidor en marcha.
    """
    with _control_lock:
        with proc_module.mc_process_lock:
            proc = proc_module.mc_process
            if proc is None or proc.poll() is not None:
                raise HTTPException(status_code=400, detail="No hay servidor en marcha")
            proc_module.mc_stop_requested = True
            try:
                proc.stdin.write(b"save-all\n")
                proc.stdin.write(b"stop\n")
                proc.stdin.flush()
            except Exception:
                pass  # si falla escribir a stdin, el kill de grupo de abajo se encarga igual

        # Algunos .sh de arranque tienen su propio bucle que relanza java si no
        # reconocen cómo se les pidió parar: se espera al proceso java real y,
        # en cuanto cierra, se mata todo el grupo antes de que el bucle lo
        # vuelva a lanzar. Si no se encuentra (p. ej. «exec java»), se espera
        # al propio proceso.
        java_pid = proc_module.find_java_descendant_pid(proc.pid)
        if java_pid is not None and java_pid != proc.pid:
            graceful = proc_module.wait_java_exit(java_pid, timeout)
        else:
            graceful = proc_module.wait_process_exit(proc, timeout)

        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Se espera a que el hilo lector termine de limpiar el estado, para
        # que un arranque justo después (reinicio) no choque con él.
        deadline = time.monotonic() + 15
        while proc_module.mc_process is proc and time.monotonic() < deadline:
            time.sleep(0.2)
        return graceful


def restart_server() -> str:
    """Para y vuelve a arrancar el mismo modpack. Devuelve su nombre."""
    with _control_lock:
        modpack = running_modpack()
        if not modpack:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        stop_server()
        start_server(modpack, force=True)
        return modpack


# ── Comandos ──────────────────────────────────────────────────────────────────
def send_command(cmd: str) -> None:
    with proc_module.mc_process_lock:
        proc = proc_module.mc_process
        if proc is None or proc.poll() is not None:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        try:
            proc.stdin.write((cmd.strip() + "\n").encode("utf-8"))
            proc.stdin.flush()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


def say(text: str) -> None:
    """Mensaje a todos los jugadores (no falla si el servidor no está)."""
    try:
        send_command("say " + text)
    except HTTPException:
        pass


@contextmanager
def world_frozen(modpack: str):
    """
    Para copiar el mundo de un servidor encendido sin pillar archivos a medio
    escribir: save-off + save-all flush (esperando a «Saved the game») antes y
    save-on al terminar. Si ese modpack no está encendido, no hace nada.
    """
    frozen = False
    if running_modpack() == modpack and proc_module.mc_ready:
        try:
            waiter = proc_module.expect_line(r"Saved the game|Saved the world|ThreadedAnvilChunkStorage.*all chunks are saved")
            send_command("save-off")
            send_command("save-all flush")
            frozen = True
            if not waiter.wait(120):
                deployer_line("No llegó la confirmación de guardado; se copia igualmente.")
        except HTTPException:
            frozen = False
    try:
        yield
    finally:
        if frozen:
            try:
                send_command("save-on")
            except HTTPException:
                pass


# ── Métricas por RCON ─────────────────────────────────────────────────────────
# El comando propio del modloader responde bien por RCON (a diferencia de
# "spark tps", que devuelve respuesta vacía por RCON: bug conocido en
# https://github.com/lucko/spark/issues/119).
TPS_COMMANDS_BY_LOADER = {
    "NeoForge": ["neoforge tps", "forge tps"],
    "Forge": ["forge tps"],
}


def refresh_via_rcon(conn: RconConnection, modloader: str | None):
    """Ejecuta list + tps del modloader por RCON (no por stdin)."""
    try:
        resp = conn.command("list")
        for line in resp.splitlines():
            _parse_metrics_line(line)

        for cmd in TPS_COMMANDS_BY_LOADER.get(modloader, []):
            resp = conn.command(cmd)
            if resp.strip():
                for line in resp.splitlines():
                    _parse_metrics_line(line)
                break

        mc_metrics["rcon_status"] = "ok"
    except RconError as e:
        mc_metrics["rcon_status"] = f"error: {e}"
    except OSError as e:
        mc_metrics["rcon_status"] = f"sin conexión ({e})"


def refresh_metrics() -> bool:
    """Refresca TPS/jugadores/RAM del servidor encendido. False si no hay servidor."""
    with proc_module.mc_process_lock:
        proc = proc_module.mc_process
        if proc is None or proc.poll() is not None:
            return False
        conn = proc_module.mc_rcon_conn
        modloader = proc_module.mc_modloader
    if conn is not None:
        refresh_via_rcon(conn, modloader)
    else:
        mc_metrics["rcon_status"] = "no configurado (reinicia el servidor desde el panel)"
    read_proc_ram(proc.pid)
    return True


# ── Sucesos de la consola ─────────────────────────────────────────────────────
_JOIN_LEAVE_RE = re.compile(r"\]:\s*([A-Za-z0-9_]{1,16}) (joined|left) the game\s*$")
_crash_history: deque = deque()  # (momento, modpack) de las últimas caídas
_RESTART_DELAY_SECONDS = 10


def on_ready(modpack: str) -> None:
    notify("ready", f"✅ {modpack} está listo para jugar.")


def on_line(modpack: str, line: str) -> None:
    match = _JOIN_LEAVE_RE.search(line)
    if not match:
        return
    name, action = match.groups()
    if action == "joined":
        notify("join", f"👋 {name} ha entrado en {modpack}.")
    else:
        notify("leave", f"🚪 {name} ha salido de {modpack}.")


def on_exit(modpack: str, crashed: bool, eula_accepted: bool, was_ready: bool, uptime_seconds: float) -> None:
    """El proceso de Minecraft ha terminado (llamado desde el hilo lector)."""
    if not modpack:
        return
    if eula_accepted:
        # Primer arranque: Minecraft se cierra tras crear eula.txt. Ya está
        # aceptada, así que se vuelve a arrancar sin contarlo como caída.
        _restart_later(modpack, 2, "EULA aceptada: arrancando de nuevo…")
        return
    if not crashed:
        notify("stopped", f"⏹️ {modpack} se ha parado.")
        return

    from services import automation
    settings = automation.load()["auto_restart"]
    now = time.time()
    window = settings["window_minutes"] * 60
    while _crash_history and (now - _crash_history[0][0] > window or _crash_history[0][1] != modpack):
        _crash_history.popleft()
    _crash_history.append((now, modpack))
    attempt = len(_crash_history)
    when = "mientras arrancaba" if not was_ready else f"tras {int(uptime_seconds // 60)} min encendido"

    if settings["enabled"] and attempt <= settings["max_attempts"]:
        message = (f"El servidor se ha caído {when}. Arrancando de nuevo en {_RESTART_DELAY_SECONDS} s "
                   f"(intento {attempt} de {settings['max_attempts']})…")
        deployer_line(message)
        notify("crash", f"💥 {modpack} se ha caído {when}. Lo vuelvo a arrancar "
                        f"(intento {attempt} de {settings['max_attempts']}).")
        _restart_later(modpack, _RESTART_DELAY_SECONDS, f"Arrancando de nuevo tras la caída (intento {attempt}).")
        return

    if settings["enabled"]:
        deployer_line(f"El servidor se ha caído {when}. Ya van {attempt} caídas en "
                      f"{settings['window_minutes']} min: no se vuelve a arrancar solo.")
        notify("crash", f"💥 {modpack} se ha caído {when}. Ya van {attempt} caídas seguidas, "
                        "así que no lo vuelvo a arrancar. Échale un vistazo a los logs.")
    else:
        deployer_line(f"El servidor se ha caído {when}.")
        notify("crash", f"💥 {modpack} se ha caído {when}.")


def _restart_later(modpack: str, delay: float, message: str) -> None:
    def run():
        time.sleep(delay)
        if is_running():
            return
        try:
            deployer_line(message)
            start_server(modpack, force=True, keep_output=True)
        except PendingModsError:
            pass
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            deployer_line(f"No se pudo arrancar de nuevo: {detail}")
            notify("crash", f"❌ No se pudo volver a arrancar {modpack}: {detail}")

    threading.Thread(target=run, daemon=True, name="reinicio-tras-caida").start()
