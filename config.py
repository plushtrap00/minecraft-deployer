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

TEMP_DIR = Path("uploads_temp")
TEMP_DIR.mkdir(exist_ok=True)

CONFIG_EXTENSIONS = {".toml", ".cfg", ".json", ".yaml", ".yml", ".properties"}

MAX_LOG_LINES = 500
