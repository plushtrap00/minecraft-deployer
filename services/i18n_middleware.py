"""
i18n_middleware.py - Traduce los mensajes del backend al idioma de quien pide.

Los endpoints escriben sus errores, motivos y mensajes de progreso en español;
este middleware los pasa al idioma de la petición (el de la cuenta, o el de la
cookie / APP_LANGUAGE) en dos sitios:

- Respuestas JSON de /api/: los campos de i18n.MESSAGE_FIELDS (detail,
  message, reason…), incluidos los errores de HTTPException.
- Eventos SSE (text/event-stream): cada línea «data: {json}» igual.

En español no hace nada. Va por dentro de la compresión gzip, así que ve los
cuerpos sin comprimir.
"""
import json

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from services import i18n

# Respuestas más grandes (listas de archivos, contenidos) se dejan como están:
# no llevan mensajes y no merece la pena volver a serializarlas.
_MAX_JSON_BYTES = 1024 * 1024
# La consola del servidor: líneas del log tal cual (no JSON) en un flujo que no
# se acaba; no hay nada que traducir.
_SKIP_PATHS = {"/api/server/logs"}


def _translate_json(body: bytes, lang: str) -> bytes | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    translated = i18n.translate_payload(data, lang)
    if translated == data:
        return None
    return json.dumps(translated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _translate_event(event: str, lang: str) -> str:
    lines = []
    for line in event.split("\n"):
        if line.startswith("data: "):
            new = _translate_json(line[6:].encode("utf-8"), lang)
            if new is not None:
                line = "data: " + new.decode("utf-8")
        lines.append(line)
    return "\n".join(lines)


class MessageTranslationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["path"] in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return
        lang = i18n.request_lang(Request(scope))
        if lang == i18n.DEFAULT_LANG:
            await self.app(scope, receive, send)
            return

        mode = None
        start = None
        chunks: list = []
        size = 0
        pending = ""

        async def wrapped(message):
            nonlocal mode, start, size, pending
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                ctype = headers.get("content-type", "")
                if headers.get("content-encoding"):
                    mode = "pass"
                elif "application/json" in ctype:
                    mode = "json"
                    start = message
                    return
                elif "text/event-stream" in ctype:
                    mode = "sse"
                else:
                    mode = "pass"
                await send(message)
                return

            if message["type"] != "http.response.body" or mode == "pass":
                await send(message)
                return

            body = message.get("body", b"")
            more = message.get("more_body", False)

            if mode == "json":
                chunks.append(body)
                size += len(body)
                if size > _MAX_JSON_BYTES:
                    # Demasiado grande: se manda tal cual lo que hay y el resto.
                    mode = "pass"
                    await send(start)
                    await send({"type": "http.response.body", "body": b"".join(chunks), "more_body": more})
                    return
                if more:
                    return
                full = b"".join(chunks)
                new = _translate_json(full, lang) if full else None
                if new is not None:
                    full = new
                    assert start is not None
                    headers = MutableHeaders(raw=start["headers"])
                    headers["content-length"] = str(len(full))
                await send(start)
                await send({"type": "http.response.body", "body": full, "more_body": False})
                return

            # SSE: los eventos se separan con una línea en blanco; un evento
            # partido entre dos trozos espera al siguiente.
            text = pending + body.decode("utf-8", errors="replace")
            events = text.split("\n\n")
            pending = events.pop() if more else ""
            out = "".join(_translate_event(event, lang) + "\n\n" for event in events if event)
            if not more and pending:
                out += _translate_event(pending, lang)
            if out or not more:
                await send({"type": "http.response.body", "body": out.encode("utf-8"), "more_body": more})

        await self.app(scope, receive, wrapped)
