"""
services/busy.py - Registro de operaciones en curso que no deben interrumpirse
(subir/instalar mods, cambiar modloader, crear servidores, descargar
modpacks...). Lo usa services/auto_update.py para no hacer pull + reiniciar
la app mientras hay algo así en marcha, sin que le importe qué endpoint lo
esté haciendo.
"""
import threading

_lock = threading.Lock()
_active: dict = {}  # token único por operación -> descripción legible


class BusyGuard:
    """Uso: `with BusyGuard("subiendo mod X"):` alrededor de cualquier tramo que no deba interrumpirse."""

    def __init__(self, reason: str):
        self.reason = reason
        self._token = object()

    def __enter__(self):
        with _lock:
            _active[self._token] = self.reason
        return self

    def __exit__(self, *exc_info):
        with _lock:
            _active.pop(self._token, None)
        return False


def is_busy() -> bool:
    with _lock:
        return bool(_active)


def busy_reasons() -> list:
    with _lock:
        return list(_active.values())
