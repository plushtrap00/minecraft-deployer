"""
routes/users.py - Gestión de usuarios (solo admin).

Rutas:
- GET    /api/users           → lista todos los usuarios
- POST   /api/users           → crea un usuario normal
- DELETE /api/users/{username}→ elimina un usuario normal
"""
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.users import list_users, create_user, delete_user

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,16}$')
_PRINTABLE_RE = re.compile(r'^[\x20-\x7E]+$')

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
    username = body.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Nombre de usuario inválido: solo letras, números, _ y - (máx. 16 caracteres)")
    if len(body.password) < 3 or not _PRINTABLE_RE.match(body.password):
        raise HTTPException(status_code=400, detail="Contraseña inválida: mínimo 3 caracteres, sin emojis ni símbolos raros")
    try:
        user = create_user(username, body.password)
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
