"""
routes/automation.py - Reinicio automático, copias automáticas y tareas
programadas (services/automation.py, services/scheduler.py).

Rutas:
- GET    /api/automation                 → ajustes, tareas, estado y hora del servidor
- POST   /api/automation/settings        → guarda reinicio automático, copias automáticas y apagado sin jugadores
- POST   /api/automation/tasks           → crea o actualiza una tarea
- DELETE /api/automation/tasks/{id}      → borra una tarea
- POST   /api/automation/tasks/{id}/run  → ejecuta una tarea ahora (para probarla)
- POST   /api/automation/backup-mirror   → destino secundario de las copias (solo admin)
"""
from datetime import datetime

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routes.auth import require_admin
from services import automation, backups, scheduler
from services.utils import get_modpacks

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.get("")
def get_automation():
    data = automation.load()
    return JSONResponse({
        **data,
        "task_status": scheduler.task_status(),
        "task_kinds": automation.TASK_KINDS,
        "server_time": datetime.now().strftime("%H:%M"),
        "modpacks": get_modpacks(),
        "mirror": backups.mirror_status(),
    })


class MirrorBody(BaseModel):
    path: str = ""


@router.post("/backup-mirror")
async def set_backup_mirror(request: Request, body: MirrorBody):
    """Elige (o quita, con path vacío) la carpeta donde se duplican todas las copias."""
    require_admin(request)
    try:
        value = await asyncio.to_thread(backups.validate_mirror_dir, body.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    automation.set_mirror_dir(value)
    if value:
        # Las copias que ya había se llevan también, en segundo plano.
        backups.sync_mirror_in_background()
    return JSONResponse({"success": True, "mirror": backups.mirror_status()})


class SettingsBody(BaseModel):
    auto_restart: dict | None = None
    backups: dict | None = None
    idle_stop: dict | None = None


@router.post("/settings")
def save_settings(body: SettingsBody):
    return JSONResponse(automation.save_settings(body.auto_restart, body.backups, body.idle_stop))


@router.post("/tasks")
def save_task(task: dict):
    try:
        saved = automation.save_task(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(saved)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    if not automation.delete_task(task_id):
        raise HTTPException(status_code=404, detail="La tarea no existe")
    return JSONResponse({"success": True})


@router.post("/tasks/{task_id}/run")
def run_task_now(task_id: str):
    task = next((t for t in automation.load()["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="La tarea no existe")
    scheduler.run_task_in_background(task)
    return JSONResponse({"success": True, "message": "Tarea en marcha: " + scheduler.describe_task(task)})
