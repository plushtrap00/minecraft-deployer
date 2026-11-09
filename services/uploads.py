"""
services/uploads.py - Límites de tamaño para lo que se sube al panel.

Sin límite, una subida enorme (o un «zip bomb»: pocos MB comprimidos que se
convierten en cientos de GB al abrirlos) podía llenar el disco del equipo, y
con él los mundos de todos los servidores. Dos topes, editables en
Configuración → Constantes → Subidas:
- MAX_UPLOAD_MB: lo que pesa el archivo subido.
- MAX_EXTRACTED_MB: lo que ocupará una vez descomprimido; se suma el tamaño
  declarado de cada entrada ANTES de extraer nada.
"""
import shutil
import tarfile
import zipfile
from pathlib import Path

from fastapi import HTTPException

from app_constants import MAX_UPLOAD_MB, MAX_EXTRACTED_MB

_MB = 1024 * 1024
_CHUNK = 1024 * 1024


def max_upload_bytes() -> int:
    return MAX_UPLOAD_MB * _MB


def _too_large(what: str, limit_mb: int) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"{what} supera el límite de {_format_mb(limit_mb)} (se puede cambiar en Configuración → Constantes → Subidas)",
    )


def _format_mb(mb: int) -> str:
    return f"{mb / 1024:g} GB" if mb >= 1024 else f"{mb} MB"


def copy_limited(source, dest_file, limit_bytes: int | None = None, what: str = "El archivo") -> int:
    """copyfileobj que corta con 413 en cuanto se pasa del límite. Devuelve los bytes copiados."""
    limit = max_upload_bytes() if limit_bytes is None else limit_bytes
    total = 0
    while chunk := source.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise _too_large(what, limit // _MB)
        dest_file.write(chunk)
    return total


def save_upload(upload, dest: Path) -> int:
    """Guarda un UploadFile en dest respetando MAX_UPLOAD_MB (borra lo escrito si se pasa)."""
    try:
        with open(dest, "wb") as out:
            return copy_limited(upload.file, out)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise


async def read_upload(upload) -> bytes:
    """Lee un UploadFile entero en memoria (mods sueltos) respetando MAX_UPLOAD_MB."""
    limit = max_upload_bytes()
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise _too_large("El archivo", MAX_UPLOAD_MB)
    return data


def extracted_size(archive_path: Path) -> int | None:
    """Bytes que ocupará el archivo descomprimido según su índice, o None si no se puede saber."""
    name = archive_path.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                return sum(info.file_size for info in zf.infolist())
        if name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
            with tarfile.open(archive_path, "r:*") as tf:
                return sum(m.size for m in tf.getmembers() if m.isfile())
        if name.endswith(".rar"):
            try:
                import rarfile
            except ImportError:
                return None
            with rarfile.RarFile(archive_path) as rf:
                return sum(info.file_size for info in rf.infolist())
    except (zipfile.BadZipFile, tarfile.TarError, OSError):
        return None
    except Exception:
        return None
    return None


def check_extracted_size(archive_path: Path, dest_dir: Path | None = None) -> None:
    """
    413 si el contenido descomprimido supera MAX_EXTRACTED_MB, o 507 si no
    cabe en el disco donde se va a extraer (dejando un margen de 1 GB).
    """
    size = extracted_size(archive_path)
    if size is None:
        return
    if size > MAX_EXTRACTED_MB * _MB:
        raise _too_large("El contenido descomprimido", MAX_EXTRACTED_MB)
    if dest_dir is not None:
        probe = dest_dir
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        if size + 1024 * _MB > free:
            raise HTTPException(
                status_code=507,
                detail=(
                    f"No hay espacio en disco: descomprimido ocupa {size / (1024 * _MB):.1f} GB "
                    f"y quedan {free / (1024 * _MB):.1f} GB libres"
                ),
            )
