"""
routes/auth.py - Autenticación JWT para la app.

Rutas:
- POST /api/auth/login   → valida usuario+contraseña, devuelve JWT con rol
- POST /api/auth/logout  → solo informativo (el cliente descarta el token)
- GET  /api/auth/verify  → comprueba si el token del cliente sigue siendo válido
"""
import time
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

# ── Bloqueo temporal tras intentos fallidos de login ───────────────────────────
# En memoria (se resetea si el proceso reinicia, igual que el resto del estado
# de esta app); alcanza para frenar fuerza bruta contra un panel de homelab
# sin sumar una dependencia nueva solo para esto.
_MAX_FAILED_ATTEMPTS = 5
_ATTEMPT_WINDOW_SECONDS = 5 * 60   # ventana en la que cuentan los fallos
_LOCKOUT_SECONDS = 5 * 60          # cuánto dura el bloqueo al superar el máximo

_failed_attempts: dict[str, list[float]] = {}  # clave "ip:usuario" -> timestamps de fallos


def _login_attempt_key(request: Request, username: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{username.strip().lower()}"


def _seconds_locked_out(key: str) -> int | None:
    """Devuelve segundos restantes de bloqueo, o None si no está bloqueado. De paso descarta intentos ya fuera de la ventana."""
    now = time.time()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < _ATTEMPT_WINDOW_SECONDS]
    _failed_attempts[key] = attempts
    if len(attempts) < _MAX_FAILED_ATTEMPTS:
        return None
    trigger = attempts[-_MAX_FAILED_ATTEMPTS]  # el intento que hizo superar el máximo
    remaining = _LOCKOUT_SECONDS - (now - trigger)
    return int(remaining) if remaining > 0 else None


def _register_failed_attempt(key: str) -> None:
    _failed_attempts.setdefault(key, []).append(time.time())


def _clear_failed_attempts(key: str) -> None:
    _failed_attempts.pop(key, None)


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


def require_admin(request: Request) -> None:
    """Corta con 403 si el usuario autenticado no tiene rol admin (gestión de
    usuarios y firewall; el resto de acciones del panel son accesibles para
    cualquier cuenta autenticada)."""
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador")


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    key = _login_attempt_key(request, username)
    locked_seconds = _seconds_locked_out(key)
    if locked_seconds is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Probá de nuevo en {locked_seconds} segundos.",
        )

    role = authenticate(username, password)
    if role is None:
        _register_failed_attempt(key)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    _clear_failed_attempts(key)
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
