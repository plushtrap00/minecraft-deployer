"""
routes/deps.py - Validación compartida de nombres de modpack y de mundo.

Todos los endpoints /api/modpacks/{modpack}/... construyen rutas con el nombre
que llega en la URL. Sin validarlo, un nombre como ".." (que llega tal cual
si el cliente lo envía codificado como %2E%2E) apunta a la carpeta PADRE de
DEFAULT_SERVERS_PATH, y desde ahí se podía leer, sobrescribir o borrar lo que
hubiera al lado. En vez de repetir la comprobación en cada endpoint, los
routers con {modpack} en la ruta declaran `dependencies=[Depends(valid_modpack)]`.
"""
import re
from pathlib import Path

from fastapi import HTTPException, Request

from config import DEFAULT_SERVERS_PATH

# Separadores de ruta y caracteres de control: nada de eso puede formar parte
# del nombre de UNA carpeta. Los nombres que empiezan por "." quedan fuera
# también: además de "." y "..", así se protege .global/ (datos de jugadores),
# que get_modpacks() ya excluye de la lista por el mismo motivo.
_INVALID_NAME_RE = re.compile(r'[/\\\x00-\x1f]')


def _check_folder_name(name: str, what: str) -> None:
    if not name or name.startswith(".") or _INVALID_NAME_RE.search(name):
        raise HTTPException(status_code=400, detail=f"Nombre de {what} inválido")


def modpack_path(modpack: str) -> Path:
    """Carpeta de un modpack existente. 400 si el nombre no es válido, 404 si no existe."""
    _check_folder_name(modpack, "modpack")
    path = DEFAULT_SERVERS_PATH / modpack
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="El modpack no existe")
    return path


def world_path(server_dir: Path, world_name: str) -> Path:
    """Carpeta de un mundo dentro de server_dir (sin comprobar que exista: crear un mundo también la usa)."""
    _check_folder_name(world_name, "mundo")
    return server_dir / world_name


async def valid_modpack(request: Request) -> None:
    """Dependencia de router: valida {modpack} antes de que se ejecute el endpoint."""
    modpack = request.path_params.get("modpack")
    if modpack is not None:
        modpack_path(modpack)
