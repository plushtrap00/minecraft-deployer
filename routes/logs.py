"""
routes/logs.py - Logs y crash reports de un modpack.

Rutas:
- GET       /api/modpacks/{modpack}/logs
- GET       /api/modpacks/{modpack}/logs/{filename}
- GET       /api/modpacks/{modpack}/logs/{filename}/download
"""
import re
import gzip
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse

from config import DEFAULT_SERVERS_PATH
from services.modpack import prune_old_logs_and_crashes
from services.crash_analysis import analyze_crash

from routes.deps import valid_modpack


router = APIRouter(prefix="/api/modpacks", tags=["logs"], dependencies=[Depends(valid_modpack)])


# ── Logs & crash reports ───────────────────────────────────────────────────────

# "crash-2024-01-15_10.23.45-server.txt" -> fecha/hora legible para el frontend.
# Los logs rotados (debug-N.log.gz) no llevan fecha en el nombre, así que solo
# los crash reports obtienen este campo.
_CRASH_FILENAME_RE = re.compile(r'^crash-(\d{4})-(\d{2})-(\d{2})_(\d{2})\.(\d{2})\.(\d{2})')


def _parse_crash_timestamp(filename: str) -> str | None:
    m = _CRASH_FILENAME_RE.match(filename)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def _find_log_or_crash_path(base: Path, filename: str) -> Path | None:
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=403, detail="Nombre de archivo inválido")
    return next(
        (c for c in [base / "logs" / filename, base / "crash-reports" / filename] if c.exists()),
        None
    )


@router.get("/{modpack}/logs")
async def get_log_list(modpack: str):
    base = DEFAULT_SERVERS_PATH / modpack
    await asyncio.to_thread(prune_old_logs_and_crashes, modpack)
    logs = []
    logs_dir = base / "logs"
    if logs_dir.exists():
        files = sorted(
            (f for f in logs_dir.iterdir() if f.is_file() and f.suffix in {".log", ".gz", ".txt"}),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        for f in files:
            logs.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "type": "log"})
    crashes = []
    crash_dir = base / "crash-reports"
    if crash_dir.exists():
        files = sorted(
            (f for f in crash_dir.iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        for f in files:
            crashes.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "type": "crash",
                "timestamp": _parse_crash_timestamp(f.name),
            })
    return JSONResponse({"logs": logs[:20], "crashes": crashes[:30]})


@router.get("/{modpack}/logs/{filename}")
async def get_log_file(modpack: str, filename: str):
    base = DEFAULT_SERVERS_PATH / modpack
    file_path = _find_log_or_crash_path(base, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if filename.endswith(".gz"):
        def _read_gz():
            with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
                return f.read()
        raw = await asyncio.to_thread(_read_gz)
    else:
        raw = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="replace")
    # analyze_crash() solo tiene sentido (y solo es fiable) para crash reports
    # de verdad — llamarlo sobre un log normal daba falsos positivos, porque
    # cualquier mod instalado tiende a mencionarse en algún punto de un log
    # de arranque sin que tenga nada que ver con ningún fallo.
    crash_info = analyze_crash(raw, modpack) if file_path.parent.name == "crash-reports" else None
    return JSONResponse({"content": raw, "crash_info": crash_info, "filename": filename})


@router.get("/{modpack}/logs/{filename}/download")
def download_log_file(modpack: str, filename: str):
    """Descarga el archivo crudo (los .gz se descargan comprimidos tal cual) — compensa que el visor esté paginado."""
    base = DEFAULT_SERVERS_PATH / modpack
    file_path = _find_log_or_crash_path(base, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=filename, media_type="application/octet-stream")
