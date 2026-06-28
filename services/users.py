"""
services/users.py - Gestión de usuarios del sistema.

El admin está definido en .env (APP_USERNAME + APP_PASSWORD_HASH).
Los usuarios normales se almacenan en users.json junto al .env.
"""
import json
import os
import bcrypt
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent.parent / ".env"
_USERS_PATH = Path(__file__).parent.parent / "users.json"

load_dotenv(_ENV_PATH, override=True)


def _admin_username() -> str:
    return os.getenv("APP_USERNAME", "pablo")


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
    _USERS_PATH.write_text(json.dumps(users, indent=2))


def list_users() -> list[dict]:
    result = [{"username": _admin_username(), "role": "admin"}]
    for u in _load():
        result.append({"username": u["username"], "role": "user"})
    return result


def authenticate(username: str, password: str) -> str | None:
    """Devuelve el rol ('admin' o 'user') si las credenciales son válidas, si no None."""
    if username == _admin_username():
        h = _admin_hash()
        if h and bcrypt.checkpw(password.encode(), h.encode()):
            return "admin"
        return None
    for u in _load():
        if u["username"] == username:
            if bcrypt.checkpw(password.encode(), u["password_hash"].encode()):
                return "user"
            return None
    return None


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


def delete_user(username: str) -> bool:
    if username == _admin_username():
        raise ValueError("No se puede eliminar al administrador")
    users = _load()
    new_users = [u for u in users if u["username"] != username]
    if len(new_users) == len(users):
        return False
    _save(new_users)
    return True
