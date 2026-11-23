"""
set_password.py - Configura el usuario y la contraseña de administrador en .env.
También genera JWT_SECRET si no existe y, si esa cuenta tiene la verificación
en dos pasos activada, ofrece quitarla (por si se ha perdido el móvil).

Uso:
    python3 set_password.py
"""
import bcrypt
import getpass
import json
import os
import re
import secrets
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def _servers_path() -> Path:
    """La misma carpeta que usa la app: SERVERS_PATH del entorno, del .env o la de por defecto."""
    value = os.environ.get("SERVERS_PATH", "")
    if not value and ENV_FILE.exists():
        match = re.search(r"^SERVERS_PATH=(.*)$", ENV_FILE.read_text(), re.MULTILINE)
        value = match.group(1).strip().strip('"').strip("'") if match else ""
    return Path(value).expanduser() if value else Path.home() / "servers-minecraft"


def offer_remove_two_factor(username: str) -> None:
    store = _servers_path() / ".global" / "two_factor.json"
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or not (data.get(username) or {}).get("enabled"):
        return
    answer = input(f"'{username}' tiene la verificación en dos pasos activada. "
                   "¿Quitarla (por ejemplo, si has perdido el móvil)? [s/N]: ").strip().lower()
    if answer not in ("s", "si", "sí", "y", "yes"):
        return
    data.pop(username, None)
    store.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"✓ Verificación en dos pasos quitada a '{username}': podrá entrar solo con la contraseña")


def main():
    print("=== Configurar acceso de administrador ===")
    username = input("Usuario [admin]: ").strip() or "admin"
    password = getpass.getpass("Nueva contraseña: ")
    confirm  = getpass.getpass("Confirmar contraseña: ")

    if password != confirm:
        print("Las contraseñas no coinciden.")
        return
    if len(password) < 6:
        print("La contraseña debe tener al menos 6 caracteres.")
        return

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # Leer .env existente o empezar desde cero
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
    else:
        content = ""

    # Actualizar o añadir APP_USERNAME
    if "APP_USERNAME=" in content:
        content = re.sub(r"APP_USERNAME=.*", f"APP_USERNAME={username}", content)
    else:
        content += f"\nAPP_USERNAME={username}\n"

    # Actualizar o añadir APP_PASSWORD_HASH
    if "APP_PASSWORD_HASH=" in content:
        content = re.sub(r"APP_PASSWORD_HASH=.*", f"APP_PASSWORD_HASH={hashed}", content)
    else:
        content += f"APP_PASSWORD_HASH={hashed}\n"

    # Generar JWT_SECRET si no existe
    if "JWT_SECRET=" not in content or re.search(r"JWT_SECRET=\s*$", content, re.MULTILINE):
        new_secret = secrets.token_hex(32)
        if "JWT_SECRET=" in content:
            content = re.sub(r"JWT_SECRET=.*", f"JWT_SECRET={new_secret}", content)
        else:
            content += f"JWT_SECRET={new_secret}\n"
        print(f"✓ JWT_SECRET generado automáticamente")

    ENV_FILE.write_text(content.strip() + "\n")
    # Lleva JWT_SECRET y el hash de la contraseña: solo lo lee el dueño.
    if os.name == "posix":
        ENV_FILE.chmod(0o600)
    print(f"✓ Usuario '{username}' configurado en {ENV_FILE}")
    offer_remove_two_factor(username)
    print("  Ya puedes arrancar la app con: bash start.sh")


if __name__ == "__main__":
    main()
