"""
Mensajes del backend en otro idioma (fase 4): plantillas con huecos en
en.json, el middleware que traduce las respuestas JSON y los eventos SSE de
/api/, y el idioma de los avisos de Telegram/Discord.
"""
import asyncio
import json
import os
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services import i18n, notify
from services.i18n_middleware import MessageTranslationMiddleware


class TemplateTests(unittest.TestCase):
    def test_exact_and_template(self):
        self.assertEqual(i18n.translate_message("El modpack no existe", "en"), "The modpack doesn't exist")
        self.assertEqual(i18n.translate_message("Steve ya es op", "en"), "Steve is already an op")

    def test_nested_and_lists(self):
        self.assertEqual(
            i18n.translate_message("⚠️ La tarea programada (reiniciar el servidor) ha fallado: No hay servidor en marcha", "en"),
            "⚠️ The scheduled task (restart the server) failed: No server is running")
        self.assertEqual(
            i18n.translate_message("No se puede borrar: hay una operación en curso (clonando A, borrando modpack 'B').", "en"),
            "Can't delete: an operation is in progress (cloning A, deleting modpack 'B').")

    def test_unknown_and_spanish_untouched(self):
        self.assertEqual(i18n.translate_message("algo que no está", "en"), "algo que no está")
        self.assertEqual(i18n.translate_message("El modpack no existe", "es"), "El modpack no existe")
        # Plantillas casi vacías («Los {days}») no se usan para mensajes.
        self.assertEqual(i18n.translate_message("Los mods", "en"), "Los mods")

    def test_payload_only_message_fields(self):
        data = {"detail": "El modpack no existe", "name": "El modpack no existe",
                "items": [{"reason": "nombre muy parecido", "file": "x"}]}
        out = i18n.translate_payload(data, "en")
        self.assertEqual(out["detail"], "The modpack doesn't exist")
        self.assertEqual(out["name"], "El modpack no existe")
        self.assertEqual(out["items"][0]["reason"], "very similar name")


def make_app():
    app = FastAPI()

    @app.get("/api/error")
    def error():
        raise HTTPException(status_code=404, detail="El modpack no existe")

    @app.get("/api/ok")
    def ok():
        return JSONResponse({"message": "Reiniciando la app...", "value": "Reiniciando la app..."})

    @app.get("/api/stream")
    def stream():
        async def events():
            yield "data: " + json.dumps({"type": "log", "message": "Ejecutando instalador..."}) + "\n\n"
            await asyncio.sleep(0)
            yield "data: " + json.dumps({"type": "error", "detail": "El modpack no existe"}) + "\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/server/logs")
    def logs():
        return JSONResponse({"detail": "El modpack no existe"})

    app.add_middleware(MessageTranslationMiddleware)
    return app


class Response:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.text = content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


def call(app, path, lang):
    """Una petición GET directa a la app ASGI (sin httpx)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
             "headers": [(b"cookie", f"{i18n.COOKIE_NAME}={lang}".encode())],
             "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
    messages = []

    sent_body = []

    async def receive():
        if not sent_body:
            sent_body.append(True)
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)  # el cliente sigue conectado
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return Response(start["status"], headers, body)


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()

    def get(self, path, lang):
        return call(self.app, path, lang)

    def test_json_error_and_fields(self):
        r = self.get("/api/error", "en")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"detail": "The modpack doesn't exist"})
        self.assertEqual(int(r.headers["content-length"]), len(r.content))
        self.assertEqual(self.get("/api/ok", "en").json(),
                         {"message": "Restarting the app...", "value": "Reiniciando la app..."})

    def test_spanish_untouched(self):
        self.assertEqual(self.get("/api/error", "es").json(), {"detail": "El modpack no existe"})

    def test_sse(self):
        text = self.get("/api/stream", "en").text
        self.assertIn('"message":"Running the installer..."', text)
        self.assertIn('"detail":"The modpack doesn\'t exist"', text)
        self.assertEqual(text.count("\n\n"), 2)

    def test_console_stream_skipped(self):
        self.assertEqual(self.get("/api/server/logs", "en").json(), {"detail": "El modpack no existe"})


class NotifyLanguageTests(unittest.TestCase):
    def test_send_now_uses_notify_language(self):
        sent = []
        with mock.patch.object(notify, "send_discord", lambda url, text: sent.append(text)):
            notify.send_now({"discord_webhook": "https://discord.com/api/webhooks/1/x", "language": "en"},
                            "✅ ATM9 está listo para jugar.")
            notify.send_now({"discord_webhook": "https://discord.com/api/webhooks/1/x", "language": "es"},
                            "✅ ATM9 está listo para jugar.")
        self.assertEqual(sent, ["✅ ATM9 is ready to play.", "✅ ATM9 está listo para jugar."])

    def test_default_follows_app_language(self):
        with mock.patch.object(notify, "_ENV_PATH", notify._ENV_PATH.with_name("no-existe.env")), \
             mock.patch.dict(os.environ, {"APP_LANGUAGE": "en"}):
            os.environ.pop("NOTIFY_LANGUAGE", None)
            self.assertEqual(notify.load_settings()["language"], "en")
            os.environ["NOTIFY_LANGUAGE"] = "es"
            self.assertEqual(notify.load_settings()["language"], "es")


if __name__ == "__main__":
    unittest.main()


# ── Repaso estricto ───────────────────────────────────────────────────────────
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sample(node):
    """El texto de un literal o f-string, con datos de ejemplo en los huecos."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append("Xq7")
        return "".join(parts)
    return None


def backend_messages():
    """(archivo:línea, texto) de cada detail= de HTTPException y cada notify(...)."""
    found = []
    for path in list((ROOT / "routes").glob("*.py")) + list((ROOT / "services").glob("*.py")) + [ROOT / "main.py", ROOT / "app_constants.py", ROOT / "config.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            texts = []
            if name == "HTTPException":
                texts = [kw.value for kw in node.keywords if kw.arg == "detail"]
            elif name == "notify" and len(node.args) == 2:
                texts = [node.args[1]]
            elif name in ("ValueError", "RuntimeError", "PendingModsError") and node.args:
                # Los servicios lanzan esto y las rutas lo devuelven con detail=str(e).
                texts = [node.args[0]]
            for text_node in texts:
                sample = _sample(text_node)
                if sample and re.search(r"[a-záéíóúñ]{3,}", sample):
                    found.append((f"{path.name}:{node.lineno}", sample))
    return found


class StrictTests(unittest.TestCase):
    def test_every_backend_message_translated(self):
        missing = [f"{where}: {text}" for where, text in backend_messages()
                   if i18n.translate_message(" ".join(text.split()), "en") == " ".join(text.split())]
        self.assertEqual(missing, [], "Mensajes del backend sin traducción en en.json")
        self.assertGreater(len(backend_messages()), 100)

    def test_achievements_and_splashes_translated(self):
        table = i18n.load("en")
        texts = []
        source = (ROOT / "static" / "js" / "achievements.js").read_text(encoding="utf-8")
        texts += re.findall(r"(?:name|hint): '([^']*)'", source)
        splash = (ROOT / "static" / "js" / "appearance.js").read_text(encoding="utf-8")
        block = splash[splash.index("var SPLASHES"):splash.index("];", splash.index("var SPLASHES"))]
        texts += re.findall(r"'([^']*)'", block)
        self.assertGreater(len(texts), 60)
        missing = [text for text in texts if i18n.normalize(text) not in table]
        self.assertEqual(missing, [])
