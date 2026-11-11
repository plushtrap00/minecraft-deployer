"""
services/process.py - Estado del proceso Minecraft y gestión del ciclo de vida.

Contiene:
- Estado global del proceso (mc_process, locks, buffer de logs)
- Estado de conexión RCON del proceso activo (mc_rcon_host, mc_rcon_port, mc_rcon_password)
- _broadcast(): fanout a SSE clients
- _accept_eula(): aceptar EULA automáticamente
- _reader_thread(): lee stdout del proceso y alimenta SSE + métricas
- _notify_stopped(): notifica a clientes que el servidor paró
- notify_app_shutdown(): desbloquea las colas SSE para que la app pueda salir rápido
"""
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from app_constants import MAX_LOG_LINES

# ── Estado global ──────────────────────────────────────────────────────────────
mc_process = None
mc_process_lock = threading.Lock()

mc_output_lines: deque = deque(maxlen=MAX_LOG_LINES)
mc_output_lock = threading.Lock()

# Cada cliente de la consola en directo es un par (event loop, asyncio.Queue).
# Las líneas llegan desde el hilo lector del proceso, así que se meten en la
# cola con call_soon_threadsafe. Antes cada cliente era un queue.Queue que el
# endpoint esperaba con run_in_executor: cada pestaña abierta ocupaba un hilo
# del pool que comparten todos los asyncio.to_thread del panel.
mc_sse_clients: set = set()
mc_sse_lock = threading.Lock()


def _send_to_client(client, line: str) -> bool:
    """Encola una línea para un cliente SSE. False si su event loop ya no existe."""
    loop, queue = client
    try:
        loop.call_soon_threadsafe(queue.put_nowait, line)
        return True
    except RuntimeError:
        return False

mc_running_modpack: str | None = None

mc_rcon_host: str | None = None
mc_rcon_port: int | None = None
mc_rcon_password: str | None = None
mc_rcon_conn = None  # services.rcon.RconConnection, creada al arrancar el servidor
mc_modloader: str | None = None

# True desde que el servidor escribe «Done (12.3s)! For help, type "help"»:
# antes de eso el proceso existe pero todavía está cargando mods o el mundo.
mc_ready = False
mc_ready_since: float | None = None  # time.time() del «Done»
_DONE_LINE_RE = re.compile(r'\]: Done \(\d')

# Para distinguir una caída de una parada normal: el panel marca
# mc_stop_requested antes de pedir «stop», y si alguien escribe «stop» en la
# consola Minecraft avisa con «Stopping the server». Si el proceso termina sin
# ninguna de las dos cosas, se ha caído (services/server_control.py decide si
# vuelve a arrancarlo).
mc_stop_requested = False
_STOPPING_RE = re.compile(r'\]: Stopping (the )?server', re.IGNORECASE)

# Esperas de líneas concretas de la consola (p. ej. «Saved the game» tras un
# save-all antes de una copia): expect_line() registra una y el hilo lector la
# despierta al ver la línea.
_line_waiters: list = []
_line_waiters_lock = threading.Lock()


class LineWaiter:
    def __init__(self, pattern: str):
        self.regex = re.compile(pattern, re.IGNORECASE)
        self.event = threading.Event()
        self.line = None

    def wait(self, timeout: float) -> bool:
        try:
            return self.event.wait(timeout)
        finally:
            with _line_waiters_lock:
                if self in _line_waiters:
                    _line_waiters.remove(self)


def expect_line(pattern: str) -> LineWaiter:
    """Registra la espera ANTES de mandar el comando, para no perder la respuesta."""
    waiter = LineWaiter(pattern)
    with _line_waiters_lock:
        _line_waiters.append(waiter)
    return waiter


def _check_line_waiters(line: str) -> None:
    with _line_waiters_lock:
        for waiter in list(_line_waiters):
            if waiter.regex.search(line):
                waiter.line = line
                waiter.event.set()
                _line_waiters.remove(waiter)


# ── Espera de apagado limpio ───────────────────────────────────────────────────
def wait_process_exit(proc, timeout_seconds: float) -> bool:
    """
    Sondea proc.poll() hasta que el proceso termine o se acabe el timeout.
    Pensado para llamarse en un hilo aparte (via asyncio.to_thread) tras pedir
    un apagado limpio, para no bloquear el event loop mientras se espera.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.5)
    return proc.poll() is not None


def _child_pids(pid: int) -> list:
    try:
        result = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True)
        return [int(p) for p in result.stdout.split() if p.strip().isdigit()]
    except Exception:
        return []


def find_java_descendant_pid(root_pid: int) -> int | None:
    """
    El .sh de arranque puede envolver a java con varios niveles de procesos
    intermedios (y, en algunos scripts de la comunidad, con un bucle propio
    que vuelve a lanzar java pasados unos segundos si no detecta un cierre
    "oficial"). Para poder esperar al proceso de Minecraft REAL en vez de al
    wrapper — que si tiene ese bucle nunca termina por sí solo — se recorre
    el árbol de descendientes de root_pid buscando el primero cuyo
    /proc/<pid>/comm sea "java".
    """
    to_check = [root_pid]
    seen = set()
    while to_check:
        pid = to_check.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        for child in _child_pids(pid):
            try:
                comm = Path(f"/proc/{child}/comm").read_text().strip()
            except Exception:
                comm = ""
            if comm == "java":
                return child
            to_check.append(child)
    return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_java_exit(java_pid: int, timeout_seconds: float) -> bool:
    """Igual que wait_process_exit pero para un PID que no es hijo directo de este proceso (no admite .poll())."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_running(java_pid):
            return True
        time.sleep(0.3)
    return not _pid_running(java_pid)


# ── Apagado de la app ──────────────────────────────────────────────────────────
def notify_app_shutdown():
    """
    Empuja un centinela a todas las colas SSE conectadas para desbloquear el
    q.get(timeout=...) al instante, en vez de esperar hasta 15s por cliente
    antes de que la app pueda terminar de cerrarse.
    """
    with mc_sse_lock:
        for client in mc_sse_clients:
            _send_to_client(client, "__APP_SHUTDOWN__")


# ── Broadcast ──────────────────────────────────────────────────────────────────
def _broadcast(line: str):
    """Añade una línea al buffer de logs y la envía a todos los clientes SSE activos."""
    with mc_output_lock:
        mc_output_lines.append(line)
    with mc_sse_lock:
        dead = {client for client in mc_sse_clients if not _send_to_client(client, line)}
        mc_sse_clients.difference_update(dead)


# ── EULA ───────────────────────────────────────────────────────────────────────
def _accept_eula(server_dir: Path) -> bool:
    """Acepta la EULA de Minecraft automáticamente si aún no está aceptada."""
    eula_file = server_dir / "eula.txt"
    if not eula_file.exists():
        return False
    text = eula_file.read_text(encoding="utf-8")
    if "eula=true" in text.lower():
        return False  # ya aceptada
    new_text = text.replace("eula=false", "eula=true").replace("eula=False", "eula=true")
    eula_file.write_text(new_text, encoding="utf-8")
    return True


# ── Notify stopped ─────────────────────────────────────────────────────────────
def _notify_stopped():
    """Limpia el estado global y notifica a los clientes SSE que el servidor paró."""
    global mc_process, mc_running_modpack, mc_rcon_host, mc_rcon_port, mc_rcon_password, mc_rcon_conn, mc_modloader
    with mc_process_lock:
        mc_process = None
        mc_running_modpack = None
        mc_rcon_host = None
        mc_rcon_port = None
        mc_rcon_password = None
        mc_modloader = None
        if mc_rcon_conn is not None:
            mc_rcon_conn.close()
            mc_rcon_conn = None
    line = "\x1b[33m[Deployer] Servidor detenido.\x1b[0m"
    with mc_output_lock:
        mc_output_lines.append(line)
    with mc_sse_lock:
        for client in mc_sse_clients:
            _send_to_client(client, line)
            _send_to_client(client, "__STOPPED__")


# ── Script atascado tras cerrarse Minecraft ────────────────────────────────────
# Algunos scripts de arranque piden una tecla («Press any key to continue») o
# preguntan algo al cerrarse Minecraft. Por stdin les llega lo que escribe el
# panel, que nunca contesta: el script se queda vivo, sin java, y el panel lo
# sigue viendo en marcha (sin avisar de la caída ni reiniciarlo). Este hilo
# vigila el árbol de procesos: si ya hubo java y desaparece, manda un Intro
# (la respuesta por defecto de cualquier pregunta así) y, si al rato sigue sin
# java, cierra el script entero. Un Intro de más no hace daño: como mucho le
# llega a la consola del siguiente java como una línea vacía.
SCRIPT_WATCHDOG_INTERVAL = 2
SCRIPT_NUDGE_EVERY = 8      # segundos sin java entre cada Intro (como mucho 3)
SCRIPT_KILL_AFTER = 60      # segundos sin java hasta cerrar el script


def _script_watchdog(proc, interval: float = SCRIPT_WATCHDOG_INTERVAL,
                     nudge_every: float = SCRIPT_NUDGE_EVERY, kill_after: float = SCRIPT_KILL_AFTER):
    java_seen = False
    gone_since = None
    nudges = 0
    while proc.poll() is None:
        time.sleep(interval)
        if proc.poll() is not None:
            return
        if mc_stop_requested:
            # Lo para stop_server(), que ya espera a java y cierra el grupo.
            gone_since = None
            continue
        if find_java_descendant_pid(proc.pid) is not None:
            java_seen = True
            gone_since = None
            nudges = 0
            continue
        if not java_seen:
            continue  # aún preparando (descargas, instalador...): no se toca
        now = time.monotonic()
        if gone_since is None:
            gone_since = now
            continue
        idle = now - gone_since
        if idle >= kill_after:
            _broadcast("\x1b[33m[Deployer] El script de arranque sigue abierto sin Minecraft; se cierra.\x1b[0m")
            _kill_process_group(proc)
            return
        if nudges < 3 and idle >= nudge_every * (nudges + 1):
            if nudges == 0:
                _broadcast("\x1b[33m[Deployer] Minecraft se ha cerrado pero el script de arranque sigue esperando: se le envía Intro.\x1b[0m")
            nudges += 1
            try:
                with mc_process_lock:
                    proc.stdin.write(b"\n")
                    proc.stdin.flush()
            except Exception:
                pass


def _kill_process_group(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ── Reader thread ──────────────────────────────────────────────────────────────
def _reader_thread(proc, temp_script: str | None = None):
    """
    Hilo que lee stdout+stderr del proceso MC línea a línea.
    - Alimenta el buffer de logs y los clientes SSE via _broadcast()
    - Parsea líneas para actualizar métricas
    - Detecta la pantalla de EULA y la acepta automáticamente
    - Al terminar, elimina el script temporal y notifica a los clientes
    """
    # Import here to avoid circular imports
    from services.metrics import mc_metrics, _parse_metrics_line
    import datetime

    global mc_running_modpack, mc_ready, mc_ready_since, mc_stop_requested
    from services import server_control

    mc_ready = False
    saw_stopping = False
    modpack = mc_running_modpack
    started_at = time.monotonic()
    mc_metrics["players_online"] = []
    mc_metrics["tps"] = None
    mc_metrics["mspt"] = None
    mc_metrics["ram_used_mb"] = None
    mc_metrics["rcon_status"] = None

    # Actualizar start_time en el módulo de métricas
    from services import metrics as _m
    _m.mc_start_time = datetime.datetime.utcnow()

    eula_handled = False
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            _broadcast(line)
            _parse_metrics_line(line)
            _check_line_waiters(line)
            if not mc_ready and _DONE_LINE_RE.search(line):
                mc_ready = True
                mc_ready_since = time.time()
                server_control.on_ready(modpack)
            elif mc_ready:
                server_control.on_line(modpack, line)
            if not saw_stopping and _STOPPING_RE.search(line):
                saw_stopping = True
            if not eula_handled and "you need to agree to the eula" in line.lower():
                eula_handled = True
                server_dir = DEFAULT_SERVERS_PATH / mc_running_modpack
                if _accept_eula(server_dir):
                    _broadcast("\x1b[33m[Deployer] EULA aceptada automáticamente. Reiniciando servidor...\x1b[0m")
    finally:
        proc.wait()
        if temp_script:
            try:
                os.unlink(temp_script)
            except Exception:
                pass
        _m.mc_start_time = None
        was_ready = mc_ready
        mc_ready = False
        mc_ready_since = None
        mc_metrics["players_online"] = []
        mc_metrics["tps"] = None
        requested = mc_stop_requested
        mc_stop_requested = False
        _notify_stopped()
        server_control.on_exit(
            modpack,
            crashed=not requested and not saw_stopping and not eula_handled,
            eula_accepted=eula_handled,
            was_ready=was_ready,
            uptime_seconds=time.monotonic() - started_at,
        )
