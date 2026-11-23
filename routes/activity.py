"""
routes/activity.py - Registro de actividad (services/activity.py), solo administrador.

- GET /api/activity?limit=&before=&user=&category= → las acciones más recientes primero
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routes.auth import require_admin
from services import activity

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(request: Request, limit: int = 100, before: float | None = None,
                  user: str | None = None, category: str | None = None):
    require_admin(request)
    limit = max(1, min(limit, 500))
    if category and category not in activity.CATEGORIES:
        category = None
    return JSONResponse(activity.read(limit, before, user, category))
