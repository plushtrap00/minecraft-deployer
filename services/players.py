"""
services/players.py - Gestión global de jugadores (ops, whitelist, bans).

Los datos de jugadores se almacenan en una carpeta .global/ dentro de servers-minecraft/,
y se sincronizan a todos los modpacks instalados.

Contiene:
- GLOBAL_DIR, PLAYER_FILES: constantes
- ensure_global_dir(): crea .global/ importando datos existentes si los hay
- read_global_file() / write_global_file(): lectura y escritura de archivos JSON
- find_player(): busca un jugador por nombre o UUID
- sync_to_all_modpacks(): copia los datos globales a todos los modpacks
- send_console_if_running(): envía comandos al servidor si está activo
"""
import ipaddress
import json
import re
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.utils import get_modpacks

GLOBAL_DIR = DEFAULT_SERVERS_PATH / ".global"
PLAYER_FILES = ["ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]

_global_dir_initialized = False

_PLAYER_NAME_RE = re.compile(r'^[A-Za-z0-9_]{1,16}$')
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')


def validate_player_name(name: str) -> str:
    """
    Valida un nombre de jugador de Minecraft (letras, números, guion bajo,
    máx. 16 caracteres — el formato real que acepta el juego). Sin esto, un
    nombre con un salto de línea termina el comando de consola actual e
    inyecta uno nuevo en la siguiente línea de stdin (ver send_console_if_running).
    """
    name = name.strip()
    if not _PLAYER_NAME_RE.match(name):
        raise ValueError("Nombre de jugador inválido: solo letras, números y _ (máx. 16 caracteres)")
    return name


def validate_ip(ip: str) -> str:
    """Valida que sea una IPv4/IPv6 real (módulo estándar ipaddress), no un string arbitrario."""
    ip = ip.strip()
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Dirección IP inválida: {ip}")
    return ip


def sanitize_reason(reason: str) -> str:
    """
    Quita saltos de línea y otros caracteres de control de un motivo de ban
    antes de mandarlo a la consola de Minecraft. Sin esto, un \\n en el motivo
    inyecta un comando de consola adicional (ver send_console_if_running).
    """
    cleaned = _CONTROL_CHARS_RE.sub('', reason).strip()
    return cleaned or "Sin motivo especificado"


def ensure_global_dir():
    """
    Crea .global/ y sus archivos JSON si no existen.
    Si un modpack ya tiene datos para ese archivo, los importa como estado inicial
    para no perder información existente.
    """
    global _global_dir_initialized
    if _global_dir_initialized and GLOBAL_DIR.exists():
        return
    GLOBAL_DIR.mkdir(exist_ok=True)
    for fname in PLAYER_FILES:
        fpath = GLOBAL_DIR / fname
        if fpath.exists():
            continue
        # Intentar importar desde el primer modpack que tenga datos
        imported = False
        for pack in get_modpacks():
            src = DEFAULT_SERVERS_PATH / pack / fname
            if src.exists():
                try:
                    data = json.loads(src.read_text(encoding="utf-8"))
                    if data:
                        fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                        imported = True
                        break
                except Exception:
                    pass
        if not imported:
            fpath.write_text("[]", encoding="utf-8")
    _global_dir_initialized = True


def read_global_file(fname: str) -> list:
    """Lee un archivo JSON global y devuelve su contenido como lista."""
    ensure_global_dir()
    try:
        return json.loads((GLOBAL_DIR / fname).read_text(encoding="utf-8"))
    except Exception:
        return []


def write_global_file(fname: str, data: list):
    """Escribe la lista dada en un archivo JSON global."""
    ensure_global_dir()
    (GLOBAL_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def find_player(data: list, name_or_uuid: str) -> int:
    """
    Busca un jugador en la lista por nombre o UUID (case-insensitive).
    Devuelve el índice, o -1 si no se encuentra.
    """
    key = name_or_uuid.lower()
    for i, entry in enumerate(data):
        if entry.get("name", "").lower() == key or entry.get("uuid", "").lower() == key:
            return i
    return -1


def sync_to_all_modpacks(fname: str, data: list) -> tuple[list, list]:
    """
    Copia el archivo JSON global a todos los modpacks instalados.
    Salta el modpack que esté corriendo actualmente para no corromper el servidor.
    Devuelve (synced, skipped).
    """
    # Import aquí para evitar import circular con process
    from services.process import mc_running_modpack

    synced, skipped = [], []
    for pack in get_modpacks():
        if pack == mc_running_modpack:
            skipped.append(pack)
            continue
        dest = DEFAULT_SERVERS_PATH / pack / fname
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        synced.append(pack)
    return synced, skipped


def send_console_if_running(modpack: str, commands: list) -> bool:
    """
    Envía comandos al servidor si el modpack indicado está activo.
    Usa '__all__' como modpack para enviar independientemente de cuál corre.
    """
    from services.process import mc_process, mc_process_lock, mc_running_modpack

    with mc_process_lock:
        if mc_process is None or mc_process.poll() is not None:
            return False
        if mc_running_modpack != modpack and modpack != "__all__":
            return False
        try:
            for cmd in commands:
                mc_process.stdin.write((cmd + "\n").encode("utf-8"))
            mc_process.stdin.flush()
            return True
        except Exception:
            return False
