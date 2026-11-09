"""
services/secure_files.py - Escritura segura de archivos.

- atomic_write_text(): escribe en un temporal de la misma carpeta y lo cambia
  por el original de una vez (os.replace). Si el proceso muere o el disco se
  llena a mitad, el archivo de antes sigue intacto en vez de quedar vacío o
  cortado (server.properties, users.json, configs de mods...).
- harden_secret_files(): .env lleva JWT_SECRET (con él se puede fabricar una
  sesión de admin) y users.json los hashes de contraseña. Con los permisos por
  defecto (644) cualquier usuario del equipo podía leerlos: se dejan en 600
  (solo el dueño) al arrancar y cada vez que se guardan.
"""
import os
import stat
import tempfile
from pathlib import Path

_APP_DIR = Path(__file__).parent.parent
SECRET_FILES = (_APP_DIR / ".env", _APP_DIR / "users.json")
_PRIVATE_MODE = 0o600


def restrict_permissions(path: Path) -> bool:
    """chmod 600 si el archivo existe y no lo tiene ya. True si lo cambió."""
    if os.name != "posix":
        return False
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current & 0o077 == 0:
            return False
        os.chmod(path, _PRIVATE_MODE)
        return True
    except OSError:
        # No existe, o es un montaje de solo lectura (Docker): nada que hacer.
        return False


def harden_secret_files() -> list:
    """Deja .env y users.json solo legibles por su dueño. Devuelve los que se cambiaron."""
    return [p.name for p in SECRET_FILES if restrict_permissions(p)]


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8", private: bool = False) -> None:
    """
    Escribe text en path de forma atómica. Conserva los permisos que ya tuviera
    el archivo (un run.sh sigue siendo ejecutable); con private=True lo deja en 600.
    """
    path = Path(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = None
    if private:
        mode = _PRIVATE_MODE

    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        elif os.name == "posix":
            # mkstemp crea con 600: un archivo nuevo normal queda como lo
            # dejaría open() (644 con la umask habitual).
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp_name, 0o666 & ~umask)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
