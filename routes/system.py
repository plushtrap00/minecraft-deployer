"""
routes/system.py - Endpoints generales del sistema.

Rutas:
- GET  /                        → sirve index.html
- GET  /api/system-info         → RAM total del sistema
- GET  /api/disk-usage          → uso de disco
- GET  /api/modpacks            → lista de modpacks con metadata
- GET  /api/modpacks/{name}/size → tamaño en disco de un modpack (cacheado)
- GET  /api/system-stats        → estadísticas del sistema (snapshot único)
- GET  /api/system-stats/stream → SSE: estadísticas del sistema cada ~3s
- GET  /api/auto-update/status  → estado de la auto-actualización
- POST /api/auto-update/check   → fuerza una comprobación inmediata contra GitHub
- POST /api/auto-update/apply   → aplica el pull pendiente y reinicia la app
"""
import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from config import DEFAULT_SERVERS_PATH, MC_DOMAIN
from services.utils import get_system_ram_gb, get_modpacks
from services.modpack import detect_modpack_version
from services.pending_mods import get_pending_mods
from services import auto_update
from services.frontend import render_index
from services.visuals import pack_icon_path, image_type
from routes.deps import modpack_path
from version import APP_VERSION
from routes.auth import require_admin
from app_constants import MAX_UPLOAD_MB

router = APIRouter()


# Cada CSS/JS se pide con ?v=<fecha de modificación de ese archivo>. Con esa
# versión en la URL el navegador lo guarda sin volver a preguntar (ver
# main.py), y en cuanto el archivo cambia la URL es otra y se pide de nuevo.
# Antes la versión era la hora de arranque del proceso: tras un git pull sin
# reiniciar el panel, el navegador seguía usando los archivos viejos de su
# caché aunque en disco ya estuvieran los nuevos.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_STATIC_ASSET_RE = re.compile(r'(href|src)="/static/([^"?]+)"')
_PROCESS_START = str(int(time.time()))


def _asset_version(rel_path: str) -> str:
    try:
        return str((_STATIC_DIR / rel_path).stat().st_mtime_ns)
    except OSError:
        return _PROCESS_START


def _versioned_asset(match: re.Match) -> str:
    attr, rel_path = match.group(1), match.group(2)
    return f'{attr}="/static/{rel_path}?v={_asset_version(rel_path)}"'


@router.get("/", response_class=HTMLResponse)
def index():
    html = _STATIC_ASSET_RE.sub(_versioned_asset, render_index())
    # Datos que el JavaScript necesita desde el primer momento (antes incluso
    # de iniciar sesión), sin una petición aparte.
    meta = (
        f'<meta name="app-version" content="{APP_VERSION}">\n'
        f'<meta name="max-upload-mb" content="{int(MAX_UPLOAD_MB)}">\n'
    )
    html = html.replace("</head>", meta + "</head>", 1)
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/api/system-info")
def system_info():
    ram_gb = get_system_ram_gb()
    max_allowed = round(ram_gb * 0.8, 1) if ram_gb else None
    return JSONResponse({
        "ram_total_gb": ram_gb,
        "ram_max_allowed_gb": max_allowed,
        "mc_domain": MC_DOMAIN,
    })


@router.get("/api/disk-usage")
def disk_usage():
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
def list_modpacks():
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
            "pending_mods": get_pending_mods(name),
            "mods_count": _count_enabled_mods(path),
            "last_played": _last_played(path),
            "has_icon": pack_icon_path(path) is not None,
        })
    return JSONResponse({"modpacks": result})



@router.get("/api/modpacks/{modpack}/icon")
def modpack_icon(modpack: str):
    """Logo del modpack (server-icon.png o el de la tienda). 404 si no tiene:
    el panel dibuja entonces un bloque con los colores del nombre."""
    icon = pack_icon_path(modpack_path(modpack))
    data = icon.read_bytes() if icon else b""
    kind = image_type(data)
    if not kind:
        raise HTTPException(status_code=404, detail="Este modpack no tiene logo")
    return Response(data, media_type=kind[0], headers={"Cache-Control": "private, max-age=3600"})

def _count_enabled_mods(path: Path) -> int | None:
    mods_dir = path / "mods"
    if not mods_dir.is_dir():
        return None
    return sum(1 for f in mods_dir.iterdir() if f.suffix == ".jar")


def _last_played(path: Path) -> float | None:
    """Última vez que arrancó el servidor: Minecraft reescribe logs/latest.log
    en cada arranque y mientras está en marcha, así que su fecha sirve sin
    tener que guardar nada aparte."""
    latest = path / "logs" / "latest.log"
    try:
        return latest.stat().st_mtime
    except OSError:
        return None


# El tamaño de un modpack con mundos grandes puede tardar segundos en
# calcularse (miles de archivos), así que va en su propio endpoint -- la
# lista se pinta sin esperarlo -- y se cachea unos minutos por modpack.
_SIZE_CACHE_TTL_SECONDS = 300
_size_cache: dict[str, tuple[float, int]] = {}


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


@router.get("/api/modpacks/{name}/size")
async def modpack_size(name: str):
    if name not in get_modpacks():
        raise HTTPException(status_code=404, detail="Modpack no encontrado")
    cached = _size_cache.get(name)
    if cached and time.time() - cached[0] < _SIZE_CACHE_TTL_SECONDS:
        size = cached[1]
    else:
        size = await asyncio.to_thread(_dir_size_bytes, DEFAULT_SERVERS_PATH / name)
        _size_cache[name] = (time.time(), size)
    return JSONResponse({"size_bytes": size})


@router.get("/api/auto-update/status")
def auto_update_status():
    return JSONResponse(auto_update.get_status())


@router.post("/api/auto-update/check")
async def auto_update_check():
    """Fuerza una comprobación inmediata contra GitHub (botón "Comprobar ahora")."""
    import asyncio
    try:
        status = await asyncio.to_thread(auto_update.check_now)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo comprobar: {e}")
    return JSONResponse(status)


@router.post("/api/auto-update/apply")
async def auto_update_apply(request: Request):
    # git pull + reinicio de la app: acción de administración, como reiniciar
    # desde Configuración. Comprobar si hay versión nueva sí puede cualquiera.
    require_admin(request)
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
def system_stats_stream():
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
