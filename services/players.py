"""
services/players.py - Gestión global de jugadores (ops, whitelist, bans).

Los datos de jugadores se almacenan en una carpeta .global/ dentro de servers-minecraft/,
y se sincronizan a todos los modpacks instalados.

Contiene:
- GLOBAL_DIR, PLAYER_FILES: constantes
- ensure_global_dir(): crea .global/ importando datos existentes si los hay
- read_global_file() / write_global_file(): lectura y escritura de archivos JSON
- find_player(): busca un jugador por nombre o UUID
- resolve_player() / offline_uuid(): UUID real (online) u offline de un jugador
- fill_missing_uuids(): completa las entradas guardadas sin UUID válido
- write_player_files(): escribe los archivos globales en la carpeta de un modpack
- sync_to_all_modpacks(): copia los datos globales a todos los modpacks
- send_console_if_running(): envía comandos al servidor si está activo

Minecraft descarta EN SILENCIO al arrancar cualquier entrada de ops.json,
whitelist.json o banned-players.json cuyo "uuid" no sea un UUID válido (y al
volver a guardar el archivo la borra): un op añadido con "uuid": "" nunca
llegaba a ser op en el juego. Por eso cada jugador se guarda con su UUID.
"""
import hashlib
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuid_lib
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.utils import get_modpacks

GLOBAL_DIR = DEFAULT_SERVERS_PATH / ".global"
PLAYER_FILES = ["ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]

_global_dir_initialized = False

_PLAYER_NAME_RE = re.compile(r'^[A-Za-z0-9_]{1,16}$')
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')

# Archivos cuyas entradas son jugadores (con uuid); banned-ips.json no.
PROFILE_FILES = ("ops.json", "whitelist.json", "banned-players.json")

_MOJANG_PROFILE_URL = "https://api.mojang.com/users/profiles/minecraft/"
_MOJANG_TIMEOUT = 6
_USER_AGENT = "minecraft-deployer/1.0 (player lookup)"


class PlayerLookupError(Exception):
    """No se pudo contactar con Mojang para resolver el UUID."""


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
        pack_data = _data_for_pack(fname, data, _pack_online_mode(pack))
        dest.write_text(json.dumps(pack_data, indent=2, ensure_ascii=False), encoding="utf-8")
        synced.append(pack)
    return synced, skipped


def is_valid_uuid(value) -> bool:
    try:
        uuid_lib.UUID(str(value))
        return True
    except ValueError:
        return False


def offline_uuid(name: str) -> str:
    """
    UUID que da Minecraft a un jugador en un servidor con online-mode=false:
    el mismo cálculo que UUID.nameUUIDFromBytes("OfflinePlayer:" + nombre) en
    Java (MD5 con los bits de versión 3).
    """
    digest = hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest()
    return str(uuid_lib.UUID(bytes=digest, version=3))


def _uuid_from_usercache(name: str):
    """Busca el jugador en los usercache.json de los modpacks (sin red)."""
    key = name.lower()
    for pack in get_modpacks():
        try:
            entries = json.loads((DEFAULT_SERVERS_PATH / pack / "usercache.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in entries if isinstance(entries, list) else []:
            if str(entry.get("name", "")).lower() == key and is_valid_uuid(entry.get("uuid")):
                return {"uuid": str(uuid_lib.UUID(entry["uuid"])), "name": entry["name"]}
    return None


def _uuid_from_mojang(name: str):
    """
    Pregunta a Mojang por la cuenta. Devuelve {"uuid", "name"} con el nombre
    tal y como está escrito en la cuenta, None si no existe, o lanza
    PlayerLookupError si no hay forma de saberlo (sin red, límite de peticiones...).
    """
    req = urllib.request.Request(
        _MOJANG_PROFILE_URL + urllib.parse.quote(name),
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_MOJANG_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as e:
        if e.code in (204, 404):
            return None
        raise PlayerLookupError(f"Mojang respondió con un error (HTTP {e.code})") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PlayerLookupError("no se pudo contactar con Mojang") from e
    if not body:
        return None
    try:
        data = json.loads(body)
        return {"uuid": str(uuid_lib.UUID(data["id"])), "name": data.get("name") or name}
    except (ValueError, KeyError, TypeError) as e:
        raise PlayerLookupError("Mojang devolvió una respuesta inesperada") from e


def _pack_online_mode(pack: str) -> bool:
    """Lee online-mode de server.properties (true si no está o no se puede leer)."""
    try:
        text = (DEFAULT_SERVERS_PATH / pack / "server.properties").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "online-mode":
            return value.strip().lower() != "false"
    return True


def any_offline_modpack() -> bool:
    return any(not _pack_online_mode(pack) for pack in get_modpacks())


def resolve_player(name: str) -> dict:
    """
    Devuelve {"uuid", "name"} para guardar en los archivos de jugadores.
    Primero mira los usercache.json y después pregunta a Mojang. Si la cuenta
    no existe o Mojang no responde, solo se acepta cuando algún servidor está
    en modo offline (ahí vale el UUID offline, que no necesita cuenta); si no,
    lanza ValueError o PlayerLookupError con un mensaje para el usuario.
    """
    found = _uuid_from_usercache(name)
    if found:
        return found
    try:
        found = _uuid_from_mojang(name)
    except PlayerLookupError as e:
        if any_offline_modpack():
            return {"uuid": offline_uuid(name), "name": name}
        raise PlayerLookupError(
            f"No se pudo comprobar la cuenta de {name}: {e}. Inténtalo de nuevo en un momento."
        ) from e
    if found:
        return found
    if any_offline_modpack():
        return {"uuid": offline_uuid(name), "name": name}
    raise ValueError(f"No existe ninguna cuenta de Minecraft llamada {name}")


def fill_missing_uuids(data: list) -> bool:
    """
    Completa el UUID de las entradas que no tienen uno válido (las que el
    panel guardaba antes con "uuid": ""). Las que no se pueden resolver se
    dejan como están. Devuelve True si cambió algo.
    """
    changed = False
    for entry in data:
        name = entry.get("name")
        if not name or is_valid_uuid(entry.get("uuid")):
            continue
        try:
            found = _uuid_from_usercache(name) or _uuid_from_mojang(name)
        except PlayerLookupError:
            found = None
        if found:
            entry["uuid"] = found["uuid"]
            changed = True
    return changed


def _data_for_pack(fname: str, data: list, online: bool) -> list:
    """En un servidor offline los jugadores se identifican por su UUID offline."""
    if online or fname not in PROFILE_FILES:
        return data
    return [{**entry, "uuid": offline_uuid(entry["name"])} if entry.get("name") else entry for entry in data]


def write_player_files(pack: str) -> list:
    """
    Escribe los archivos globales de jugadores en la carpeta de un modpack
    nuevo, adaptando los UUID si el servidor está en modo offline. Devuelve
    los archivos escritos (los vacíos se saltan).
    """
    online = _pack_online_mode(pack)
    written = []
    for fname in PLAYER_FILES:
        data = read_global_file(fname)
        if not data:
            continue
        (DEFAULT_SERVERS_PATH / pack / fname).write_text(
            json.dumps(_data_for_pack(fname, data, online), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written.append(fname)
    return written


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
