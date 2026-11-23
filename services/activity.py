"""
services/activity.py - Registro de actividad: quién hizo qué y cuándo.

Se guarda en SERVERS_PATH/.global/activity.jsonl, una línea JSON por acción:
  {"ts", "user", "ip", "action", "params", "detail"}
con las últimas MAX_ENTRIES (al pasarse de largo se recorta).

Cómo se rellena:
- AuthMiddleware (main.py) llama a record_request() tras cada petición que
  ha salido bien: ROUTES dice qué acción es según el método y la ruta; los
  parámetros salen de la propia ruta y de la query (?name=...).
- Si el detalle va en el cuerpo (el comando de la consola, el jugador...),
  el endpoint lo deja en request.state.activity_params / activity_detail, y
  puede cambiar la acción con activity_action (activar o desactivar un mod).
- Lo que no pasa por una petición (copias automáticas, reinicios tras una
  caída, tareas programadas) y las entradas al panel llaman a record().

ACTIONS da la categoría y el texto de cada acción (en español; el panel lo
traduce con t()). tests/test_activity.py comprueba que todos están en en.json.
"""
import json
import re
import threading
import time

from config import DEFAULT_SERVERS_PATH

ACTIVITY_FILE = DEFAULT_SERVERS_PATH / ".global" / "activity.jsonl"
MAX_ENTRIES = 5000
SYSTEM_USER = ""  # acciones automáticas (sin persona detrás)

ACTIONS = {
    # Servidor
    "server.start": ("server", "Encendió {modpack}"),
    "server.stop": ("server", "Paró {modpack}"),
    "server.restart": ("server", "Reinició {modpack}"),
    "server.command": ("server", "Mandó un comando a la consola"),
    "server.crash_restart": ("server", "Reinicio automático de {modpack} tras una caída"),
    "server.idle_stop": ("server", "Apagó {modpack} tras {minutes} min sin nadie conectado"),
    # Jugadores
    "players.op": ("players", "Hizo operador a {name}"),
    "players.deop": ("players", "Quitó de operadores a {name}"),
    "players.whitelist_add": ("players", "Añadió a {name} a la lista blanca"),
    "players.whitelist_remove": ("players", "Quitó a {name} de la lista blanca"),
    "players.ban": ("players", "Baneó a {name}"),
    "players.unban": ("players", "Quitó el baneo a {name}"),
    "players.ban_ip": ("players", "Baneó la IP {ip}"),
    "players.unban_ip": ("players", "Quitó el baneo a la IP {ip}"),
    # Modpacks y archivos
    "modpack.install": ("install", "Empezó a instalar el modpack {name}"),
    "modpack.create": ("install", "Empezó a crear el servidor {name}"),
    "modpack.upload": ("install", "Subió un modpack"),
    "modpack.delete": ("files", "Borró el modpack {modpack}"),
    "modpack.clone": ("files", "Clonó {modpack}"),
    "modpack.update": ("install", "Empezó a actualizar {modpack} a otra versión de su modpack"),
    "modpack.link": ("install", "Vinculó {modpack} a su modpack"),
    "modpack.properties": ("files", "Cambió server.properties de {modpack}"),
    "modpack.ram": ("files", "Cambió la RAM de {modpack}"),
    "modpack.config_file": ("files", "Editó la configuración de {modpack}"),
    "modpack.kubejs": ("files", "Cambió los scripts de KubeJS de {modpack}"),
    "modpack.kubejs_delete": ("files", "Borró un script de KubeJS de {modpack}"),
    "modpack.world_file": ("files", "Editó un archivo del mundo de {modpack}"),
    "modpack.modloader": ("install", "Empezó a cambiar la versión del modloader de {modpack}"),
    "worlds.activate": ("files", "Cambió el mundo activo de {modpack}"),
    "worlds.create": ("files", "Creó un mundo nuevo en {modpack}"),
    "worlds.upload": ("files", "Subió un mundo a {modpack}"),
    "worlds.delete": ("files", "Borró el mundo {world_name} de {modpack}"),
    # Mods
    "mods.install": ("mods", "Instaló un mod en {modpack}"),
    "mods.upload": ("mods", "Subió mods a {modpack}"),
    "mods.delete": ("mods", "Borró el mod {filename} de {modpack}"),
    "mods.toggle": ("mods", "Activó o desactivó {filename} en {modpack}"),
    "mods.enable": ("mods", "Activó {filename} en {modpack}"),
    "mods.disable": ("mods", "Desactivó {filename} en {modpack}"),
    "mods.delete_disabled": ("mods", "Borró los mods deshabilitados de {modpack}"),
    "mods.dependencies": ("mods", "Empezó a instalar las dependencias que faltaban en {modpack}"),
    "mods.update": ("mods", "Actualizó un mod de {modpack}"),
    "mods.update_undo": ("mods", "Deshizo actualizaciones de mods en {modpack}"),
    # Copias
    "backups.create": ("backups", "Hizo una copia de {modpack}"),
    "backups.restore": ("backups", "Restauró la copia {name} de {modpack}"),
    "backups.delete": ("backups", "Borró la copia {name} de {modpack}"),
    "backups.auto": ("backups", "Copia automática de {modpack}"),
    # Automatización
    "automation.settings": ("automation", "Cambió los ajustes de automatización"),
    "automation.task_save": ("automation", "Guardó una tarea programada"),
    "automation.task_delete": ("automation", "Borró una tarea programada"),
    "automation.task_run": ("automation", "Ejecutó una tarea programada a mano"),
    "automation.task": ("automation", "Se ejecutó una tarea programada"),
    "automation.mirror": ("automation", "Cambió el destino secundario de las copias"),
    # Cuentas y seguridad
    "auth.login": ("security", "Entró en el panel"),
    "auth.login_recovery": ("security", "Entró en el panel con un código de recuperación"),
    "auth.login_failed": ("security", "Intento de entrada fallido como {name}"),
    "auth.password": ("security", "Cambió su contraseña"),
    "auth.2fa_on": ("security", "Activó la verificación en dos pasos"),
    "auth.2fa_off": ("security", "Desactivó la verificación en dos pasos"),
    "auth.2fa_codes": ("security", "Creó códigos de recuperación nuevos"),
    "users.create": ("users", "Creó la cuenta {name}"),
    "users.delete": ("users", "Borró la cuenta {username}"),
    "users.password": ("users", "Cambió la contraseña de {username}"),
    "users.role": ("users", "Cambió el rol de {username}"),
    "users.role_limited": ("users", "Dejó la cuenta {username} como limitada"),
    "users.role_user": ("users", "Dio acceso completo a {username}"),
    "users.2fa_remove": ("users", "Quitó la verificación en dos pasos a {username}"),
    # Panel
    "config.constants": ("config", "Cambió las constantes"),
    "config.env": ("config", "Cambió las variables de entorno"),
    "config.notifications": ("config", "Cambió los avisos de Telegram y Discord"),
    "config.restart": ("config", "Reinició el panel"),
    "config.update": ("config", "Actualizó el panel"),
    "config.firewall": ("config", "Cambió quién puede entrar al servidor de Minecraft"),
}

CATEGORIES = ("server", "players", "mods", "files", "install", "backups", "automation", "users", "security", "config")

# (método, ruta) → acción. {x} es un trozo de la ruta que pasa a los parámetros.
ROUTES = [
    ("POST", "/api/server/start", "server.start"),
    ("POST", "/api/server/stop", "server.stop"),
    ("POST", "/api/server/restart", "server.restart"),
    ("POST", "/api/server/command", "server.command"),
    ("POST", "/api/players/op", "players.op"),
    ("DELETE", "/api/players/op/{name}", "players.deop"),
    ("POST", "/api/players/whitelist", "players.whitelist_add"),
    ("DELETE", "/api/players/whitelist/{name}", "players.whitelist_remove"),
    ("POST", "/api/players/ban", "players.ban"),
    ("DELETE", "/api/players/ban/{name}", "players.unban"),
    ("POST", "/api/players/ban-ip", "players.ban_ip"),
    ("DELETE", "/api/players/ban-ip/{ip}", "players.unban_ip"),
    ("GET", "/api/modpack-install/stream", "modpack.install"),
    ("GET", "/api/create-server/stream", "modpack.create"),
    ("POST", "/api/upload-and-extract", "modpack.upload"),
    ("DELETE", "/api/modpacks/{modpack}", "modpack.delete"),
    ("POST", "/api/modpacks/{modpack}/clone", "modpack.clone"),
    ("GET", "/api/modpacks/{modpack}/pack-update/stream", "modpack.update"),
    ("POST", "/api/modpacks/{modpack}/pack-source", "modpack.link"),
    ("POST", "/api/modpacks/{modpack}/server-properties", "modpack.properties"),
    ("POST", "/api/modpacks/{modpack}/server-property", "modpack.properties"),
    ("POST", "/api/modpacks/{modpack}/ram", "modpack.ram"),
    ("POST", "/api/modpacks/{modpack}/config-file", "modpack.config_file"),
    ("POST", "/api/modpacks/{modpack}/kubejs-file", "modpack.kubejs"),
    ("POST", "/api/modpacks/{modpack}/kubejs-new", "modpack.kubejs"),
    ("POST", "/api/modpacks/{modpack}/kubejs-move", "modpack.kubejs"),
    ("DELETE", "/api/modpacks/{modpack}/kubejs-file", "modpack.kubejs_delete"),
    ("POST", "/api/modpacks/{modpack}/world-file", "modpack.world_file"),
    ("GET", "/api/modpacks/{modpack}/modloader/install/stream", "modpack.modloader"),
    ("POST", "/api/modpacks/{modpack}/worlds/activate", "worlds.activate"),
    ("POST", "/api/modpacks/{modpack}/worlds/create", "worlds.create"),
    ("POST", "/api/modpacks/{modpack}/worlds/upload", "worlds.upload"),
    ("DELETE", "/api/modpacks/{modpack}/worlds/{world_name}", "worlds.delete"),
    ("POST", "/api/modpacks/{modpack}/mods/search/install", "mods.install"),
    ("POST", "/api/modpacks/{modpack}/mods/upload", "mods.upload"),
    ("POST", "/api/modpacks/{modpack}/mods/upload-bulk", "mods.upload"),
    ("DELETE", "/api/modpacks/{modpack}/mods/{filename}", "mods.delete"),
    ("POST", "/api/modpacks/{modpack}/mods/{filename}/toggle", "mods.toggle"),
    ("POST", "/api/modpacks/{modpack}/mods/delete-disabled", "mods.delete_disabled"),
    ("GET", "/api/modpacks/{modpack}/mods/dependencies/install/stream", "mods.dependencies"),
    ("POST", "/api/modpacks/{modpack}/mods/updates/apply", "mods.update"),
    ("POST", "/api/modpacks/{modpack}/mods/updates/undo", "mods.update_undo"),
    ("POST", "/api/modpacks/{modpack}/backups", "backups.create"),
    ("POST", "/api/modpacks/{modpack}/backups/{name}/restore", "backups.restore"),
    ("DELETE", "/api/modpacks/{modpack}/backups/{name}", "backups.delete"),
    ("POST", "/api/automation/settings", "automation.settings"),
    ("POST", "/api/automation/tasks", "automation.task_save"),
    ("DELETE", "/api/automation/tasks/{task_id}", "automation.task_delete"),
    ("POST", "/api/automation/tasks/{task_id}/run", "automation.task_run"),
    ("POST", "/api/automation/backup-mirror", "automation.mirror"),
    ("POST", "/api/auth/password", "auth.password"),
    ("POST", "/api/auth/2fa/enable", "auth.2fa_on"),
    ("POST", "/api/auth/2fa/disable", "auth.2fa_off"),
    ("POST", "/api/auth/2fa/recovery", "auth.2fa_codes"),
    ("POST", "/api/users", "users.create"),
    ("DELETE", "/api/users/{username}", "users.delete"),
    ("POST", "/api/users/{username}/password", "users.password"),
    ("DELETE", "/api/users/{username}/two-factor", "users.2fa_remove"),
    ("POST", "/api/users/{username}/role", "users.role"),
    ("POST", "/api/admin/constants", "config.constants"),
    ("POST", "/api/admin/env", "config.env"),
    ("POST", "/api/admin/notifications", "config.notifications"),
    ("POST", "/api/admin/restart", "config.restart"),
    ("POST", "/api/auto-update/apply", "config.update"),
    ("POST", "/api/firewall/set", "config.firewall"),
]

_QUERY_PARAMS = ("name",)


def _compile(path: str) -> re.Pattern:
    regex = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(path))
    return re.compile(f"^{regex}$")


_COMPILED = [(method, _compile(path), action) for method, path, action in ROUTES]
_lock = threading.Lock()
_writes = 0


def match(method: str, path: str) -> tuple[str, dict] | None:
    for route_method, regex, action in _COMPILED:
        if route_method == method:
            found = regex.match(path)
            if found:
                return action, dict(found.groupdict())
    return None


def _trim() -> None:
    try:
        lines = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > MAX_ENTRIES:
        ACTIVITY_FILE.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")


def record(action: str, user: str = SYSTEM_USER, params: dict | None = None,
           detail: str | None = None, ip: str | None = None) -> None:
    """Nunca falla hacia fuera: el registro no puede romper la acción registrada."""
    global _writes
    if action not in ACTIONS:
        return
    entry = {"ts": round(time.time(), 3), "user": user or SYSTEM_USER, "action": action}
    if params:
        entry["params"] = {k: str(v)[:200] for k, v in params.items() if v is not None}
    if detail:
        entry["detail"] = str(detail)[:500]
    if ip:
        entry["ip"] = ip
    try:
        with _lock:
            ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _writes += 1
            if _writes % 200 == 0:
                _trim()
    except OSError:
        pass


def record_request(request, response_status: int) -> None:
    """Desde AuthMiddleware, con la petición ya respondida."""
    if response_status >= 400:
        return
    state = request.state
    if getattr(state, "activity_skip", False):
        return
    found = match(request.method, request.url.path)
    if not found:
        return
    action, params = found
    # El endpoint puede afinar la acción (p. ej. activar o desactivar un mod).
    action = getattr(state, "activity_action", None) or action
    for key in _QUERY_PARAMS:
        if key in request.query_params and key not in params:
            params[key] = request.query_params[key]
    params.update(getattr(state, "activity_params", None) or {})
    record(action, getattr(state, "user", SYSTEM_USER), params,
           getattr(state, "activity_detail", None),
           request.client.host if request.client else None)


def read(limit: int = 100, before: float | None = None, user: str | None = None,
         category: str | None = None) -> dict:
    """Las más recientes primero. before: para paginar (ts de la última que ya tienes)."""
    try:
        lines = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    items, users = [], set()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        users.add(entry.get("user") or SYSTEM_USER)
        if before is not None and entry.get("ts", 0) >= before:
            continue
        if user is not None and (entry.get("user") or SYSTEM_USER) != user:
            continue
        cat, label = ACTIONS.get(entry.get("action"), (None, None))
        if not label or (category and cat != category):
            continue
        if len(items) < limit:
            items.append({**entry, "category": cat, "label": label})
    return {"items": items, "users": sorted(users), "more": len(items) == limit}
