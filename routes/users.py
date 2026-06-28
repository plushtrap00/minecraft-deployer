"""
routes/users.py - Gestión de usuarios (solo admin).

Rutas:
- GET    /api/users           → lista todos los usuarios
- POST   /api/users           → crea un usuario normal
- DELETE /api/users/{username}→ elimina un usuario normal
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.users import list_users, create_user, delete_user

router = APIRouter(prefix="/api/users", tags=["users"])


def _require_admin(request: Request) -> None:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador")


class CreateUserBody(BaseModel):
    username: str
    password: str


@router.get("")
async def get_users(request: Request):
    _require_admin(request)
    return JSONResponse(list_users())


@router.post("", status_code=201)
async def add_user(request: Request, body: CreateUserBody):
    _require_admin(request)
    if not body.username.strip() or not body.password:
        raise HTTPException(status_code=400, detail="Usuario y contraseña son requeridos")
    try:
        user = create_user(body.username.strip(), body.password)
        return JSONResponse(user, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{username}")
async def remove_user(username: str, request: Request):
    _require_admin(request)
    try:
        found = delete_user(username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return JSONResponse({"success": True})
