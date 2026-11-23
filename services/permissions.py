"""
services/permissions.py - Qué puede hacer cada rol.

- admin: todo.
- user: todo menos cuentas, firewall y configuración del panel (eso lo cortan
  las propias rutas con require_admin).
- limited: lo ve todo, pero solo puede encender, parar y reiniciar el
  servidor, gestionar la lista blanca y su propia cuenta. Pensado para dar
  acceso a un amigo sin que pueda tocar mods, mundos, copias ni la consola.

El rol limitado se comprueba en el middleware (main.py) con una lista de lo
permitido: una ruta nueva que cambie algo queda cerrada para él por defecto.
"""
from services import activity

ROLES = ("user", "limited")  # los que se pueden dar a una cuenta (admin solo hay uno)

# Acciones del registro de actividad (services/activity.py) que sí puede hacer.
LIMITED_ACTIONS = {
    "server.start", "server.stop", "server.restart",
    "players.whitelist_add", "players.whitelist_remove",
    "auth.password", "auth.2fa_on", "auth.2fa_off", "auth.2fa_codes",
}

# Peticiones que cambian algo pero no salen en el registro: solo de su cuenta.
LIMITED_SAFE = {
    ("POST", "/api/auth/2fa/setup"),
    ("POST", "/api/auth/achievements"),
    ("POST", "/api/auth/language"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/server/metrics/refresh"),
}

LIMITED_DENIED_MESSAGE = ("Tu cuenta es limitada: puedes mirarlo todo, pero solo encender, parar y "
                          "reiniciar el servidor y gestionar la lista blanca")


def allowed(role: str | None, method: str, path: str) -> bool:
    """¿Puede ese rol hacer esta petición? (las de admin las corta cada ruta)."""
    if role != "limited":
        return True
    method = method.upper()
    found = activity.match(method, path)
    if found:
        # Incluye los GET que cambian algo (instalaciones por SSE...).
        return found[0] in LIMITED_ACTIONS
    if method in ("GET", "HEAD"):
        # Mirar sí; llevarse el mundo, las copias o los mods, no.
        return not path.rstrip("/").endswith("/download")
    return (method, path) in LIMITED_SAFE


def mask_secrets(properties: str) -> str:
    """server.properties sin la contraseña de RCON (para las cuentas limitadas)."""
    lines = []
    for line in properties.splitlines(keepends=True):
        if line.split("=", 1)[0].strip() == "rcon.password":
            ending = "\n" if line.endswith("\n") else ""
            line = "rcon.password=********" + ending
        lines.append(line)
    return "".join(lines)
