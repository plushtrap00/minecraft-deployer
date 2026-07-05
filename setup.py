"""
setup.py - Instalador interactivo de Minecraft Server Deployer.

Configura credenciales, puertos y ruta de servidores,
y genera .env y docker-compose.yml listos para usar.

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

def configure_credentials() -> tuple[str, str]:
    print("  Configura el usuario y contraseña para acceder")
    print("  a la interfaz web de Minecraft Deployer.\n")

    username = ask("  Usuario", default="admin")

    while True:
        password = ask("  Contraseña (mín. 8 caracteres)", secret=True)
        if len(password) < 8:
            print("  La contraseña debe tener al menos 8 caracteres.")
            continue
        confirm = ask("  Confirmar contraseña", secret=True)
        if password != confirm:
            print("  Las contraseñas no coinciden. Inténtalo de nuevo.")
            continue
        break

    return username, password


def configure_ports() -> tuple[int, int]:
    print("  Puerto de la interfaz web y del servidor Minecraft.")
    print("  Déjalos en blanco para usar los valores por defecto.\n")

    web_port = ask_int("  Puerto web", default=8000)
    mc_port  = ask_int("  Puerto Minecraft", default=25565)

    return web_port, mc_port


def configure_java() -> str:
    print("  Versión de Java para ejecutar los servidores Minecraft.")
    print("  · Java 21 → Minecraft 1.20.5 o superior (NeoForge, Fabric moderno)")
    print("  · Java 17 → Minecraft 1.17 – 1.20.4\n")

    while True:
        ver = ask("  Versión de Java", default="21")
        if ver in ("17", "21"):
            return ver
        print("  Introduce 17 o 21.")


def configure_servers_path() -> tuple[str, bool]:
    """
    Devuelve (ruta_o_nombre_volumen, es_ruta_host).
    Si el usuario deja en blanco se usa un volumen Docker gestionado.
    """
    print("  ¿Dónde se guardarán los modpacks del servidor?")
    print("  · Volumen Docker (recomendado): pulsa Enter")
    print("  · Ruta del host: introduce una ruta absoluta, ej. /home/user/servers\n")

    raw = input("  Ruta del host [volumen Docker]: ").strip()
    if not raw:
        return "servers", False   # nombre del volumen Docker
    return raw, True              # ruta absoluta en el host


def configure_domain() -> str:
    print("  Dominio con el que los jugadores se conectarán al servidor Minecraft.")
    print("  Solo informativo (se muestra en la interfaz); déjalo vacío si no")
    print("  tienes uno (se mostrará la IP pública).\n")
    return input("  Dominio Minecraft [ej: mc.tudominio.com]: ").strip()


def configure_curseforge() -> str:
    print("  Habilita buscar e instalar mods desde CurseForge además de Modrinth")
    print("  (Modrinth funciona sin esto). Se consigue gratis en:")
    print("  https://console.curseforge.com/#/api-keys\n")
    return input("  API key de CurseForge [déjalo vacío para saltar]: ").strip()


# ── Generadores de archivos ────────────────────────────────────────────────────

def generate_env(username: str, password: str, mc_domain: str, curseforge_key: str) -> str:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    jwt_secret = secrets.token_hex(32)

    # Preservar JWT_SECRET si ya existe (no invalidar sesiones activas)
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text()
        m = re.search(r'^JWT_SECRET=(.+)$', existing, re.MULTILINE)
        if m and m.group(1).strip():
            jwt_secret = m.group(1).strip()

    return (
        f"APP_USERNAME={username}\n"
        f"APP_PASSWORD_HASH={password_hash}\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"MC_DOMAIN={mc_domain}\n"
        f"CURSEFORGE_API_KEY={curseforge_key}\n"
    )


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
        f"      - ./.env:/app/.env:ro\n"
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
    print("Este asistente generará el archivo .env y")
    print("docker-compose.yml listos para arrancar la app.\n")

    separator()
    print("1/6  CREDENCIALES DE ACCESO")
    separator()
    username, password = configure_credentials()

    separator()
    print("2/6  PUERTOS")
    separator()
    web_port, mc_port = configure_ports()

    separator()
    print("3/6  VERSIÓN DE JAVA")
    separator()
    java_version = configure_java()

    separator()
    print("4/6  ALMACENAMIENTO DE SERVIDORES")
    separator()
    servers_path, is_host_path = configure_servers_path()

    separator()
    print("5/6  DOMINIO PÚBLICO (opcional)")
    separator()
    mc_domain = configure_domain()

    separator()
    print("6/6  CURSEFORGE (opcional)")
    separator()
    curseforge_key = configure_curseforge()

    # ── Resumen ────────────────────────────────────────────────────────────────
    separator()
    print("  RESUMEN DE LA CONFIGURACIÓN\n")
    print(f"  Usuario:         {username}")
    print(f"  Puerto web:      {web_port}")
    print(f"  Puerto Minecraft:{mc_port}")
    print(f"  Java:            {java_version}")
    if is_host_path:
        print(f"  Servidores:      {servers_path} (ruta del host)")
    else:
        print(f"  Servidores:      volumen Docker '{servers_path}'")
    print(f"  Dominio:         {mc_domain or 'no configurado'}")
    print(f"  CurseForge:      {'configurado' if curseforge_key else 'no configurado'}")
    separator()

    confirm = input("  ¿Aplicar esta configuración? [S/n]: ").strip().lower()
    if confirm not in ("", "s", "si", "sí", "y", "yes"):
        print("\n  Configuración cancelada.")
        sys.exit(0)

    # ── Escribir archivos ──────────────────────────────────────────────────────
    ENV_FILE.write_text(generate_env(username, password, mc_domain, curseforge_key))
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
