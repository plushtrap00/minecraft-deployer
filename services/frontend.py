"""
services/frontend.py - Monta la página única del panel a partir de sus trozos.

static/index.html es solo el esqueleto (cabecera, estilos y scripts). Cada
página, modal y bloque repetido vive en su propio archivo bajo
static/partials/ y se mete en su sitio con un comentario:

    <!-- include: partials/pages/server.html -->

Un trozo puede incluir otros (manage.html incluye cada pestaña) y recibir
parámetros, que sustituyen los {{nombre}} del trozo; así el mismo bloque de
RAM sirve para los tres formularios de instalación con ids distintos:

    <!-- include: partials/ram-fields.html prefix=create- min=2 max=4 -->

Todo se resuelve en el servidor, así que el navegador sigue recibiendo un
único HTML y los ids, el JS y el CSS funcionan igual que antes.
"""
import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PARTIALS_DIR = STATIC_DIR / "partials"

_INCLUDE_RE = re.compile(r"<!-- include: ([\w./-]+)((?:\s+[\w-]+=[^\s>]*)*)\s*-->")
_PARAM_RE = re.compile(r"([\w-]+)=([^\s>]*)")
_PLACEHOLDER_RE = re.compile(r"\{\{([\w-]+)\}\}")
_MAX_DEPTH = 5


class PartialError(Exception):
    pass


def _resolve_path(rel: str) -> Path:
    path = (STATIC_DIR / rel).resolve()
    if PARTIALS_DIR.resolve() not in path.parents:
        raise PartialError(f"Include fuera de static/partials: {rel}")
    if not path.is_file():
        raise PartialError(f"No existe el trozo {rel}")
    return path


def _expand(text: str, depth: int) -> str:
    if depth > _MAX_DEPTH:
        raise PartialError("Demasiados includes anidados")

    def replace(match):
        params = dict(_PARAM_RE.findall(match.group(2) or ""))
        body = _resolve_path(match.group(1)).read_text(encoding="utf-8")

        def fill(placeholder):
            name = placeholder.group(1)
            if name not in params:
                raise PartialError(f"{match.group(1)}: falta el parámetro {name}")
            return params[name]

        body = _PLACEHOLDER_RE.sub(fill, body)
        return _expand(body.rstrip("\n"), depth + 1)

    return _INCLUDE_RE.sub(replace, text)


def render_index() -> str:
    """index.html con todos los trozos ya metidos."""
    return _expand((STATIC_DIR / "index.html").read_text(encoding="utf-8"), 0)
