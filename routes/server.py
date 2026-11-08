"""
routes/server.py - Endpoints de control del servidor Minecraft.

Rutas:
- GET  /api/server/status          → estado del servidor (running, modpack)
- POST /api/server/start           → arrancar servidor
- POST /api/server/stop            → parar servidor
- POST /api/server/restart         → parar y volver a arrancar el mismo
- GET  /api/server/history         → historial de TPS, jugadores y RAM (24 h / 7 días)
- POST /api/server/command         → enviar comando a la consola
- GET  /api/server/metrics         → métricas actuales (TPS, RAM, jugadores...)
- POST /api/server/metrics/refresh → refrescar métricas (list, forge/neoforge tps por RCON)
- GET  /api/server/logs            → SSE stream de logs en tiempo real
"""
import asyncio
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services import process as proc_module
from services.process import mc_process_lock, mc_output_lines, mc_output_lock, mc_sse_clients, mc_sse_lock
from services import metrics as metrics_module
from services.metrics import mc_metrics, read_proc_ram
from services import server_control, history
from routes.deps import modpack_path

router = APIRouter(prefix="/api/server", tags=["server"])


@router.get("/status")
def server_status():
    with mc_process_lock:
        proc = proc_module.mc_process
        running = proc is not None and proc.poll() is None
    return JSONResponse({
        "running": running,
        "modpack": proc_module.mc_running_modpack if running else None,
        "ready": running and proc_module.mc_ready,
    })


@router.post("/start")
def server_start(modpack: str = Form(...), force: str = Form("0")):
    try:
        server_control.start_server(modpack, force=(force == "1"))
    except server_control.PendingModsError as e:
        # Mods bloqueados por su autor para descarga por terceros: se avisa
        # antes de arrancar, pero se puede forzar (force=1).
        return JSONResponse(status_code=409, content={
            "detail": (
                f"Este modpack dio error al descargar estos mods: {', '.join(e.pending)}. "
                "Instálalos manualmente en Gestionar → Mods → importar carpeta/mods uno a uno."
            ),
            "pending_mods": e.pending,
        })
    return JSONResponse({"success": True, "modpack": modpack})


@router.post("/stop")
async def server_stop():
    graceful = await asyncio.to_thread(server_control.stop_server)
    return JSONResponse({"success": True, "graceful": graceful})


@router.post("/restart")
async def server_restart():
    modpack = await asyncio.to_thread(server_control.restart_server)
    return JSONResponse({"success": True, "modpack": modpack})


@router.post("/command")
def server_command(cmd: str = Form(...)):
    server_control.send_command(cmd)
    return JSONResponse({"success": True})


@router.get("/history")
def server_history(modpack: str, hours: int = 24):
    modpack_path(modpack)
    hours = max(1, min(hours, history.MAX_HOURS))
    return JSONResponse({"modpack": modpack, "hours": hours, "samples": history.query(modpack, hours)})


@router.get("/metrics")
def get_metrics():
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


@router.post("/metrics/refresh")
async def refresh_metrics():
    """Refresca métricas (list, tps) por RCON, y lee RAM desde /proc."""
    if not await asyncio.to_thread(server_control.refresh_metrics):
        raise HTTPException(status_code=400, detail="Servidor no activo")
    return JSONResponse({"success": True})


@router.get("/logs")
def server_logs():
    """SSE endpoint: envía el historial de logs y luego hace streaming de nuevas líneas."""

    async def event_stream():
        client = (asyncio.get_running_loop(), asyncio.Queue())
        with mc_sse_lock:
            mc_sse_clients.add(client)
        with mc_output_lock:
            history = list(mc_output_lines)
        try:
            for line in history:
                yield "data: " + line + "\n\n"
            while True:
                try:
                    line = await asyncio.wait_for(client[1].get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if line == "__APP_SHUTDOWN__":
                    break
                yield "data: " + line + "\n\n"
                if line == "__STOPPED__":
                    break
        finally:
            with mc_sse_lock:
                mc_sse_clients.discard(client)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
