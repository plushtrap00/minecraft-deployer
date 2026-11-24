"""
services/two_factor.py - Verificación en dos pasos (TOTP, RFC 6238), opcional
para cada cuenta.

Funciona con cualquier app de códigos (Google Authenticator, Aegis, 2FAS,
Bitwarden...): código de 6 cifras que cambia cada 30 segundos, con HMAC-SHA1
como pide la norma. Solo librería estándar.

Se guarda en SERVERS_PATH/.global/two_factor.json (permisos 600):
    {usuario: {"secret": base32, "enabled": bool, "pending": base32 | null,
               "recovery": [sha256 de cada código de recuperación],
               "last_step": int}}
«pending» es el secreto que se está configurando (aún sin confirmar con un
código); «last_step» impide reutilizar el mismo código dos veces.

Al activarla se dan 8 códigos de recuperación de un solo uso, para entrar si
se pierde el móvil. Si también se pierden, un administrador puede quitársela
a otra cuenta desde Usuarios, y la del administrador se quita con
`python3 set_password.py` en el servidor.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
import urllib.parse

from config import DEFAULT_SERVERS_PATH
from services.secure_files import atomic_write_text

STORE_FILE = DEFAULT_SERVERS_PATH / ".global" / "two_factor.json"
ISSUER = "Server Deployer"
PERIOD = 30
DIGITS = 6
# Se acepta el código del intervalo anterior y del siguiente (relojes un
# poco desajustados).
WINDOW = 1
RECOVERY_CODES = 8
_lock = threading.Lock()


def _load() -> dict:
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry(data: dict, username: str) -> dict:
    entry = data.get(username)
    return entry if isinstance(entry, dict) else {}


def _save(data: dict) -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(STORE_FILE, json.dumps(data, indent=2), private=True)


# ── TOTP ─────────────────────────────────────────────────────────────────────

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> bytes:
    secret = secret.strip().replace(" ", "").upper()
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def totp(secret: str, at: float | None = None) -> str:
    return hotp(_key(secret), int((time.time() if at is None else at) // PERIOD))


def _match_step(secret: str, code: str, at: float | None = None) -> int | None:
    """El intervalo al que corresponde el código, o None si no vale."""
    step = int((time.time() if at is None else at) // PERIOD)
    key = _key(secret)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if hmac.compare_digest(hotp(key, candidate), code):
            return candidate
    return None


def _clean_code(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isalnum()).lower()


def otpauth_uri(username: str, secret: str) -> str:
    label = urllib.parse.quote(f"{ISSUER}:{username}")
    query = urllib.parse.urlencode({"secret": secret, "issuer": ISSUER}, quote_via=urllib.parse.quote)
    return f"otpauth://totp/{label}?{query}"


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(_clean_code(code).encode()).hexdigest()


def _new_recovery_codes() -> list:
    # 10 caracteres sin letras que se confundan (0/o, 1/l), en dos grupos.
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(raw[:5] + "-" + raw[5:])
    return codes


# ── Cuentas ──────────────────────────────────────────────────────────────────

def is_enabled(username: str) -> bool:
    with _lock:
        entry = _entry(_load(), username)
    return bool(entry.get("enabled") and entry.get("secret"))


def status(username: str) -> dict:
    with _lock:
        entry = _entry(_load(), username)
    return {"enabled": bool(entry.get("enabled")), "recovery_left": len(entry.get("recovery") or [])}


def begin_setup(username: str) -> dict:
    """Genera un secreto nuevo (pendiente hasta que se confirme con un código)."""
    secret = new_secret()
    with _lock:
        data = _load()
        entry = _entry(data, username)
        if entry.get("enabled"):
            raise ValueError("La verificación en dos pasos ya está activada")
        entry["pending"] = secret
        data[username] = entry
        _save(data)
    return {"secret": secret, "uri": otpauth_uri(username, secret)}


def confirm_setup(username: str, code: str) -> list:
    """Activa la verificación si el código de la app es correcto. Devuelve los códigos de recuperación."""
    code = _clean_code(code)
    with _lock:
        data = _load()
        entry = _entry(data, username)
        secret = entry.get("pending")
        if not secret:
            raise ValueError("Empieza de nuevo la configuración de la verificación en dos pasos")
        step = _match_step(secret, code)
        if step is None:
            raise ValueError("El código no es correcto. Comprueba que la hora del móvil está bien y prueba con el siguiente.")
        codes = _new_recovery_codes()
        data[username] = {
            "secret": secret, "enabled": True, "pending": None, "last_step": step,
            "recovery": [_hash_recovery(c) for c in codes], "enabled_at": time.time(),
        }
        _save(data)
    return codes


def regenerate_recovery(username: str) -> list:
    with _lock:
        data = _load()
        entry = _entry(data, username)
        if not entry.get("enabled"):
            raise ValueError("La verificación en dos pasos no está activada")
        codes = _new_recovery_codes()
        entry["recovery"] = [_hash_recovery(c) for c in codes]
        data[username] = entry
        _save(data)
    return codes


def verify(username: str, code: str) -> str | None:
    """
    Comprueba un código al entrar: "totp" si es el de la app, "recovery" si es
    uno de recuperación (que queda gastado), None si no vale.
    """
    code = _clean_code(code)
    if not code:
        return None
    with _lock:
        data = _load()
        entry = _entry(data, username)
        if not entry.get("enabled") or not entry.get("secret"):
            return None
        if code.isdigit() and len(code) == DIGITS:
            step = _match_step(entry["secret"], code)
            if step is None or step <= int(entry.get("last_step") or -1):
                return None
            entry["last_step"] = step
            data[username] = entry
            _save(data)
            return "totp"
        hashed = _hash_recovery(code)
        remaining = [h for h in entry.get("recovery") or [] if not hmac.compare_digest(h, hashed)]
        if len(remaining) == len(entry.get("recovery") or []):
            return None
        entry["recovery"] = remaining
        data[username] = entry
        _save(data)
        return "recovery"


def disable(username: str) -> bool:
    with _lock:
        data = _load()
        if data.pop(username, None) is None:
            return False
        _save(data)
    return True
