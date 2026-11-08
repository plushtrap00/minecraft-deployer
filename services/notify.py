"""
services/notify.py - Avisos por Telegram y Discord (los dos opcionales).

Cada instalación usa su propio bot de Telegram (token de @BotFather) y su
propio chat, o su propio webhook de Discord: los mensajes solo llegan a quien
los configuró. Si no hay nada configurado, notify() no hace nada.

La configuración se lee del .env en cada envío (no al arrancar), así que al
cambiarla desde Configuración se aplica al momento, sin reiniciar la app.

Los envíos van por un hilo propio con una cola: quien avisa (el lector de la
consola, el planificador...) nunca espera a la red.
"""
import json
import os
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Claves del .env y sucesos que se pueden avisar (con su texto para el panel).
ENV_KEYS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "NOTIFY_EVENTS"]
EVENTS = {
    "ready": "El servidor está listo para jugar",
    "stopped": "El servidor se ha parado",
    "crash": "El servidor se ha caído",
    "join": "Un jugador entra",
    "leave": "Un jugador sale",
    "backup_failed": "Una copia de seguridad falla",
    "backup_done": "Una copia de seguridad termina",
    "install": "Termina la instalación de un modpack",
    "task": "Se ejecuta una tarea programada",
}
DEFAULT_EVENTS = ["ready", "stopped", "crash", "join", "backup_failed", "install"]

_TIMEOUT = 10
_queue: "queue.Queue" = queue.Queue(maxsize=200)
_worker = None
_worker_lock = threading.Lock()


def load_settings() -> dict:
    """Configuración actual (del .env; si no está, de las variables de entorno)."""
    values = dotenv_values(_ENV_PATH) if _ENV_PATH.exists() else {}

    def get(key):
        value = values.get(key)
        if value is None:
            value = os.environ.get(key, "")
        return (value or "").strip()

    events_raw = get("NOTIFY_EVENTS")
    events = [e for e in events_raw.split(",") if e.strip() in EVENTS] if events_raw else list(DEFAULT_EVENTS)
    return {
        "telegram_token": get("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": get("TELEGRAM_CHAT_ID"),
        "discord_webhook": get("DISCORD_WEBHOOK_URL"),
        "events": [e.strip() for e in events],
    }


def is_configured(settings: dict | None = None) -> bool:
    settings = settings or load_settings()
    return bool((settings["telegram_token"] and settings["telegram_chat_id"]) or settings["discord_webhook"])


def valid_discord_webhook(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com") \
        and parsed.path.startswith("/api/webhooks/")


def _post_json(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "MinecraftServerDeployer",
    })
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        response.read()


def _http_error_detail(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        try:
            body = json.loads(error.read().decode("utf-8", errors="replace"))
            description = body.get("description") or body.get("message")
            if description:
                return f"{error.code}: {description}"
        except Exception:
            pass
        return f"error {error.code}"
    if isinstance(error, urllib.error.URLError):
        return f"sin conexión ({error.reason})"
    return str(error)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Lanza una excepción si Telegram no acepta el mensaje."""
    if not token or not chat_id:
        raise ValueError("Falta el token del bot o el chat ID")
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
    _post_json(url, {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def send_discord(webhook: str, text: str) -> None:
    if not valid_discord_webhook(webhook):
        raise ValueError("La URL del webhook de Discord no es válida")
    _post_json(webhook, {"content": text[:1900], "username": "MC Deployer"})


def send_now(settings: dict, text: str) -> dict:
    """Envía ya (sin cola) a los canales configurados. Devuelve {canal: 'ok' | error}."""
    results = {}
    if settings.get("telegram_token") or settings.get("telegram_chat_id"):
        try:
            send_telegram(settings.get("telegram_token", ""), settings.get("telegram_chat_id", ""), text)
            results["telegram"] = "ok"
        except Exception as e:
            results["telegram"] = _http_error_detail(e)
    if settings.get("discord_webhook"):
        try:
            send_discord(settings["discord_webhook"], text)
            results["discord"] = "ok"
        except Exception as e:
            results["discord"] = _http_error_detail(e)
    return results


def detect_telegram_chat(token: str) -> dict:
    """
    Busca el chat del último mensaje que recibió el bot (hay que escribirle
    antes, por ejemplo /start). Devuelve {"chat_id", "name"} o lanza ValueError.
    """
    if not token:
        raise ValueError("Escribe primero el token del bot")
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/getUpdates"
    request = urllib.request.Request(url, headers={"User-Agent": "MinecraftServerDeployer"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise ValueError("Telegram no acepta ese token (" + _http_error_detail(e) + ")")
    for update in reversed(body.get("result") or []):
        message = update.get("message") or update.get("channel_post") or update.get("my_chat_member") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            name = chat.get("title") or " ".join(
                part for part in (chat.get("first_name"), chat.get("last_name")) if part
            ) or chat.get("username") or str(chat["id"])
            return {"chat_id": str(chat["id"]), "name": name}
    raise ValueError("El bot todavía no ha recibido ningún mensaje. Escríbele algo (por ejemplo /start) y vuelve a probar.")


def _work():
    while True:
        text = _queue.get()
        try:
            settings = load_settings()
            results = send_now(settings, text)
            for channel, result in results.items():
                if result != "ok":
                    print(f"[avisos] {channel}: {result}", flush=True)
        except Exception as e:
            print(f"[avisos] error inesperado: {e!r}", flush=True)


def notify(event: str, text: str) -> None:
    """Avisa de un suceso si hay algún canal configurado y ese suceso está activado."""
    try:
        settings = load_settings()
    except Exception:
        return
    if event not in settings["events"] or not is_configured(settings):
        return
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="avisos")
            _worker.start()
    try:
        _queue.put_nowait(text)
    except queue.Full:
        pass


def notify_install_result(event: dict, name: str) -> None:
    """Aviso de «install» al terminar (bien o mal) una instalación por SSE."""
    if not isinstance(event, dict) or event.get("type") != "done":
        return
    if event.get("success"):
        notify("install", f"📦 {name} se ha instalado y está listo para arrancar.")
    else:
        notify("install", f"⚠️ La instalación de {name} ha fallado: {event.get('detail', 'error desconocido')}")
