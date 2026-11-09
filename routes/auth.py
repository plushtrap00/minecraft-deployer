"""
routes/auth.py - Autenticación con tokens JWT (HS256) en una cookie HttpOnly.

Rutas:
- POST /api/auth/login   → valida usuario+contraseña y deja la sesión en la cookie
- POST /api/auth/logout  → borra la cookie
- GET  /api/auth/verify  → comprueba si la sesión del cliente sigue siendo válida

La sesión viaja en una cookie HttpOnly (el JavaScript de la página no puede
leerla) en vez de en localStorage y en ?token= dentro de las URLs, donde
acababa en el historial del navegador y en los logs. SameSite=Strict hace que
el navegador no la mande desde otras webs, así que tampoco sirve para que una
página ajena dispare acciones en el panel.

El token se firma con hmac de la librería estándar: HS256 son unas pocas
líneas y así no hace falta python-jose, que ya no se mantiene.
"""
import base64
import hashlib
import hmac
import json
import math
import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from services.users import authenticate, password_fingerprint, role_of, set_password, verify_password
from app_constants import (
    JWT_TOKEN_EXPIRE_HOURS, LOGIN_MAX_FAILED_ATTEMPTS,
    LOGIN_ATTEMPT_WINDOW_SECONDS, LOGIN_LOCKOUT_SECONDS,
    LOGIN_MAX_FAILED_ATTEMPTS_PER_IP,
)

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_EXPIRE_HOURS = JWT_TOKEN_EXPIRE_HOURS

# ── Bloqueo temporal tras intentos fallidos de login ───────────────────────────
# En memoria (se resetea si el proceso reinicia, igual que el resto del estado
# de esta app); alcanza para frenar fuerza bruta contra un panel de homelab
# sin sumar una dependencia nueva solo para esto.
_MAX_FAILED_ATTEMPTS = LOGIN_MAX_FAILED_ATTEMPTS
_ATTEMPT_WINDOW_SECONDS = LOGIN_ATTEMPT_WINDOW_SECONDS   # ventana en la que cuentan los fallos
_LOCKOUT_SECONDS = LOGIN_LOCKOUT_SECONDS                 # cuánto dura el bloqueo al superar el máximo

# Dos contadores por intento fallido: "ip:usuario" (5 por defecto) e "ip"
# sola (20 por defecto, con cualquier usuario). Sin el segundo, desde una
# misma IP se podía ir probando contraseñas con un nombre de usuario distinto
# cada vez sin llegar nunca al bloqueo.
_failed_attempts: dict[str, list[float]] = {}  # clave -> timestamps de fallos
_MAX_TRACKED_KEYS = 5000


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_attempt_keys(request: Request, username: str) -> list[tuple[str, int]]:
    ip = _client_ip(request)
    return [
        (f"{ip}:{username.strip().lower()}", _MAX_FAILED_ATTEMPTS),
        (f"ip:{ip}", LOGIN_MAX_FAILED_ATTEMPTS_PER_IP),
    ]


def _seconds_locked_out(key: str, max_attempts: int = _MAX_FAILED_ATTEMPTS) -> int | None:
    """Devuelve segundos restantes de bloqueo, o None si no está bloqueado. De paso descarta intentos ya fuera de la ventana."""
    now = time.time()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < _ATTEMPT_WINDOW_SECONDS]
    if attempts:
        _failed_attempts[key] = attempts
    else:
        _failed_attempts.pop(key, None)
    if max_attempts <= 0 or len(attempts) < max_attempts:
        return None
    trigger = attempts[-max_attempts]  # el intento que hizo superar el máximo
    remaining = _LOCKOUT_SECONDS - (now - trigger)
    return math.ceil(remaining) if remaining > 0 else None


def _prune_failed_attempts() -> None:
    """Que el diccionario no crezca sin límite con miles de usuarios/IP distintos."""
    if len(_failed_attempts) <= _MAX_TRACKED_KEYS:
        return
    now = time.time()
    for key in [k for k, ts in _failed_attempts.items() if not ts or now - ts[-1] >= _ATTEMPT_WINDOW_SECONDS]:
        _failed_attempts.pop(key, None)
    # Si aun así hay demasiadas, fuera las más antiguas.
    if len(_failed_attempts) > _MAX_TRACKED_KEYS:
        oldest = sorted(_failed_attempts, key=lambda k: _failed_attempts[k][-1])
        for key in oldest[: len(_failed_attempts) - _MAX_TRACKED_KEYS]:
            _failed_attempts.pop(key, None)


def _register_failed_attempt(key: str) -> None:
    _failed_attempts.setdefault(key, []).append(time.time())
    _prune_failed_attempts()


def _clear_failed_attempts(key: str) -> None:
    _failed_attempts.pop(key, None)


SESSION_COOKIE = "mc_session"


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET no configurado en .env")
    return secret


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(signing_input: str) -> bytes:
    return hmac.new(get_jwt_secret().encode(), signing_input.encode("ascii"), hashlib.sha256).digest()


def create_token(username: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "exp": int(time.time() + TOKEN_EXPIRE_HOURS * 3600),
        "pwf": password_fingerprint(username),
    }
    signing_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    return signing_input + "." + _b64url_encode(_signature(signing_input))


def verify_token(token: str) -> dict | None:
    """
    Devuelve {"sub": username, "role": role} si el token es válido, si no None.

    Además de la firma y la caducidad, comprueba que el usuario siga
    existiendo y que su contraseña no haya cambiado desde que se creó el token
    (ver password_fingerprint). El rol se calcula de nuevo en vez de fiarse
    del que llevara el token.
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None
        expected = _signature(header_b64 + "." + payload_b64)
        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError, AttributeError):
        return None

    username = payload.get("sub")
    exp = payload.get("exp")
    if not isinstance(username, str) or not isinstance(exp, (int, float)) or exp < time.time():
        return None
    current = password_fingerprint(username)
    if current is None or not hmac.compare_digest(str(payload.get("pwf", "")), current):
        return None
    return {"sub": username, "role": role_of(username)}


def token_from_request(request: Request) -> str:
    """La cookie de sesión, o una cabecera Authorization: Bearer (útil para scripts)."""
    auth = request.headers.get("Authorization", "")
    return auth.removeprefix("Bearer ").strip() or request.cookies.get(SESSION_COOKIE, "")


def require_admin(request: Request) -> None:
    """Corta con 403 si el usuario autenticado no tiene rol admin (gestión de
    usuarios y firewall; el resto de acciones del panel son accesibles para
    cualquier cuenta autenticada)."""
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    keys = _login_attempt_keys(request, username)
    locked_seconds = max((s for s in (_seconds_locked_out(k, m) for k, m in keys) if s is not None), default=None)
    if locked_seconds is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Prueba de nuevo dentro de {locked_seconds} segundos.",
        )

    role = authenticate(username, password)
    if role is None:
        for key, _ in keys:
            _register_failed_attempt(key)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    for key, _ in keys:
        _clear_failed_attempts(key)
    response = JSONResponse({"role": role, "user": username, "expires_in_hours": TOKEN_EXPIRE_HOURS})
    _set_session_cookie(response, username)
    return response


def _set_session_cookie(response: JSONResponse, username: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, create_token(username),
        max_age=TOKEN_EXPIRE_HOURS * 3600, httponly=True, samesite="strict", path="/",
    )


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/password")
def change_own_password(request: Request, body: ChangePasswordBody):
    """
    Cambia la contraseña de quien tiene la sesión iniciada (admin o usuario
    normal). Pide la actual: con una sesión olvidada abierta en otro equipo no
    basta para quedarse con la cuenta. Las demás sesiones de ese usuario se
    cierran (cambia la huella del hash); esta recibe una cookie nueva.
    """
    username = getattr(request.state, "user", None)
    if not username:
        raise HTTPException(status_code=401, detail="No autorizado")
    key = f"pw:{username}"
    locked_seconds = _seconds_locked_out(key)
    if locked_seconds is not None:
        raise HTTPException(status_code=429, detail=f"Demasiados intentos. Prueba de nuevo dentro de {locked_seconds} segundos.")
    if not verify_password(username, body.current_password):
        _register_failed_attempt(key)
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="La contraseña nueva es igual que la actual")
    try:
        set_password(username, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError:
        raise HTTPException(status_code=500, detail="No se pudo guardar la contraseña: el archivo no se puede escribir")
    _clear_failed_attempts(key)
    response = JSONResponse({"success": True})
    _set_session_cookie(response, username)
    return response


@router.post("/logout")
def logout():
    response = JSONResponse({"success": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/verify")
def verify(request: Request):
    info = verify_token(token_from_request(request))
    if not info:
        raise HTTPException(status_code=401, detail="Sesión no iniciada o caducada")
    return JSONResponse({"valid": True, "user": info["sub"], "role": info["role"]})
