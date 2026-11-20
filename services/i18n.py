"""
services/i18n.py - Idiomas del panel: español de España (el original) e inglés.

Todo el panel está escrito en español. Las traducciones son un mapa de
frases en static/i18n/<idioma>.json: {"Frase en español": "Translation"}.
Frases enteras y no palabras sueltas, porque palabra a palabra el orden y el
sentido cambian («El servidor se ha caído» no es «The server itself has
fallen»). Lo que no está en el mapa se queda en español: nunca sale nada roto.

- El HTML se traduce aquí, al montar la página (translate_html): textos entre
  etiquetas y los atributos placeholder/title/aria-label/alt. Una frase con
  etiquetas dentro («Los cambios <strong>no se aplican</strong>…») va en el
  mapa con sus etiquetas tal cual, porque partida en trozos no se traduce bien.
- El JavaScript usa t('Frase') (static/js/i18n.js) con el mismo mapa, que se
  sirve como /i18n/<idioma>.js.
- Las frases con datos llevan huecos: «Mira tu {canal}» → «Check your {canal}».

Idioma de cada petición (request_lang): la cookie mcd-lang (lo que el usuario
eligió en Apariencia), si no APP_LANGUAGE del .env (lo que se eligió al
instalar o en Configuración), si no el idioma del navegador, y si no español.
"""
import json
import os
import re
from pathlib import Path

LANGS = ("es", "en")
DEFAULT_LANG = "es"
COOKIE_NAME = "mcd-lang"

I18N_DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"

_TRANSLATED_ATTRS = ("placeholder", "title", "aria-label", "alt")
# Trozos del HTML: comentarios, <script>/<style> enteros (no se tocan) y
# etiquetas sueltas; lo que queda entre ellos es texto.
_TOKEN_RE = re.compile(
    r"(<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)",
    re.DOTALL | re.IGNORECASE,
)
_ATTR_RE = re.compile(r'\b(' + "|".join(_TRANSLATED_ATTRS) + r')="([^"]*)"')
_LETTER_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
_PARAM_RE = re.compile(r"\{(\w+)\}")
# Nombres técnicos que se quedan igual en todos los idiomas: sin minúsculas
# (GB, WARN, JWT_SECRET, ERROR / FATAL) o una sola palabra con signos o
# números (startup_scripts/, .jar, -Xms, user_jvm_args.txt).
_LOWER_RE = re.compile(r"[a-záéíóúüñ]")
_TECHNICAL_TOKEN_RE = re.compile(r"^\S*[./_\-:#0-9]\S*$")

_cache: dict = {}


def normalize(text: str) -> str:
    """Las frases se buscan sin importar saltos de línea ni espacios de más."""
    return " ".join(text.split())


def load(lang: str) -> dict:
    """El mapa de un idioma (vacío para el español), releído si cambia en disco."""
    if lang not in LANGS or lang == DEFAULT_LANG:
        return {}
    path = I18N_DIR / f"{lang}.json"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _cache.get(lang)
    if cached and cached[0] == mtime:
        return cached[1]
    raw = json.loads(path.read_text(encoding="utf-8"))
    table = {normalize(key): value for key, value in raw.items() if not key.startswith("//")}
    _cache[lang] = (mtime, table)
    return table


def t(text: str, lang: str, **params) -> str:
    """Una frase en el idioma pedido, con sus huecos {nombre} rellenos."""
    result = load(lang).get(normalize(text), text)
    if params:
        result = _PARAM_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), result)
    return result


def _pick(value) -> str | None:
    value = (value or "").strip().lower()[:2]
    return value if value in LANGS else None


pick_lang = _pick


# ── Mensajes del backend ──────────────────────────────────────────────────────
# Los errores y avisos se escriben en español en el código, a menudo con datos
# dentro (f"{name} ya es op"). En en.json van como plantillas con huecos
# ("{name} ya es op": "{name} is already an op"): si un mensaje no está tal
# cual, se busca la plantilla que encaje, y lo que ocupa cada hueco se
# traduce a su vez (puede ser otro mensaje: "No se pudo X: {error}").

_templates_cache: dict = {}
_MAX_DEPTH = 4


def _templates(lang: str) -> list:
    table = load(lang)
    cached = _templates_cache.get(lang)
    if cached and cached[0] is table:
        return cached[1]
    compiled = []
    for key, value in table.items():
        if "{" not in key or not _PARAM_RE.search(key):
            continue
        literal = _PARAM_RE.sub("", key)
        if len(_LETTER_RE.findall(literal)) < 4:
            continue  # casi todo huecos («Los {days}»): encajaría con demasiadas cosas
        names: list = []
        pattern = ""
        pos = 0
        for match in _PARAM_RE.finditer(key):
            pattern += re.escape(key[pos:match.start()]).replace(r"\ ", r"\s+")
            name = match.group(1)
            group = f"g{len(names)}"
            names.append(name)
            pattern += f"(?P<{group}>.+?)"
            pos = match.end()
        pattern += re.escape(key[pos:]).replace(r"\ ", r"\s+")
        compiled.append((len(literal), re.compile(pattern + r"\Z", re.S), names, value))
    # Primero las plantillas con más texto fijo: son las más concretas.
    compiled.sort(key=lambda item: -item[0])
    _templates_cache[lang] = (table, compiled)
    return compiled


def translate_message(text, lang: str, _depth: int = 0):
    """Un mensaje del backend en el idioma pedido (igual si no se conoce)."""
    if not isinstance(text, str) or not text or lang not in LANGS or lang == DEFAULT_LANG:
        return text
    table = load(lang)
    key = normalize(text)
    if key in table:
        return table[key]
    if _depth >= _MAX_DEPTH or not _LETTER_RE.search(key):
        return text
    for _, pattern, names, value in _templates(lang):
        match = pattern.match(key)
        if not match:
            continue
        params = {}
        for index, name in enumerate(names):
            params.setdefault(name, translate_message(match.group(f"g{index}"), lang, _depth + 1))
        return _PARAM_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    # Dentro de un hueco puede ir una lista («subiendo mod a 'X', clonando Y»):
    # se traduce cada elemento.
    if _depth > 0 and ", " in key:
        parts = key.split(", ")
        translated = [translate_message(part, lang, _depth + 1) for part in parts]
        if translated != parts:
            return ", ".join(translated)
    return text


# Campos de las respuestas JSON y de los eventos SSE que llevan texto para
# la persona (mensajes, errores, motivos). Los datos (nombres, rutas,
# contenidos de archivos) no se tocan.
MESSAGE_FIELDS = frozenset({"detail", "message", "reason", "reason_label", "error", "last_error", "results"})


def translate_payload(data, lang: str, _in_field: bool = False):
    """Traduce los campos de MESSAGE_FIELDS dentro de un JSON (dicts y listas anidados)."""
    if lang == DEFAULT_LANG:
        return data
    if isinstance(data, dict):
        return {k: translate_payload(v, lang, _in_field or k in MESSAGE_FIELDS) for k, v in data.items()}
    if isinstance(data, list):
        return [translate_payload(item, lang, _in_field) for item in data]
    if _in_field and isinstance(data, str):
        return translate_message(data, lang)
    return data


def browser_lang(accept_language: str) -> str | None:
    """El primero de los idiomas del navegador que el panel tiene."""
    weighted = []
    for position, part in enumerate((accept_language or "").split(",")):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        weighted.append((-weight, position, tag))
    for _, _, tag in sorted(weighted):
        lang = _pick(tag)
        if lang:
            return lang
    return None


def default_lang() -> str:
    return _pick(os.environ.get("APP_LANGUAGE")) or DEFAULT_LANG


def _session_user(request) -> str | None:
    user = getattr(getattr(request, "state", None), "user", None)
    if user:
        return user
    try:
        from routes.auth import token_from_request, verify_token  # import tardío: evita el ciclo
        info = verify_token(token_from_request(request))
    except Exception:  # noqa: BLE001 — sin sesión válida, se sigue con la cookie
        return None
    return info.get("sub") if info else None


def request_lang(request, use_account: bool = True) -> str:
    """Idioma de la cuenta con sesión > cookie > APP_LANGUAGE > navegador > es."""
    if use_account:
        user = _session_user(request)
        if user:
            from services import user_prefs
            saved = _pick(user_prefs.get_lang(user))
            if saved:
                return saved
    return (
        _pick(request.cookies.get(COOKIE_NAME))
        or _pick(os.environ.get("APP_LANGUAGE"))
        or browser_lang(request.headers.get("accept-language", ""))
        or DEFAULT_LANG
    )


# ── HTML ──────────────────────────────────────────────────────────────────────

def _html_phrases(table: dict) -> list:
    """Frases del mapa que llevan etiquetas dentro, de la más larga a la más corta."""
    return sorted((key for key in table if "<" in key), key=len, reverse=True)


def _phrase_pattern(key: str) -> re.Pattern:
    # El HTML de los trozos parte las frases largas en varias líneas.
    parts = [re.escape(word) for word in key.split()]
    return re.compile(r"\s+".join(parts))


def needs_translation(text: str) -> bool:
    """Si un texto es una frase a traducir (y no un número o nombre técnico)."""
    text = text.strip()
    return bool(_LOWER_RE.search(text)) and not _TECHNICAL_TOKEN_RE.match(text)


def _translate_text(text: str, table: dict, missing: list | None) -> str:
    core = text.strip()
    if not core or not _LETTER_RE.search(core):
        return text
    translated = table.get(normalize(core))
    if translated is None:
        if missing is not None and needs_translation(core):
            missing.append(normalize(core))
        return text
    start = text.index(core[0])
    return text[:start] + translated + text[start + len(core):]


def _translate_tag(tag: str, table: dict, missing: list | None) -> str:
    if tag.startswith("<!--") or tag[:7].lower() in ("<script", "<style"):
        return tag

    def replace(match):
        value = match.group(2)
        if not _LETTER_RE.search(value):
            return match.group(0)
        translated = table.get(normalize(value))
        if translated is None:
            if missing is not None and needs_translation(value):
                missing.append(normalize(value))
            return match.group(0)
        return f'{match.group(1)}="{translated}"'

    return _ATTR_RE.sub(replace, tag)


def translate_html(html: str, lang: str, missing: list | None = None, table: dict | None = None) -> str:
    """
    El HTML del panel en otro idioma. Si se pasa `missing`, se le añaden las
    frases que no tienen traducción (lo usan los tests para vigilar que no se
    quede nada en español).
    """
    if table is None:
        table = load(lang)
    if not table and missing is None:
        return html

    # Primero las frases con etiquetas dentro, enteras, para que el paso de
    # texto suelto no las parta. Se apartan tras un marcador sin letras y se
    # devuelven al final, para que ese paso no revise sus trozos ya traducidos.
    done: list = []

    def stash(value: str) -> str:
        done.append(value)
        return f"\x00{len(done) - 1}\x00"

    for key in _html_phrases(table):
        html = _phrase_pattern(key).sub(lambda _m, value=table[key]: stash(value), html)

    out = []
    for piece in _TOKEN_RE.split(html):
        if not piece:
            continue
        if piece.startswith("<"):
            out.append(_translate_tag(piece, table, missing))
        else:
            out.append(_translate_text(piece, table, missing))
    return re.sub(r"\x00(\d+)\x00", lambda m: done[int(m.group(1))], "".join(out))


def untranslated(html: str, lang: str) -> list:
    """Frases del HTML que no tienen traducción a `lang` (sin repetir)."""
    missing: list = []
    translate_html(html, lang, missing=missing)
    seen = set()
    return [m for m in missing if not (m in seen or seen.add(m))]
