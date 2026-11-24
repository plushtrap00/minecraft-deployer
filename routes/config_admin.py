"""
routes/config_admin.py - Panel de administración: editar .env y .APP_CONSTANTS.

Solo accesible para el rol admin (mismo criterio que gestión de usuarios y
firewall: acciones de infraestructura, no de uso normal del panel). Los
cambios no se aplican en caliente — al guardar el .env o las constantes, el
frontend ofrece reiniciar la app en el momento, reusando el mecanismo ya
existente de services/auto_update.py (mismo aviso de seguridad: no reinicia
si hay un servidor de Minecraft corriendo o una operación en curso).

Los secretos (JWT_SECRET, la API key de CurseForge, el token de Telegram y el
webhook de Discord) son de solo escritura: los GET nunca los devuelven, solo
dicen si están puestos (`secrets_set`). Al guardar, un secreto vacío deja el
que había; para borrarlo hay que pedirlo en `clear`.

Rutas:
- GET  /api/admin/env        → variables de .env conocidas (sin hashes ni secretos)
- POST /api/admin/env        → guarda cambios; una nueva contraseña (opcional) se hashea aquí
- GET  /api/admin/constants  → valores + descripciones de .APP_CONSTANTS
- POST /api/admin/constants  → guarda cambios
- POST /api/admin/restart    → reinicia la app para aplicar lo anterior
- GET  /api/admin/notifications              → avisos por Telegram/Discord
- POST /api/admin/notifications              → guardarlos (se aplican al momento, sin reiniciar)
- POST /api/admin/notifications/test         → mensaje de prueba con lo escrito (aunque no esté guardado)
- POST /api/admin/notifications/detect-chat  → averigua el chat ID con el token del bot
"""
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import dotenv_values, set_key

import app_constants
from services import auto_update, i18n, notify, users
from services.users import set_password
from routes.auth import require_admin as _require_admin

router = APIRouter(prefix="/api/admin", tags=["admin-config"])

_ENV_PATH = Path(__file__).parent.parent / ".env"

# Claves de .env que expone el formulario. APP_PASSWORD_HASH/PABLO_PASSWORD_HASH
# quedan afuera a propósito: no tiene sentido pegar un hash bcrypt a mano — el
# cambio de contraseña usa su propio campo de texto plano (ver new_password),
# que se hashea aquí mismo antes de guardarlo.
_ENV_EDITABLE_KEYS = [
    "APP_USERNAME", "JWT_SECRET", "WEB_PORT", "SERVERS_PATH", "MC_DOMAIN",
    "CURSEFORGE_API_KEY", "AUTO_UPDATE_ENABLED", "AUTO_UPDATE_INTERVAL_SECONDS",
    "APP_LANGUAGE",
]

# Secretos del formulario: nunca salen hacia el navegador (ver docstring). La
# API key se puede quitar (deja de usarse CurseForge); JWT_SECRET no, porque
# sin él no se pueden firmar sesiones.
_ENV_SECRET_KEYS = {"JWT_SECRET", "CURSEFORGE_API_KEY"}
_ENV_CLEARABLE_SECRETS = {"CURSEFORGE_API_KEY"}

# Lo que vale una clave que no está en el .env: el formulario la muestra así y
# guardar ese mismo valor no cuenta como cambio.
_ENV_DEFAULTS = {"APP_LANGUAGE": i18n.DEFAULT_LANG}


@router.get("/env")
def get_env(request: Request):
    _require_admin(request)
    values = dotenv_values(_ENV_PATH) if _ENV_PATH.exists() else {}
    result: dict = {
        key: values.get(key, "") for key in _ENV_EDITABLE_KEYS if key not in _ENV_SECRET_KEYS
    }
    for key, default in _ENV_DEFAULTS.items():
        result[key] = result.get(key) or default
    result["secrets_set"] = {key: bool(values.get(key)) for key in sorted(_ENV_SECRET_KEYS)}
    # WEB_PORT/SERVERS_PATH en Docker los controla docker-compose.yml (mapeo de
    # puertos y volumen/carpeta), no este .env — el frontend usa esto para
    # avisar en vez de dejar que el usuario cambie un campo sin efecto real (y
    # que además falla al guardar si el .env está montado de solo lectura,
    # como en el docker-compose.yml que genera setup.py).
    result["in_docker"] = auto_update.running_in_docker()
    return JSONResponse(result)


class EnvUpdateBody(BaseModel):
    values: dict
    new_password: str = ""
    clear: list = []


def _env_changes(body: EnvUpdateBody) -> dict:
    """
    Lo que hay que escribir en el .env: las claves editables que llegan, salvo
    los secretos vacíos (vacío = «deja el que hay», porque el formulario nunca
    los recibe), más los secretos que se piden quitar en `clear` (a "").
    """
    changes = {}
    for key, value in body.values.items():
        if key not in _ENV_EDITABLE_KEYS:
            continue
        value = str(value)
        if key in _ENV_SECRET_KEYS and not value:
            continue
        changes[key] = value
    for key in body.clear:
        if key in _ENV_CLEARABLE_SECRETS and not changes.get(key):
            changes[key] = ""
    return changes


@router.post("/env")
async def update_env(request: Request, body: EnvUpdateBody):
    _require_admin(request)
    changes = _env_changes(body)

    # Solo se ofrece reiniciar (y solo se toca el disco) si algo cambió de
    # verdad — comparado contra lo que ya hay en .env, no contra lo último
    # que este proceso leyó al arrancar. Una contraseña nueva siempre cuenta
    # como cambio: al ser un campo write-only (se guarda ya hasheada) no hay
    # nada previo con qué compararla.
    current = dotenv_values(_ENV_PATH) if _ENV_PATH.exists() else {}
    changed = bool(body.new_password) or any(
        str(current.get(key) or _ENV_DEFAULTS.get(key, "")) != value for key, value in changes.items()
    )
    if not changed:
        return JSONResponse({"success": True, "changed": False})

    # Sin comillas en el .env, un salto de línea en un valor colaría otra
    # variable (p. ej. APP_PASSWORD_HASH) en la línea siguiente.
    for key, value in changes.items():
        if any(ch in value for ch in "\r\n\x00"):
            raise HTTPException(status_code=400, detail=f"{key} no puede contener saltos de línea")
    if changes.get("APP_LANGUAGE", i18n.DEFAULT_LANG) not in i18n.LANGS:
        raise HTTPException(status_code=400, detail="Idioma no disponible")

    try:
        if body.new_password:
            # Se aplica al momento (no espera al reinicio) y cierra las
            # sesiones abiertas del admin, igual que «Cambiar contraseña».
            try:
                await asyncio.to_thread(set_password, users.admin_username(), body.new_password)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        for key, value in changes.items():
            await asyncio.to_thread(set_key, str(_ENV_PATH), key, value, quote_mode="never")
    except HTTPException:
        raise
    except OSError as e:
        # dotenv.set_key() escribe de forma atómica (archivo temporal + os.replace);
        # si .env no se puede escribir (p.ej. montado ":ro" en Docker), esto lanza
        # sin que quede rastro en ningún lado si no se captura explícitamente aquí.
        print(f"[config-admin] No se pudo escribir {_ENV_PATH}: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo guardar .env: el archivo no se puede escribir. Si usas Docker, "
                "comprueba que docker-compose.yml no monte el .env como solo lectura (sin "
                "\":ro\" en esa línea) — puede que necesites volver a ejecutar "
                "'python3 setup.py' para regenerarlo tras una actualización."
            ),
        )
    except Exception as e:
        print(f"[config-admin] Error inesperado guardando .env: {e!r}", flush=True)
        raise HTTPException(status_code=500, detail=f"Error inesperado al guardar .env: {e}")

    auto_update.mark_restart_pending()
    return JSONResponse({"success": True, "changed": True})


@router.get("/constants")
def get_constants(request: Request):
    _require_admin(request)
    return JSONResponse(app_constants.get_all())


class ConstantsUpdateBody(BaseModel):
    values: dict


@router.post("/constants")
async def update_constants(request: Request, body: ConstantsUpdateBody):
    _require_admin(request)
    try:
        changed = await asyncio.to_thread(app_constants.save, body.values)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if changed:
        auto_update.mark_restart_pending()
    return JSONResponse({"success": True, "changed": changed})


@router.post("/restart")
async def restart_app(request: Request):
    _require_admin(request)
    try:
        await asyncio.to_thread(auto_update.restart_now)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    auto_update.schedule_restart()
    return JSONResponse({"success": True, "message": "Reiniciando la app..."})


# ── Avisos por Telegram / Discord ─────────────────────────────────────────────
# Van en el .env (el token del bot y el webhook son secretos), pero
# services/notify.py los lee en cada envío: no hace falta reiniciar la app.
# El token del bot y el webhook son de solo escritura, como los secretos del
# formulario del .env: el GET solo dice si están puestos.
_NOTIFY_SECRET_FIELDS = ("telegram_token", "discord_webhook")


@router.get("/notifications")
def get_notifications(request: Request):
    _require_admin(request)
    settings: dict = notify.load_settings()
    settings["secrets_set"] = {field: bool(settings[field]) for field in _NOTIFY_SECRET_FIELDS}
    for field in _NOTIFY_SECRET_FIELDS:
        settings[field] = ""
    return JSONResponse({**settings, "available_events": notify.EVENTS})


class NotificationsBody(BaseModel):
    telegram_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook: str = ""
    events: list = []
    language: str = ""
    # Secretos que hay que borrar (telegram_token / discord_webhook); los que
    # llegan vacíos sin estar aquí se quedan como estaban.
    clear: list = []


def _clean_notifications(body: NotificationsBody) -> dict:
    stored = notify.load_settings()
    values: dict = {
        "telegram_token": body.telegram_token.strip(),
        "telegram_chat_id": body.telegram_chat_id.strip(),
        "discord_webhook": body.discord_webhook.strip(),
    }
    for field in _NOTIFY_SECRET_FIELDS:
        if not values[field] and field not in body.clear:
            values[field] = stored[field]
    for value in values.values():
        if any(ch in value for ch in "\r\n\x00 "):
            raise HTTPException(status_code=400, detail="Los datos de los avisos no pueden llevar espacios ni saltos de línea")
    if values["discord_webhook"] and not notify.valid_discord_webhook(values["discord_webhook"]):
        raise HTTPException(status_code=400, detail="La URL del webhook de Discord no es válida (tiene que empezar por https://discord.com/api/webhooks/)")
    if bool(values["telegram_token"]) != bool(values["telegram_chat_id"]):
        raise HTTPException(status_code=400, detail="Para Telegram hacen falta el token del bot y el chat ID")
    values["events"] = [e for e in body.events if e in notify.EVENTS]
    values["language"] = i18n.pick_lang(body.language) or stored["language"]
    return values


@router.post("/notifications")
async def save_notifications(request: Request, body: NotificationsBody):
    _require_admin(request)
    values = _clean_notifications(body)
    pairs = {
        "TELEGRAM_BOT_TOKEN": values["telegram_token"],
        "TELEGRAM_CHAT_ID": values["telegram_chat_id"],
        "DISCORD_WEBHOOK_URL": values["discord_webhook"],
        # Vacío significaría «los de siempre»: si se desmarca todo, se guarda «none».
        "NOTIFY_EVENTS": ",".join(values["events"]) or "none",
        "NOTIFY_LANGUAGE": values["language"],
    }
    try:
        for key, value in pairs.items():
            await asyncio.to_thread(set_key, str(_ENV_PATH), key, value, quote_mode="never")
    except OSError as e:
        print(f"[config-admin] No se pudo escribir {_ENV_PATH}: {e}", flush=True)
        raise HTTPException(status_code=500, detail="No se pudo guardar en .env: el archivo no se puede escribir")
    return JSONResponse({"success": True})


@router.post("/notifications/test")
async def test_notifications(request: Request, body: NotificationsBody):
    _require_admin(request)
    values = _clean_notifications(body)
    if not notify.is_configured(values):
        raise HTTPException(status_code=400, detail="Configura Telegram o Discord antes de probar")
    results = await asyncio.to_thread(
        notify.send_now, values, "🧪 Mensaje de prueba de Server Deployer: los avisos funcionan."
    )
    return JSONResponse({"results": results, "ok": all(r == "ok" for r in results.values())})


class DetectChatBody(BaseModel):
    # Vacío = el token ya guardado (el panel no lo tiene: es de solo escritura).
    telegram_token: str = ""


@router.post("/notifications/detect-chat")
async def detect_chat(request: Request, body: DetectChatBody):
    _require_admin(request)
    token = body.telegram_token.strip() or notify.load_settings()["telegram_token"]
    try:
        chat = await asyncio.to_thread(notify.detect_telegram_chat, token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(chat)
