"""
routes/auth.py - Autenticación JWT para la app.

Rutas:
- POST /api/auth/login   → valida usuario+contraseña, devuelve JWT con rol
- POST /api/auth/logout  → solo informativo (el cliente descarta el token)
- GET  /api/auth/verify  → comprueba si el token del cliente sigue siendo válido
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from dotenv import load_dotenv
import os

from services.users import authenticate

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_EXPIRE_HOURS = 24 * 7  # 1 semana


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET no configurado en .env")
    return secret


def create_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire},
        get_jwt_secret(),
        algorithm="HS256",
    )


def verify_token(token: str) -> dict | None:
    """Devuelve {"sub": username, "role": role} si el token es válido, si no None."""
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        username = payload.get("sub")
        if username:
            return {"sub": username, "role": payload.get("role", "user")}
    except JWTError:
        pass
    return None


@router.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    role = authenticate(username, password)
    if role is None:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = create_token(username, role)
    return JSONResponse({"token": token, "role": role, "expires_in_hours": TOKEN_EXPIRE_HOURS})


@router.post("/logout")
async def logout():
    return JSONResponse({"success": True})


@router.get("/verify")
async def verify(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    info = verify_token(token)
    if not info:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return JSONResponse({"valid": True, "user": info["sub"], "role": info["role"]})
