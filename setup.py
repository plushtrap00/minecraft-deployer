"""
setup.py - Instalador interactivo de Minecraft Server Deployer.

Configura idioma, credenciales, puertos y ruta de servidores,
y genera .env y docker-compose.yml listos para usar.

Si ya existe una configuración previa (.env / docker-compose.yml), cada
pregunta usa el valor actual como valor por defecto — para cambiar solo
una cosa (p. ej. el puerto), basta con pulsar Enter en el resto.

El asistente habla en el idioma que se elija al principio (español o
inglés), que también queda como idioma por defecto del panel (APP_LANGUAGE).

Uso:
    python3 setup.py
"""
import bcrypt
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
COMPOSE_FILE = Path(__file__).parent / "docker-compose.yml"

# Idioma del asistente: "es" o "en". L("español", "english") devuelve el que toca.
LANG = "es"
YES = ("s", "si", "sí", "y", "yes")


def L(es: str, en: str) -> str:
    return en if LANG == "en" else es


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
        print(L("  El valor no puede estar vacío.", "  The value can't be empty."))


def ask_int(prompt: str, default: int, min_val: int = 1, max_val: int = 65535) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(L(f"  Debe ser un número entre {min_val} y {max_val}.",
                    f"  It must be a number between {min_val} and {max_val}."))
        except ValueError:
            print(L("  Introduce un número válido.", "  Enter a valid number."))


def separator():
    print("\n" + "─" * 52 + "\n")


# ── Secciones del wizard ───────────────────────────────────────────────────────

def choose_language(default: str = "") -> str:
    """Primera pregunta, en los dos idiomas. Devuelve "es" o "en"."""
    print("  Idioma / Language:\n")
    print("    1) Español (España)")
    print("    2) English\n")
    current = {"es": "1", "en": "2"}.get(default, "")
    while True:
        hint = f" [{current}]" if current else ""
        raw = input(f"  [1/2]{hint}: ").strip() or current
        if raw == "1":
            return "es"
        if raw == "2":
            return "en"
        print("  1 / 2")


def configure_credentials(existing_username: str = "", has_existing_password: bool = False) -> tuple[str, str | None]:
    """Devuelve (usuario, contraseña) — contraseña None significa "mantener la actual"."""
    print(L("  Configura el usuario y contraseña para acceder", "  Set the username and password to sign in"))
    print(L("  a la interfaz web de Minecraft Deployer.", "  to the Minecraft Deployer web panel."))
    if has_existing_password:
        print(L("  Deja la contraseña en blanco para mantener la actual.", "  Leave the password empty to keep the current one."))
    print("")

    username = ask(L("  Usuario", "  Username"), default=existing_username or "admin")

    while True:
        display = L("  Contraseña (mín. 8 caracteres, Enter = mantener la actual): ",
                    "  Password (at least 8 characters, Enter = keep the current one): ") if has_existing_password \
            else L("  Contraseña (mín. 8 caracteres): ", "  Password (at least 8 characters): ")
        password = getpass.getpass(display)
        if not password and has_existing_password:
            return username, None
        if len(password) < 8:
            print(L("  La contraseña debe tener al menos 8 caracteres.", "  The password must have at least 8 characters."))
            continue
        confirm = getpass.getpass(L("  Confirmar contraseña: ", "  Confirm password: "))
        if password != confirm:
            print(L("  Las contraseñas no coinciden. Inténtalo de nuevo.", "  The passwords don't match. Try again."))
            continue
        return username, password


def configure_ports(default_web: int = 8000, default_mc: int = 25565) -> tuple[int, int]:
    print(L("  Puerto de la interfaz web y del servidor Minecraft.", "  Port for the web panel and for the Minecraft server."))
    print(L("  Déjalos en blanco para mantener los valores actuales/por defecto.\n",
            "  Leave them empty to keep the current/default values.\n"))

    web_port = ask_int(L("  Puerto web", "  Web port"), default=default_web)
    mc_port  = ask_int(L("  Puerto Minecraft", "  Minecraft port"), default=default_mc)

    return web_port, mc_port


def configure_java(default: str = "21") -> str:
    print(L("  Versión de Java para ejecutar los servidores Minecraft.", "  Java version to run the Minecraft servers."))
    print(L("  · Java 21 → Minecraft 1.20.5 o superior (NeoForge, Fabric moderno)",
            "  · Java 21 → Minecraft 1.20.5 or newer (NeoForge, modern Fabric)"))
    print("  · Java 17 → Minecraft 1.17 – 1.20.4\n")

    while True:
        ver = ask(L("  Versión de Java", "  Java version"), default=default)
        if ver in ("17", "21"):
            return ver
        print(L("  Introduce 17 o 21.", "  Enter 17 or 21."))


def configure_servers_path(default_path: str = "servers", default_is_host: bool = False) -> tuple[str, bool]:
    """
    Devuelve (ruta_o_nombre_volumen, es_ruta_host).
    Si el usuario deja en blanco se mantiene lo que ya hubiera (o un volumen
    Docker gestionado llamado "servers" si es la primera vez).
    """
    print(L("  ¿Dónde se guardarán los modpacks del servidor?", "  Where should the server's modpacks be stored?"))
    print(L("  · Volumen Docker (recomendado): pulsa Enter", "  · Docker volume (recommended): press Enter"))
    print(L("  · Ruta del host: introduce una ruta absoluta, ej. /home/user/servers\n",
            "  · Host path: enter an absolute path, e.g. /home/user/servers\n"))

    hint = default_path if default_is_host else L("volumen Docker", "Docker volume")
    raw = input(L(f"  Ruta del host [{hint}]: ", f"  Host path [{hint}]: ")).strip()
    if not raw:
        return default_path, default_is_host
    return raw, True              # ruta absoluta en el host


def configure_domain(default: str = "") -> str:
    print(L("  Dominio con el que los jugadores se conectarán al servidor Minecraft.",
            "  Domain players will use to connect to the Minecraft server."))
    print(L("  Solo informativo (se muestra en la interfaz); déjalo vacío si no",
            "  Just for information (shown in the panel); leave it empty if you"))
    print(L("  tienes uno (se mostrará la IP pública).\n", "  don't have one (the public IP will be shown).\n"))
    hint = default or L("ej: mc.tudominio.com", "e.g. mc.yourdomain.com")
    raw = input(L(f"  Dominio Minecraft [{hint}]: ", f"  Minecraft domain [{hint}]: ")).strip()
    return raw or default


def configure_curseforge(default: str = "") -> str:
    print(L("  Habilita buscar e instalar mods desde CurseForge además de Modrinth",
            "  Lets you search and install mods from CurseForge as well as Modrinth"))
    print(L("  (Modrinth funciona sin esto). Se consigue gratis en:", "  (Modrinth works without it). Get one free at:"))
    print("  https://console.curseforge.com/#/api-keys\n")
    hint = L("ya configurada, Enter para mantener", "already set, Enter to keep it") if default \
        else L("déjalo vacío para saltar", "leave empty to skip")
    raw = input(L(f"  API key de CurseForge [{hint}]: ", f"  CurseForge API key [{hint}]: ")).strip()
    return raw or default


def configure_auto_update(default_enabled: bool = False, default_interval: int = 300) -> tuple[bool, int]:
    print(L("  La app puede revisar sola cada tanto si hay una versión nueva en GitHub",
            "  The app can check GitHub for a new version every so often"))
    print(L("  y actualizarse + reiniciarse sola — pero SOLO cuando no haya ningún",
            "  and update + restart itself — but ONLY when no Minecraft server is"))
    print(L("  servidor de Minecraft corriendo ni ninguna subida/instalación en curso;",
            "  running and no upload/installation is in progress;"))
    print(L("  si hay algo de eso, pospone la actualización a la siguiente comprobación.\n",
            "  if there is, it puts the update off until the next check.\n"))
    actual = L("sí", "yes") if default_enabled else "no"
    answer = input(L(f"  ¿Habilitar auto-actualización? [s/N] (actual: {actual}): ",
                     f"  Enable auto-update? [y/N] (current: {actual}): ")).strip().lower()
    if not answer:
        enabled = default_enabled
    else:
        enabled = answer in YES
    if not enabled:
        return False, default_interval
    interval = ask_int(L("  Revisar cada cuántos segundos", "  Check every how many seconds"),
                       default=default_interval, min_val=30, max_val=86400)
    return True, interval


def configure_telegram(default_token: str = "", default_chat: str = "") -> tuple[str, str]:
    print(L("  El panel puede avisarte por Telegram cuando el servidor arranca, se cae,",
            "  The panel can message you on Telegram when the server starts, crashes,"))
    print(L("  entra alguien... Cada instalación usa su propio bot, así que solo te",
            "  someone joins... Each installation uses its own bot, so only your"))
    print(L("  llegan tus avisos. Para crearlo:", "  notifications reach you. To create it:"))
    print(L("    1. En Telegram, abre @BotFather y escríbele /newbot.", "    1. In Telegram, open @BotFather and send it /newbot."))
    print(L("    2. Elige un nombre; te dará un token (algo como 123456:ABC-DEF...).",
            "    2. Pick a name; it will give you a token (something like 123456:ABC-DEF...)."))
    print(L("  También se puede configurar más tarde en Configuración → Avisos.\n",
            "  You can also set it up later in Settings → Notifications.\n"))
    hint = L("ya configurado, Enter para mantener", "already set, Enter to keep it") if default_token \
        else L("déjalo vacío para saltar", "leave empty to skip")
    token = input(L(f"  Token del bot [{hint}]: ", f"  Bot token [{hint}]: ")).strip().replace(" ", "") or default_token
    if not token:
        return "", ""
    if token == default_token and default_chat:
        return token, default_chat
    print(L("  Ahora abre tu bot en Telegram y escríbele cualquier cosa (por ejemplo /start).",
            "  Now open your bot in Telegram and send it anything (for example /start)."))
    input(L("  Pulsa Enter cuando lo hayas hecho... ", "  Press Enter when you've done it... "))
    chat = _detect_telegram_chat(token)
    if chat:
        print(L(f"  ✓ Chat encontrado: {chat}", f"  ✓ Chat found: {chat}"))
        return token, chat
    print(L("  No se encontró ningún mensaje (¿token correcto? ¿le escribiste al bot?).",
            "  No message found (is the token right? did you message the bot?)."))
    chat = input(L("  Chat ID a mano [déjalo vacío para configurarlo luego]: ",
                   "  Chat ID by hand [leave empty to set it up later]: ")).strip()
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
    telegram_token: str = "", telegram_chat: str = "", language: str = "es",
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
        "APP_LANGUAGE": language,
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
    global LANG
    print("\n╔══════════════════════════════════════════════════╗")
    print("║     Minecraft Server Deployer — Setup            ║")
    print("╚══════════════════════════════════════════════════╝\n")

    existing_env = read_existing_env()
    existing_compose = read_existing_compose()

    LANG = choose_language(default=existing_env.get("APP_LANGUAGE", "").strip().lower()[:2])
    print("")

    if existing_env or existing_compose:
        print(L("Se detectó una configuración existente (.env / docker-compose.yml).",
                "An existing configuration was found (.env / docker-compose.yml)."))
        print(L("Pulsa Enter en cualquier pregunta para mantener el valor actual —",
                "Press Enter on any question to keep the current value —"))
        print(L("solo escribe algo en lo que quieras cambiar (p. ej. el puerto).\n",
                "only type something where you want a change (e.g. the port).\n"))
    else:
        print(L("Este asistente generará el archivo .env y", "This wizard will generate the .env file and"))
        print(L("docker-compose.yml listos para arrancar la app.\n", "docker-compose.yml, ready to start the app.\n"))

    separator()
    print(L("1/8  CREDENCIALES DE ACCESO", "1/8  SIGN-IN DETAILS"))
    separator()
    username, password = configure_credentials(
        existing_username=existing_env.get("APP_USERNAME", ""),
        has_existing_password=bool(existing_env.get("APP_PASSWORD_HASH")),
    )

    separator()
    print(L("2/8  PUERTOS", "2/8  PORTS"))
    separator()
    web_port, mc_port = configure_ports(
        default_web=existing_compose.get("web_port", 8000),
        default_mc=existing_compose.get("mc_port", 25565),
    )

    separator()
    print(L("3/8  VERSIÓN DE JAVA", "3/8  JAVA VERSION"))
    separator()
    java_version = configure_java(default=existing_compose.get("java_version", "21"))

    separator()
    print(L("4/8  ALMACENAMIENTO DE SERVIDORES", "4/8  SERVER STORAGE"))
    separator()
    servers_path, is_host_path = configure_servers_path(
        default_path=existing_compose.get("servers_path", "servers"),
        default_is_host=existing_compose.get("is_host_path", False),
    )

    separator()
    print(L("5/8  DOMINIO PÚBLICO (opcional)", "5/8  PUBLIC DOMAIN (optional)"))
    separator()
    mc_domain = configure_domain(default=existing_env.get("MC_DOMAIN", ""))

    separator()
    print(L("6/8  CURSEFORGE (opcional)", "6/8  CURSEFORGE (optional)"))
    separator()
    curseforge_key = configure_curseforge(default=existing_env.get("CURSEFORGE_API_KEY", ""))

    separator()
    print(L("7/8  AUTO-ACTUALIZACIÓN (opcional)", "7/8  AUTO-UPDATE (optional)"))
    separator()
    auto_update_enabled, auto_update_interval = configure_auto_update(
        default_enabled=existing_env.get("AUTO_UPDATE_ENABLED", "false").strip().lower() == "true",
        default_interval=int(existing_env.get("AUTO_UPDATE_INTERVAL_SECONDS") or 300),
    )

    separator()
    print(L("8/8  AVISOS POR TELEGRAM (opcional)", "8/8  TELEGRAM NOTIFICATIONS (optional)"))
    separator()
    telegram_token, telegram_chat = configure_telegram(
        default_token=existing_env.get("TELEGRAM_BOT_TOKEN", ""),
        default_chat=existing_env.get("TELEGRAM_CHAT_ID", ""),
    )

    # ── Resumen ────────────────────────────────────────────────────────────────
    configured = L("configurado", "set up")
    not_configured = L("no configurado", "not set up")
    separator()
    print(L("  RESUMEN DE LA CONFIGURACIÓN\n", "  CONFIGURATION SUMMARY\n"))
    print(L("  Idioma:          español", "  Language:        English"))
    print(L(f"  Usuario:         {username}", f"  Username:        {username}"))
    print(L(f"  Contraseña:      {'(sin cambios)' if password is None else '(nueva)'}",
            f"  Password:        {'(unchanged)' if password is None else '(new)'}"))
    print(L(f"  Puerto web:      {web_port}", f"  Web port:        {web_port}"))
    print(L(f"  Puerto Minecraft:{mc_port}", f"  Minecraft port:  {mc_port}"))
    print(f"  Java:            {java_version}")
    if is_host_path:
        print(L(f"  Servidores:      {servers_path} (ruta del host)", f"  Servers:         {servers_path} (host path)"))
    else:
        print(L(f"  Servidores:      volumen Docker '{servers_path}'", f"  Servers:         Docker volume '{servers_path}'"))
    print(L(f"  Dominio:         {mc_domain or not_configured}", f"  Domain:          {mc_domain or not_configured}"))
    print(f"  CurseForge:      {configured if curseforge_key else not_configured}")
    if auto_update_enabled:
        print(L(f"  Auto-update:     habilitado, cada {auto_update_interval}s",
                f"  Auto-update:     enabled, every {auto_update_interval}s"))
    else:
        print(L("  Auto-update:     deshabilitado", "  Auto-update:     disabled"))
    print(f"  Telegram:        {configured if telegram_token else not_configured}")
    separator()

    confirm = input(L("  ¿Aplicar esta configuración? [S/n]: ", "  Apply this configuration? [Y/n]: ")).strip().lower()
    if confirm not in ("",) + YES:
        print(L("\n  Configuración cancelada.", "\n  Configuration cancelled."))
        sys.exit(0)

    # ── Escribir archivos ──────────────────────────────────────────────────────
    ENV_FILE.write_text(generate_env(
        username, password, existing_env.get("APP_PASSWORD_HASH", ""), mc_domain, curseforge_key,
        auto_update_enabled, auto_update_interval, telegram_token, telegram_chat, LANG,
    ))
    # Lleva JWT_SECRET y el hash de la contraseña: solo lo lee el dueño.
    if os.name == "posix":
        ENV_FILE.chmod(0o600)
    COMPOSE_FILE.write_text(generate_compose(web_port, mc_port, java_version, servers_path, is_host_path))

    print(L("\n  ✓ .env generado", "\n  ✓ .env generated"))
    print(L("  ✓ docker-compose.yml generado", "  ✓ docker-compose.yml generated"))

    separator()
    print(L("  PRÓXIMOS PASOS\n", "  NEXT STEPS\n"))
    print(L("  1. Construir la imagen:", "  1. Build the image:"))
    print("       docker compose build\n")
    print(L("  2. Arrancar la app:", "  2. Start the app:"))
    print("       docker compose up -d\n")
    print(L("  3. Abrir en el navegador:", "  3. Open in the browser:"))
    print(L(f"       http://<IP-DEL-SERVIDOR>:{web_port}\n", f"       http://<SERVER-IP>:{web_port}\n"))
    print(L(f"  4. Iniciar sesión con el usuario '{username}' y tu contraseña.",
            f"  4. Sign in with the username '{username}' and your password."))
    separator()


if __name__ == "__main__":
    main()
