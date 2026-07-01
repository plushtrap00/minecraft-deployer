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
import threading
from collections import deque
from pathlib import Path

from config import DEFAULT_SERVERS_PATH, MAX_LOG_LINES

# ── Estado global ──────────────────────────────────────────────────────────────
mc_process = None
mc_process_lock = threading.Lock()

mc_output_lines: deque = deque(maxlen=MAX_LOG_LINES)
mc_output_lock = threading.Lock()

mc_sse_clients: set = set()
mc_sse_lock = threading.Lock()

mc_running_modpack: str | None = None

mc_rcon_host: str | None = None
mc_rcon_port: int | None = None
mc_rcon_password: str | None = None
mc_rcon_conn = None  # services.rcon.RconConnection, creada al arrancar el servidor
mc_modloader: str | None = None


# ── Apagado de la app ──────────────────────────────────────────────────────────
def notify_app_shutdown():
    """
    Empuja un centinela a todas las colas SSE conectadas para desbloquear el
    q.get(timeout=...) al instante, en vez de esperar hasta 15s por cliente
    antes de que la app pueda terminar de cerrarse.
    """
    with mc_sse_lock:
        for q in mc_sse_clients:
            try:
                q.put_nowait("__APP_SHUTDOWN__")
            except Exception:
                pass


# ── Broadcast ──────────────────────────────────────────────────────────────────
def _broadcast(line: str):
    """Añade una línea al buffer de logs y la envía a todos los clientes SSE activos."""
    with mc_output_lock:
        mc_output_lines.append(line)
    with mc_sse_lock:
        dead = set()
        for q in mc_sse_clients:
            try:
                q.put_nowait(line)
            except Exception:
                dead.add(q)
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
        for q in mc_sse_clients:
            try:
                q.put_nowait(line)
                q.put_nowait("__STOPPED__")
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

    global mc_running_modpack

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
        mc_metrics["players_online"] = []
        mc_metrics["tps"] = None
        _notify_stopped()
