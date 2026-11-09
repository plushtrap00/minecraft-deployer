"""
services/users.py - Gestión de usuarios del sistema.

El admin está definido en .env (APP_USERNAME + APP_PASSWORD_HASH).
Los usuarios normales se almacenan en users.json junto al .env.
"""
import hashlib
import json
import os
import re
import bcrypt
from pathlib import Path
from dotenv import load_dotenv, set_key
from services.secure_files import atomic_write_text

_ENV_PATH = Path(__file__).parent.parent / ".env"
_USERS_PATH = Path(__file__).parent.parent / "users.json"

load_dotenv(_ENV_PATH, override=True)


def _admin_username() -> str:
    return os.getenv("APP_USERNAME", "admin")


def admin_username() -> str:
    return _admin_username()


def _admin_hash() -> str | None:
    return os.getenv("APP_PASSWORD_HASH") or os.getenv("PABLO_PASSWORD_HASH")


def _load() -> list[dict]:
    if not _USERS_PATH.exists():
        return []
    try:
        return json.loads(_USERS_PATH.read_text())
    except Exception:
        return []


def _save(users: list[dict]) -> None:
    atomic_write_text(_USERS_PATH, json.dumps(users, indent=2), private=True)


def list_users() -> list[dict]:
    result = [{"username": _admin_username(), "role": "admin"}]
    for u in _load():
        result.append({"username": u["username"], "role": "user"})
    return result


# Hash de relleno: con un usuario que no existe también se hace una
# comprobación bcrypt completa. Si no, la respuesta llegaba al instante y con
# uno que sí existe tardaba lo que bcrypt, y midiendo el tiempo se podía saber
# qué nombres de usuario son válidos.
_DUMMY_HASH = bcrypt.hashpw(b"usuario-inexistente", bcrypt.gensalt()).decode()


def _stored_hash(username: str) -> str | None:
    if username == _admin_username():
        return _admin_hash()
    return next((u["password_hash"] for u in _load() if u["username"] == username), None)


def authenticate(username: str, password: str) -> str | None:
    """Devuelve el rol ('admin' o 'user') si las credenciales son válidas, si no None."""
    stored = _stored_hash(username)
    try:
        ok = bcrypt.checkpw(password.encode(), (stored or _DUMMY_HASH).encode())
    except ValueError:
        # Hash corrupto en users.json/.env: se trata como contraseña incorrecta.
        ok = False
    if not ok or stored is None:
        return None
    return role_of(username)


def password_fingerprint(username: str) -> str | None:
    """
    Huella corta del hash de contraseña actual del usuario, o None si el
    usuario ya no existe. Va dentro de cada token de sesión: si se borra el
    usuario o cambia su contraseña, la huella deja de coincidir y todas sus
    sesiones abiertas dejan de valer, sin tener que guardar una lista de
    tokens revocados.
    """
    h = _stored_hash(username)
    if not h:
        return None
    return hashlib.sha256(h.encode()).hexdigest()[:16]


def role_of(username: str) -> str:
    return "admin" if username == _admin_username() else "user"


def create_user(username: str, password: str) -> dict:
    if username == _admin_username():
        raise ValueError("Nombre de usuario ya en uso")
    users = _load()
    if any(u["username"] == username for u in users):
        raise ValueError("Nombre de usuario ya en uso")
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users.append({"username": username, "password_hash": pw_hash, "role": "user"})
    _save(users)
    return {"username": username, "role": "user"}


_PRINTABLE_RE = re.compile(r'^[\x20-\x7E]+$')


def validate_password(password: str) -> None:
    """ValueError con un mensaje legible si la contraseña no vale."""
    if len(password) < 8 or not _PRINTABLE_RE.match(password):
        raise ValueError("Contraseña inválida: mínimo 8 caracteres, sin emojis ni símbolos raros")
    if len(password.encode()) > 72:
        # bcrypt solo mira los primeros 72 bytes (y las versiones nuevas de la
        # librería lanzan error con más).
        raise ValueError("Contraseña demasiado larga: máximo 72 caracteres")


def verify_password(username: str, password: str) -> bool:
    return authenticate(username, password) is not None


def set_password(username: str, new_password: str) -> None:
    """
    Cambia la contraseña de cualquier usuario (el admin vive en .env, el resto
    en users.json). Se aplica al momento, sin reiniciar, y como cambia el hash
    también cambia su huella (password_fingerprint): todas las sesiones
    abiertas de ese usuario dejan de valer.
    """
    validate_password(new_password)
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    if username == _admin_username():
        set_key(str(_ENV_PATH), "APP_PASSWORD_HASH", new_hash, quote_mode="never")
        os.environ["APP_PASSWORD_HASH"] = new_hash
        return
    users = _load()
    for u in users:
        if u["username"] == username:
            u["password_hash"] = new_hash
            _save(users)
            return
    raise KeyError(username)


def delete_user(username: str) -> bool:
    if username == _admin_username():
        raise ValueError("No se puede eliminar al administrador")
    users = _load()
    new_users = [u for u in users if u["username"] != username]
    if len(new_users) == len(users):
        return False
    _save(new_users)
    return True
