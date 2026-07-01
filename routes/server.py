"""
routes/server.py - Endpoints de control del servidor Minecraft.

Rutas:
- GET  /api/server/status          → estado del servidor (running, modpack)
- POST /api/server/start           → arrancar servidor
- POST /api/server/stop            → parar servidor
- POST /api/server/command         → enviar comando a la consola
- GET  /api/server/metrics         → métricas actuales (TPS, RAM, jugadores...)
- POST /api/server/metrics/refresh → refrescar métricas (list, forge/neoforge tps por RCON)
- GET  /api/server/logs            → SSE stream de logs en tiempo real
"""
import os
import re
import stat
import asyncio
import tempfile
import threading
import subprocess
from pathlib import Path
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import DEFAULT_SERVERS_PATH
from services import process as proc_module
from services.process import (
    mc_process, mc_process_lock, mc_output_lines, mc_output_lock,
    mc_sse_clients, mc_sse_lock, _reader_thread,
)
from services import metrics as metrics_module
from services.metrics import mc_metrics, read_proc_ram, _parse_metrics_line
from services.modpack import ensure_rcon_enabled, detect_modpack_version
from services.rcon import RconConnection, RconError
import datetime

router = APIRouter(prefix="/api/server", tags=["server"])


@router.get("/status")
async def server_status():
    with mc_process_lock:
        proc = proc_module.mc_process
        running = proc is not None and proc.poll() is None
    return JSONResponse({
        "running": running,
        "modpack": proc_module.mc_running_modpack if running else None,
    })


@router.post("/start")
async def server_start(modpack: str = Form(...)):
    with mc_process_lock:
        if proc_module.mc_process is not None and proc_module.mc_process.poll() is None:
            raise HTTPException(status_code=400, detail="Ya hay un servidor en marcha")

        server_dir = DEFAULT_SERVERS_PATH / modpack
        script = next(
            (server_dir / s for s in ["startserver.sh", "start.sh", "run.sh"] if (server_dir / s).exists()),
            None
        )
        if script is None:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontró script de arranque (startserver.sh / start.sh / run.sh) en {server_dir}"
            )

        # Parchear RESTART=true → false para evitar bucles de reinicio
        script_content = script.read_bytes()
        script_content = re.sub(
            rb'(?m)^(\s*RESTART\s*=\s*)["\']?true["\']?',
            rb'\1false',
            script_content
        )
        # Escribir script parcheado en archivo temporal
        tmp = tempfile.NamedTemporaryFile(mode='wb', suffix='.sh', dir=str(server_dir), delete=False)
        tmp.write(script_content)
        tmp.close()
        patched_script = tmp.name
        os.chmod(patched_script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)

        with mc_output_lock:
            mc_output_lines.clear()

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

        t = threading.Thread(target=_reader_thread, args=(proc, patched_script), daemon=True)
        t.start()

    return JSONResponse({"success": True, "modpack": modpack})


@router.post("/stop")
async def server_stop():
    with mc_process_lock:
        proc = proc_module.mc_process
        if proc is None or proc.poll() is not None:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return JSONResponse({"success": True})


@router.post("/command")
async def server_command(cmd: str = Form(...)):
    with mc_process_lock:
        proc = proc_module.mc_process
        if proc is None or proc.poll() is not None:
            raise HTTPException(status_code=400, detail="No hay servidor en marcha")
        try:
            proc.stdin.write((cmd.strip() + "\n").encode("utf-8"))
            proc.stdin.flush()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"success": True})


@router.get("/metrics")
async def get_metrics():
    import datetime as dt
    uptime = None
    if metrics_module.mc_start_time:
        uptime = int((dt.datetime.utcnow() - metrics_module.mc_start_time).total_seconds())

    with mc_process_lock:
        proc = proc_module.mc_process

    if proc is not None and proc.poll() is None:
        read_proc_ram(proc.pid)

    return JSONResponse({
        **mc_metrics,
        "running": proc is not None and proc.poll() is None,
        "uptime_seconds": uptime,
    })


# El comando propio del modloader responde bien por RCON (a diferencia de
# "spark tps", que devuelve respuesta vacía por RCON: bug conocido en
# https://github.com/lucko/spark/issues/119).
TPS_COMMANDS_BY_LOADER = {
    "NeoForge": ["neoforge tps", "forge tps"],
    "Forge": ["forge tps"],
}


def _refresh_via_rcon(conn: RconConnection, modloader: str | None):
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


@router.post("/metrics/refresh")
async def refresh_metrics():
    """Refresca métricas (list, tps) por RCON, y lee RAM desde /proc."""
    with mc_process_lock:
        proc = proc_module.mc_process
        if proc is None or proc.poll() is not None:
            raise HTTPException(status_code=400, detail="Servidor no activo")
        conn = proc_module.mc_rcon_conn
        modloader = proc_module.mc_modloader

    if conn is not None:
        await asyncio.to_thread(_refresh_via_rcon, conn, modloader)
    else:
        mc_metrics["rcon_status"] = "no configurado (reinicia el servidor desde el panel)"
    read_proc_ram(proc.pid)
    return JSONResponse({"success": True})


@router.get("/logs")
async def server_logs():
    """SSE endpoint: envía el historial de logs y luego hace streaming de nuevas líneas."""
    import queue

    q = queue.Queue()
    with mc_sse_lock:
        mc_sse_clients.add(q)

    with mc_output_lock:
        history = list(mc_output_lines)

    async def event_stream():
        try:
            for line in history:
                yield "data: " + line + "\n\n"
            loop = asyncio.get_event_loop()
            while True:
                try:
                    line = await loop.run_in_executor(None, lambda: q.get(timeout=15))
                    yield "data: " + line + "\n\n"
                    if line == "__STOPPED__":
                        break
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            with mc_sse_lock:
                mc_sse_clients.discard(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
