"""
routes/system.py - Endpoints generales del sistema.

Rutas:
- GET  /                        → sirve index.html
- GET  /api/system-info         → RAM total del sistema
- GET  /api/disk-usage          → uso de disco
- GET  /api/modpacks            → lista de modpacks con metadata
- GET  /api/system-stats        → estadísticas del sistema (snapshot único)
- GET  /api/system-stats/stream → SSE: estadísticas del sistema cada ~3s
- GET  /api/auto-update/status  → estado de la auto-actualización
- POST /api/auto-update/apply   → aplica el pull pendiente y reinicia la app
"""
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from config import DEFAULT_SERVERS_PATH, MC_DOMAIN
from services.utils import get_system_ram_gb, get_modpacks
from services.modpack import detect_modpack_version
from services import auto_update

router = APIRouter()


_STATIC_INDEX = Path(__file__).parent.parent / "static" / "index.html"

@router.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=_STATIC_INDEX.read_text(encoding="utf-8"))


@router.get("/api/system-info")
async def system_info():
    ram_gb = get_system_ram_gb()
    max_allowed = round(ram_gb * 0.8, 1) if ram_gb else None
    return JSONResponse({
        "ram_total_gb": ram_gb,
        "ram_max_allowed_gb": max_allowed,
        "mc_domain": MC_DOMAIN,
    })


@router.get("/api/disk-usage")
async def disk_usage():
    try:
        total, used, free = shutil.disk_usage(DEFAULT_SERVERS_PATH)
        gb = 1024 ** 3
        return JSONResponse({
            "total_gb": round(total / gb, 1),
            "used_gb": round(used / gb, 1),
            "free_gb": round(free / gb, 1),
            "percent_used": round((used / total) * 100, 1),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


@router.get("/api/modpacks")
async def list_modpacks():
    packs = get_modpacks()
    result = []
    for name in packs:
        path = DEFAULT_SERVERS_PATH / name
        start_script = next(
            (s for s in ["startserver.sh", "start.sh", "run.sh"] if (path / s).exists()),
            None
        )
        ver = detect_modpack_version(name)
        result.append({
            "name": name,
            "path": str(path),
            "has_server_properties": (path / "server.properties").exists(),
            "has_config": (path / "config").exists(),
            "has_kubejs": (path / "kubejs").exists(),
            "start_script": start_script,
            "mc_version": ver.get("mc_version"),
            "modloader": ver.get("modloader"),
            "modloader_version": ver.get("modloader_version"),
        })
    return JSONResponse({"modpacks": result})


@router.get("/api/auto-update/status")
async def auto_update_status():
    return JSONResponse(auto_update.get_status())


@router.post("/api/auto-update/apply")
async def auto_update_apply():
    import asyncio
    try:
        await asyncio.to_thread(auto_update.apply_update)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    auto_update.schedule_restart()
    return JSONResponse({"success": True, "message": "Actualización aplicada. La app se está reiniciando..."})


@router.get("/api/system-stats")
async def system_stats():
    """
    Estadísticas completas del sistema via psutil (snapshot único).
    Incluye CPU, RAM, swap, temperaturas, discos, red y top procesos.
    """
    import traceback
    try:
        return JSONResponse(await _get_system_stats_full())
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error leyendo stats del sistema: {e}")


@router.get("/api/system-stats/stream")
async def system_stats_stream():
    """
    SSE: empuja cada ~2s solo lo que pinta el panel flotante (CPU total, RAM,
    temperaturas). Se omite a propósito lo que ese panel no usa (cores por
    separado, discos, red, swap, top procesos) para no recalcularlo ni
    mandarlo por la red en cada ciclo.
    """
    import asyncio, json, traceback
    from services.lifecycle import shutdown_event

    async def event_stream():
        while not shutdown_event.is_set():
            try:
                stats = await _get_system_stats_light()
                yield f"data: {json.dumps(stats)}\n\n"
            except Exception as e:
                traceback.print_exc()
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _read_temps_raw() -> dict:
    import psutil
    temps_out = {}
    try:
        for chip, entries in psutil.sensors_temperatures().items():
            temps_out[chip] = [
                {
                    "label": e.label or chip,
                    "current": round(e.current, 1),
                    "high": round(e.high, 1) if e.high else None,
                    "critical": round(e.critical, 1) if e.critical else None,
                }
                for e in entries if e.current is not None
            ]
    except Exception:
        pass
    return temps_out


def _avg_cpu_gpu_temp(temps_raw: dict):
    """
    Reduce el desglose por sensor a dos medias (CPU/GPU), clasificando por
    nombre de chip. Es la misma heurística que antes vivía en sysmon.js.
    """
    cpu_vals = []
    gpu_vals = []
    for chip, entries in temps_raw.items():
        chip_low = chip.lower()
        is_gpu = any(k in chip_low for k in ("gpu", "amdgpu", "radeon", "nouveau", "nvidia"))
        bucket = gpu_vals if is_gpu else cpu_vals
        bucket.extend(e["current"] for e in entries)
    cpu_temp = round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None
    gpu_temp = round(sum(gpu_vals) / len(gpu_vals), 1) if gpu_vals else None
    return cpu_temp, gpu_temp


async def _get_system_stats_light() -> dict:
    """CPU total, RAM y temperatura media CPU/GPU: lo único que renderiza el panel flotante."""
    import psutil, asyncio

    cpu_total = await asyncio.to_thread(psutil.cpu_percent, 0.3)
    mem = psutil.virtual_memory()
    cpu_temp, gpu_temp = _avg_cpu_gpu_temp(_read_temps_raw())

    return {
        "cpu": {"total_percent": cpu_total},
        "ram": {
            "total_gb": round(mem.total / 1024**3, 1),
            "used_gb": round(mem.used / 1024**3, 1),
            "percent": mem.percent,
        },
        "cpu_temp": cpu_temp,
        "gpu_temp": gpu_temp,
    }


async def _get_system_stats_full() -> dict:
    """CPU (total + por core), RAM, swap, temperaturas por sensor, discos, red y top procesos."""
    import psutil, asyncio

    def _read_cpu():
        total = psutil.cpu_percent(interval=0.3)
        cores = psutil.cpu_percent(interval=0.3, percpu=True)
        return total, cores

    cpu_total, cpu_cores = await asyncio.to_thread(_read_cpu)
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = round(cpu_freq.current) if cpu_freq else None
    except Exception:
        cpu_freq_mhz = None

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    stats = {
        "cpu": {
            "total_percent": cpu_total,
            "cores": cpu_cores,
            "logical_count": psutil.cpu_count(logical=True),
            "physical_count": psutil.cpu_count(logical=False),
            "freq_mhz": cpu_freq_mhz,
        },
        "ram": {
            "total_gb": round(mem.total / 1024**3, 1),
            "used_gb": round(mem.used / 1024**3, 1),
            "available_gb": round(mem.available / 1024**3, 1),
            "percent": mem.percent,
        },
        "swap": {
            "total_gb": round(swap.total / 1024**3, 1),
            "used_gb": round(swap.used / 1024**3, 1),
            "percent": swap.percent,
        },
        "temps": _read_temps_raw(),
    }

    # Discos (solo particiones reales)
    disks = []
    for part in psutil.disk_partitions():
        if any(x in part.fstype for x in ["tmpfs", "squash", "devtmpfs", "overlay"]):
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mountpoint": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total_gb": round(u.total / 1024**3, 1),
                "used_gb": round(u.used / 1024**3, 1),
                "free_gb": round(u.free / 1024**3, 1),
                "percent": u.percent,
            })
        except Exception:
            pass
    stats["disks"] = disks

    # Red
    net = psutil.net_io_counters()
    stats["net"] = {
        "sent_mb": round(net.bytes_sent / 1024**2, 1),
        "recv_mb": round(net.bytes_recv / 1024**2, 1),
    }

    # Top 8 procesos por RAM
    top_procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            top_procs.append(p.info)
        except Exception:
            pass
    stats["top_procs"] = sorted(top_procs, key=lambda x: x.get("memory_percent") or 0, reverse=True)[:8]

    return stats
