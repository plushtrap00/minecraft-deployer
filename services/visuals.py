"""
services/visuals.py - Imágenes que solo sirven para que el panel se vea mejor:
cabezas de los jugadores y logo de cada modpack.

Nada de esto es imprescindible: si no hay internet o el servicio externo
falla, el panel dibuja una cabeza o un bloque genérico por su cuenta. Por eso
todo es "lo mejor posible" y nunca lanza errores hacia fuera.

- Cabezas: se piden a mc-heads.net (cara de 32 px con la capa del sombrero) y
  se guardan en .global/heads/ unos días, para no pedirlas en cada carga.
- Logo del modpack: server-icon.png si el servidor tiene (es lo que ven los
  jugadores en su lista de servidores) o, si no, el logo de Modrinth o
  CurseForge que se descarga al instalar el modpack desde ahí.
"""
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from config import DEFAULT_SERVERS_PATH

HEADS_DIR = DEFAULT_SERVERS_PATH / ".global" / "heads"
HEAD_TTL_SECONDS = 3 * 86400
# Si mc-heads.net no responde, no se vuelve a intentar con ese jugador hasta
# pasado un rato: una lista de 30 jugadores sin red serían 30 esperas.
_HEAD_RETRY_SECONDS = 600
_HEAD_URL = "https://mc-heads.net/avatar/{key}/32"
_TIMEOUT = 5
_USER_AGENT = "minecraft-deployer/1.0 (panel images)"
_MAX_IMAGE_BYTES = 1024 * 1024

PACK_ICON_DIR = ".mcdeployer"
PACK_ICON_NAME = "icon"

_failed_heads: dict[str, float] = {}

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF8", "image/gif", "gif"),
)


def image_type(data: bytes) -> tuple[str, str] | None:
    """(media type, extensión) si los bytes son una imagen conocida."""
    for magic, media, ext in _SIGNATURES:
        if data.startswith(magic):
            return media, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _download_image(url: str) -> bytes | None:
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read(_MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if len(data) > _MAX_IMAGE_BYTES or not image_type(data):
        return None
    return data


# -- Cabezas -------------------------------------------------------------------
def head_cache_key(name: str, uuid: str | None) -> str:
    """
    Con una cuenta premium (UUID versión 4) la cabeza va por UUID, que no
    cambia aunque el jugador se cambie el nombre. En servidores sin
    online-mode el UUID es inventado (versión 3) y no lleva a ninguna skin:
    ahí se busca por nombre.
    """
    if uuid:
        compact = uuid.replace("-", "").lower()
        if len(compact) == 32 and compact[12] == "4" and all(c in "0123456789abcdef" for c in compact):
            return compact
    return name.lower()


def player_head(name: str, uuid: str | None = None) -> bytes | None:
    key = head_cache_key(name, uuid)
    path = HEADS_DIR / f"{key}.png"
    try:
        fresh = time.time() - path.stat().st_mtime < HEAD_TTL_SECONDS
    except OSError:
        fresh = False
    if fresh:
        return path.read_bytes()
    if time.time() - _failed_heads.get(key, 0) > _HEAD_RETRY_SECONDS:
        data = _download_image(_HEAD_URL.format(key=urllib.parse.quote(key)))
        if data:
            HEADS_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            _failed_heads.pop(key, None)
            return data
        _failed_heads[key] = time.time()
    # Sin red: mejor una cabeza de hace una semana que ninguna.
    try:
        return path.read_bytes()
    except OSError:
        return None


# -- Logo del modpack -----------------------------------------------------------
def pack_icon_path(server_dir: Path) -> Path | None:
    server_icon = server_dir / "server-icon.png"
    if server_icon.is_file():
        return server_icon
    folder = server_dir / PACK_ICON_DIR
    if folder.is_dir():
        for candidate in sorted(folder.glob(PACK_ICON_NAME + ".*")):
            if candidate.is_file():
                return candidate
    return None


def save_pack_icon(server_dir: Path, url: str | None) -> bool:
    """Descarga el logo de la tienda y lo deja junto al servidor. Nunca falla hacia fuera."""
    if not url:
        return False
    data = _download_image(url)
    kind = image_type(data) if data else None
    if not data or not kind:
        return False
    ext = kind[1]
    try:
        folder = server_dir / PACK_ICON_DIR
        folder.mkdir(exist_ok=True)
        (folder / f"{PACK_ICON_NAME}.{ext}").write_bytes(data)
    except OSError:
        return False
    return True
