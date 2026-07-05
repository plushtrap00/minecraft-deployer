"""
config.py - Constantes globales y paths de la aplicación.
"""
import os
from pathlib import Path

# SERVERS_PATH permite sobreescribir la ruta via variable de entorno,
# útil en Docker (SERVERS_PATH=/servers) sin cambiar el comportamiento por defecto.
DEFAULT_SERVERS_PATH = Path(os.environ.get("SERVERS_PATH", str(Path.home() / "servers-minecraft")))
MC_DOMAIN = os.environ.get("MC_DOMAIN", "")
DEFAULT_SERVERS_PATH.mkdir(parents=True, exist_ok=True)

# Puerto de la interfaz web. install.sh/setup.py ya preguntan por este valor
# y lo guardan en .env; antes la app ignoraba la respuesta y siempre escuchaba
# en el 8000 fijo, así que elegir otro puerto en instalación nativa no hacía nada.
WEB_PORT = int(os.environ.get("WEB_PORT", "8000"))

# API key gratuita para buscar mods en CurseForge (console.curseforge.com/#/api-keys).
# Sin esta variable, la búsqueda en CurseForge queda deshabilitada pero Modrinth
# (que no requiere key) sigue funcionando normalmente.
CURSEFORGE_API_KEY = os.environ.get("CURSEFORGE_API_KEY", "")

TEMP_DIR = Path("uploads_temp")
TEMP_DIR.mkdir(exist_ok=True)

CONFIG_EXTENSIONS = {".toml", ".cfg", ".json", ".yaml", ".yml", ".properties"}

MAX_LOG_LINES = 500

# Tiempo máximo que se espera un apagado limpio (save-all + stop) antes de
# recurrir a SIGKILL, tanto al parar el servidor a mano como al limpiar
# procesos huérfanos en el arranque del panel.
GRACEFUL_STOP_TIMEOUT_SECONDS = 30
