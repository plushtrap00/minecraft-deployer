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

from services.users import list_users, create_user, delete_user, set_password, validate_password
from routes.auth import require_admin as _require_admin

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,16}$')

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserBody(BaseModel):
    username: str
    password: str


@router.get("")
def get_users(request: Request):
    _require_admin(request)
    return JSONResponse(list_users())


@router.post("", status_code=201)
def add_user(request: Request, body: CreateUserBody):
    _require_admin(request)
    username = body.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Nombre de usuario inválido: solo letras, números, _ y - (máx. 16 caracteres)")
    try:
        validate_password(body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        user = create_user(username, body.password)
        return JSONResponse(user, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


class ResetPasswordBody(BaseModel):
    password: str


@router.post("/{username}/password")
def reset_user_password(username: str, request: Request, body: ResetPasswordBody):
    """El admin pone una contraseña nueva a otro usuario (sin borrarlo y crearlo de nuevo). Cierra sus sesiones."""
    _require_admin(request)
    if username == request.state.user:
        raise HTTPException(status_code=400, detail="Para tu propia contraseña usa «Cambiar contraseña» en el menú de tu usuario")
    try:
        set_password(username, body.password)
    except KeyError:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"success": True})


@router.delete("/{username}")
def remove_user(username: str, request: Request):
    _require_admin(request)
    try:
        found = delete_user(username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return JSONResponse({"success": True})
