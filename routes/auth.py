"""
routes/auth.py - Autenticación JWT para la app.

Rutas:
- POST /api/auth/login   → valida usuario+contraseña, devuelve JWT
- POST /api/auth/logout  → solo informativo (el cliente descarta el token)
- GET  /api/auth/verify  → comprueba si el token del cliente sigue siendo válido
"""
import os
import bcrypt
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_EXPIRE_HOURS = 24 * 7  # 1 semana


def get_app_username() -> str:
    return os.getenv("APP_USERNAME", "pablo")


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET no configurado en .env")
    return secret


def get_password_hash() -> str:
    # APP_PASSWORD_HASH es el nombre actual; PABLO_PASSWORD_HASH se mantiene por compatibilidad
    h = os.getenv("APP_PASSWORD_HASH") or os.getenv("PABLO_PASSWORD_HASH")
    if not h:
        raise HTTPException(
            status_code=500,
            detail="APP_PASSWORD_HASH no configurado. Ejecuta: python3 setup.py"
        )
    return h


def create_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": get_app_username(), "exp": expire}, get_jwt_secret(), algorithm="HS256")


def verify_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload.get("sub") == get_app_username()
    except JWTError:
        return False


@router.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username != get_app_username():
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    stored_hash = get_password_hash()
    if not bcrypt.checkpw(password.encode(), stored_hash.encode()):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = create_token()
    return JSONResponse({"token": token, "expires_in_hours": TOKEN_EXPIRE_HOURS})


@router.post("/logout")
async def logout():
    return JSONResponse({"success": True})


@router.get("/verify")
async def verify(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return JSONResponse({"valid": True, "user": get_app_username()})
