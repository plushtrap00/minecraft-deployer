"""
setup.py - Instalador interactivo de Minecraft Server Deployer.

Configura credenciales, puertos y ruta de servidores,
y genera .env y docker-compose.yml listos para usar.

Si ya existe una configuración previa (.env / docker-compose.yml), cada
pregunta usa el valor actual como valor por defecto — para cambiar solo
una cosa (p. ej. el puerto), basta con pulsar Enter en el resto.

Uso:
    python3 setup.py
"""
import bcrypt
import getpass
import re
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
COMPOSE_FILE = Path(__file__).parent / "docker-compose.yml"


# ── Leer configuración existente (para reconfigurar sin partir de cero) ────────

def read_existing_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        values[key.strip()] = val.strip()
    return values


def read_existing_compose() -> dict:
    if not COMPOSE_FILE.exists():
        return {}
    content = COMPOSE_FILE.read_text()
    result = {}
    m = re.search(r'"(\d+):8000"', content)
    if m:
        result["web_port"] = int(m.group(1))
    m = re.search(r'"(\d+):25565"', content)
    if m:
        result["mc_port"] = int(m.group(1))
    m = re.search(r'JAVA_VERSION:\s*"(\d+)"', content)
    if m:
        result["java_version"] = m.group(1)
    # La línea del volumen de servidores es la única "- algo:/servers" del
    # archivo (la del .env es "- ./.env:/app/.env" y no matchea este patrón).
    m = re.search(r'^\s*-\s*(\S+):/servers\s*$', content, re.MULTILINE)
    if m:
        vol = m.group(1)
        result["servers_path"] = vol
        result["is_host_path"] = "/" in vol
    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        if secret:
            value = getpass.getpass(display)
        else:
            value = input(display).strip()
        if value == "" and default:
            return default
        if value:
            return value
        print("  El valor no puede estar vacío.")


def ask_int(prompt: str, default: int, min_val: int = 1, max_val: int = 65535) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"  Debe ser un número entre {min_val} y {max_val}.")
        except ValueError:
            print("  Introduce un número válido.")


def separator():
    print("\n" + "─" * 52 + "\n")


# ── Secciones del wizard ───────────────────────────────────────────────────────

def configure_credentials(existing_username: str = "", has_existing_password: bool = False) -> tuple[str, str | None]:
    """Devuelve (usuario, contraseña) — contraseña None significa "mantener la actual"."""
    print("  Configura el usuario y contraseña para acceder")
    print("  a la interfaz web de Minecraft Deployer.")
    if has_existing_password:
        print("  Deja la contraseña en blanco para mantener la actual.")
    print("")

    username = ask("  Usuario", default=existing_username or "admin")

    while True:
        display = "  Contraseña (mín. 8 caracteres, Enter = mantener la actual): " if has_existing_password \
            else "  Contraseña (mín. 8 caracteres): "
        password = getpass.getpass(display)
        if not password and has_existing_password:
            return username, None
        if len(password) < 8:
            print("  La contraseña debe tener al menos 8 caracteres.")
            continue
        confirm = getpass.getpass("  Confirmar contraseña: ")
        if password != confirm:
            print("  Las contraseñas no coinciden. Inténtalo de nuevo.")
            continue
        return username, password


def configure_ports(default_web: int = 8000, default_mc: int = 25565) -> tuple[int, int]:
    print("  Puerto de la interfaz web y del servidor Minecraft.")
    print("  Déjalos en blanco para mantener los valores actuales/por defecto.\n")

    web_port = ask_int("  Puerto web", default=default_web)
    mc_port  = ask_int("  Puerto Minecraft", default=default_mc)

    return web_port, mc_port


def configure_java(default: str = "21") -> str:
    print("  Versión de Java para ejecutar los servidores Minecraft.")
    print("  · Java 21 → Minecraft 1.20.5 o superior (NeoForge, Fabric moderno)")
    print("  · Java 17 → Minecraft 1.17 – 1.20.4\n")

    while True:
        ver = ask("  Versión de Java", default=default)
        if ver in ("17", "21"):
            return ver
        print("  Introduce 17 o 21.")


def configure_servers_path(default_path: str = "servers", default_is_host: bool = False) -> tuple[str, bool]:
    """
    Devuelve (ruta_o_nombre_volumen, es_ruta_host).
    Si el usuario deja en blanco se mantiene lo que ya hubiera (o un volumen
    Docker gestionado llamado "servers" si es la primera vez).
    """
    print("  ¿Dónde se guardarán los modpacks del servidor?")
    print("  · Volumen Docker (recomendado): pulsa Enter")
    print("  · Ruta del host: introduce una ruta absoluta, ej. /home/user/servers\n")

    hint = default_path if default_is_host else "volumen Docker"
    raw = input(f"  Ruta del host [{hint}]: ").strip()
    if not raw:
        return default_path, default_is_host
    return raw, True              # ruta absoluta en el host


def configure_domain(default: str = "") -> str:
    print("  Dominio con el que los jugadores se conectarán al servidor Minecraft.")
    print("  Solo informativo (se muestra en la interfaz); déjalo vacío si no")
    print("  tienes uno (se mostrará la IP pública).\n")
    hint = default or "ej: mc.tudominio.com"
    raw = input(f"  Dominio Minecraft [{hint}]: ").strip()
    return raw or default


def configure_curseforge(default: str = "") -> str:
    print("  Habilita buscar e instalar mods desde CurseForge además de Modrinth")
    print("  (Modrinth funciona sin esto). Se consigue gratis en:")
    print("  https://console.curseforge.com/#/api-keys\n")
    hint = "ya configurada, Enter para mantener" if default else "déjalo vacío para saltar"
    raw = input(f"  API key de CurseForge [{hint}]: ").strip()
    return raw or default


def configure_auto_update(default_enabled: bool = False, default_interval: int = 300) -> tuple[bool, int]:
    print("  La app puede revisar sola cada tanto si hay una versión nueva en GitHub")
    print("  y actualizarse + reiniciarse sola — pero SOLO cuando no haya ningún")
    print("  servidor de Minecraft corriendo ni ninguna subida/instalación en curso;")
    print("  si hay algo de eso, pospone la actualización al siguiente chequeo.\n")
    actual = "sí" if default_enabled else "no"
    answer = input(f"  ¿Habilitar auto-actualización? [s/N] (actual: {actual}): ").strip().lower()
    if not answer:
        enabled = default_enabled
    else:
        enabled = answer in ("s", "si", "sí", "y", "yes")
    if not enabled:
        return False, default_interval
    interval = ask_int("  Revisar cada cuántos segundos", default=default_interval, min_val=30, max_val=86400)
    return True, interval


def configure_telegram(default_token: str = "", default_chat: str = "") -> tuple[str, str]:
    print("  El panel puede avisarte por Telegram cuando el servidor arranca, se cae,")
    print("  entra alguien... Cada instalación usa su propio bot, así que solo te")
    print("  llegan tus avisos. Para crearlo:")
    print("    1. En Telegram, abre @BotFather y escríbele /newbot.")
    print("    2. Elige un nombre; te dará un token (algo como 123456:ABC-DEF...).")
    print("  También se puede configurar más tarde en Configuración → Avisos.\n")
    hint = "ya configurado, Enter para mantener" if default_token else "déjalo vacío para saltar"
    token = input(f"  Token del bot [{hint}]: ").strip().replace(" ", "") or default_token
    if not token:
        return "", ""
    if token == default_token and default_chat:
        return token, default_chat
    print("  Ahora abre tu bot en Telegram y escríbele cualquier cosa (por ejemplo /start).")
    input("  Pulsa Enter cuando lo hayas hecho... ")
    chat = _detect_telegram_chat(token)
    if chat:
        print(f"  ✓ Chat encontrado: {chat}")
        return token, chat
    print("  No se encontró ningún mensaje (¿token correcto? ¿le escribiste al bot?).")
    chat = input("  Chat ID a mano [déjalo vacío para configurarlo luego]: ").strip()
    return (token, chat) if chat else ("", "")


def _detect_telegram_chat(token: str) -> str:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10) as response:
            updates = json.load(response).get("result") or []
    except Exception:
        return ""
    for update in reversed(updates):
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            return str(chat["id"])
    return ""


# ── Generadores de archivos ────────────────────────────────────────────────────

def generate_env(
    username: str, password: str | None, existing_hash: str, mc_domain: str, curseforge_key: str,
    auto_update_enabled: bool, auto_update_interval: int,
    telegram_token: str = "", telegram_chat: str = "",
) -> str:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if password else existing_hash
    jwt_secret = secrets.token_hex(32)

    # Preservar JWT_SECRET si ya existe (no invalidar sesiones activas)
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text()
        m = re.search(r'^JWT_SECRET=(.+)$', existing, re.MULTILINE)
        if m and m.group(1).strip():
            jwt_secret = m.group(1).strip()

    managed = {
        "APP_USERNAME": username,
        "APP_PASSWORD_HASH": password_hash,
        "JWT_SECRET": jwt_secret,
        "MC_DOMAIN": mc_domain,
        "CURSEFORGE_API_KEY": curseforge_key,
        "AUTO_UPDATE_ENABLED": "true" if auto_update_enabled else "false",
        "AUTO_UPDATE_INTERVAL_SECONDS": str(auto_update_interval),
        "TELEGRAM_BOT_TOKEN": telegram_token,
        "TELEGRAM_CHAT_ID": telegram_chat,
    }
    text = "".join(f"{key}={value}\n" for key, value in managed.items())
    # Lo que se configuró desde el panel y este asistente no pregunta (webhook
    # de Discord, qué avisos se mandan...) se conserva tal cual.
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key = line.split("=", 1)[0].strip()
            if "=" in line and key and not key.startswith("#") and key not in managed:
                text += line + "\n"
    return text


def generate_compose(
    web_port: int,
    mc_port: int,
    java_version: str,
    servers_path: str,
    is_host_path: bool,
) -> str:
    if is_host_path:
        volume_def  = f"      - {servers_path}:/servers"
        volumes_section = ""
    else:
        volume_def  = f"      - {servers_path}:/servers"
        volumes_section = f"\nvolumes:\n  {servers_path}:\n"

    return (
        f"services:\n"
        f"  minecraft-deployer:\n"
        f"    build:\n"
        f"      context: .\n"
        f"      args:\n"
        f"        JAVA_VERSION: \"{java_version}\"\n"
        f"    ports:\n"
        f"      - \"{web_port}:8000\"\n"
        f"      - \"{mc_port}:25565\"\n"
        f"    volumes:\n"
        f"{volume_def}\n"
        f"      - ./.env:/app/.env\n"
        f"    environment:\n"
        f"      SERVERS_PATH: /servers\n"
        f"    restart: unless-stopped\n"
        f"{volumes_section}"
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n╔══════════════════════════════════════════════════╗")
    print("║     Minecraft Server Deployer — Setup            ║")
    print("╚══════════════════════════════════════════════════╝\n")

    existing_env = read_existing_env()
    existing_compose = read_existing_compose()

    if existing_env or existing_compose:
        print("Se detectó una configuración existente (.env / docker-compose.yml).")
        print("Pulsa Enter en cualquier pregunta para mantener el valor actual —")
        print("solo escribe algo en lo que quieras cambiar (p. ej. el puerto).\n")
    else:
        print("Este asistente generará el archivo .env y")
        print("docker-compose.yml listos para arrancar la app.\n")

    separator()
    print("1/8  CREDENCIALES DE ACCESO")
    separator()
    username, password = configure_credentials(
        existing_username=existing_env.get("APP_USERNAME", ""),
        has_existing_password=bool(existing_env.get("APP_PASSWORD_HASH")),
    )

    separator()
    print("2/8  PUERTOS")
    separator()
    web_port, mc_port = configure_ports(
        default_web=existing_compose.get("web_port", 8000),
        default_mc=existing_compose.get("mc_port", 25565),
    )

    separator()
    print("3/8  VERSIÓN DE JAVA")
    separator()
    java_version = configure_java(default=existing_compose.get("java_version", "21"))

    separator()
    print("4/8  ALMACENAMIENTO DE SERVIDORES")
    separator()
    servers_path, is_host_path = configure_servers_path(
        default_path=existing_compose.get("servers_path", "servers"),
        default_is_host=existing_compose.get("is_host_path", False),
    )

    separator()
    print("5/8  DOMINIO PÚBLICO (opcional)")
    separator()
    mc_domain = configure_domain(default=existing_env.get("MC_DOMAIN", ""))

    separator()
    print("6/8  CURSEFORGE (opcional)")
    separator()
    curseforge_key = configure_curseforge(default=existing_env.get("CURSEFORGE_API_KEY", ""))

    separator()
    print("7/8  AUTO-ACTUALIZACIÓN (opcional)")
    separator()
    auto_update_enabled, auto_update_interval = configure_auto_update(
        default_enabled=existing_env.get("AUTO_UPDATE_ENABLED", "false").strip().lower() == "true",
        default_interval=int(existing_env.get("AUTO_UPDATE_INTERVAL_SECONDS") or 300),
    )

    separator()
    print("8/8  AVISOS POR TELEGRAM (opcional)")
    separator()
    telegram_token, telegram_chat = configure_telegram(
        default_token=existing_env.get("TELEGRAM_BOT_TOKEN", ""),
        default_chat=existing_env.get("TELEGRAM_CHAT_ID", ""),
    )

    # ── Resumen ────────────────────────────────────────────────────────────────
    separator()
    print("  RESUMEN DE LA CONFIGURACIÓN\n")
    print(f"  Usuario:         {username}")
    print(f"  Contraseña:      {'(sin cambios)' if password is None else '(nueva)'}")
    print(f"  Puerto web:      {web_port}")
    print(f"  Puerto Minecraft:{mc_port}")
    print(f"  Java:            {java_version}")
    if is_host_path:
        print(f"  Servidores:      {servers_path} (ruta del host)")
    else:
        print(f"  Servidores:      volumen Docker '{servers_path}'")
    print(f"  Dominio:         {mc_domain or 'no configurado'}")
    print(f"  CurseForge:      {'configurado' if curseforge_key else 'no configurado'}")
    if auto_update_enabled:
        print(f"  Auto-update:     habilitado, cada {auto_update_interval}s")
    else:
        print(f"  Auto-update:     deshabilitado")
    print(f"  Telegram:        {'configurado' if telegram_token else 'no configurado'}")
    separator()

    confirm = input("  ¿Aplicar esta configuración? [S/n]: ").strip().lower()
    if confirm not in ("", "s", "si", "sí", "y", "yes"):
        print("\n  Configuración cancelada.")
        sys.exit(0)

    # ── Escribir archivos ──────────────────────────────────────────────────────
    ENV_FILE.write_text(generate_env(
        username, password, existing_env.get("APP_PASSWORD_HASH", ""), mc_domain, curseforge_key,
        auto_update_enabled, auto_update_interval, telegram_token, telegram_chat,
    ))
    COMPOSE_FILE.write_text(generate_compose(web_port, mc_port, java_version, servers_path, is_host_path))

    print("\n  ✓ .env generado")
    print("  ✓ docker-compose.yml generado")

    separator()
    print("  PRÓXIMOS PASOS\n")
    print("  1. Construir la imagen:")
    print("       docker compose build\n")
    print("  2. Arrancar la app:")
    print("       docker compose up -d\n")
    print(f"  3. Abrir en el navegador:")
    print(f"       http://<IP-DEL-SERVIDOR>:{web_port}\n")
    print(f"  4. Iniciar sesión con el usuario '{username}' y tu contraseña.")
    separator()


if __name__ == "__main__":
    main()
