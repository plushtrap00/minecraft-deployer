"""
routes/system.py - Endpoints generales del sistema.

Rutas:
- GET  /                        → sirve index.html
- GET  /api/system-info         → RAM total del sistema
- GET  /api/disk-usage          → uso de disco
- GET  /api/modpacks            → lista de modpacks con metadata
"""
import shutil
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from config import DEFAULT_SERVERS_PATH, MC_DOMAIN
from services.utils import get_system_ram_gb, get_modpacks
from services.modpack import detect_modpack_version

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


@router.get("/api/system-stats")
async def system_stats():
    """
    Estadísticas completas del sistema en tiempo real via psutil.
    Incluye CPU, RAM, swap, temperaturas, discos, red y top procesos.
    """
    import psutil, time, traceback
    try:
        return await _system_stats_inner()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error leyendo stats del sistema: {e}")


async def _system_stats_inner():
    import psutil, time

    # CPU
    cpu_total = psutil.cpu_percent(interval=0.3)
    cpu_cores = psutil.cpu_percent(interval=0.3, percpu=True)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_count_phys = psutil.cpu_count(logical=False)
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = round(cpu_freq.current) if cpu_freq else None
    except Exception:
        cpu_freq_mhz = None

    # RAM
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Temperaturas
    temps_out = {}
    try:
        temps = psutil.sensors_temperatures()
        for chip, entries in temps.items():
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

    # Red
    net = psutil.net_io_counters()

    # Top 8 procesos por RAM
    top_procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            top_procs.append(p.info)
        except Exception:
            pass
    top_procs = sorted(top_procs, key=lambda x: x.get("memory_percent") or 0, reverse=True)[:8]

    return JSONResponse({
        "cpu": {
            "total_percent": cpu_total,
            "cores": cpu_cores,
            "logical_count": cpu_count,
            "physical_count": cpu_count_phys,
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
        "temps": temps_out,
        "disks": disks,
        "net": {
            "sent_mb": round(net.bytes_sent / 1024**2, 1),
            "recv_mb": round(net.bytes_recv / 1024**2, 1),
        },
        "top_procs": top_procs,
    })
