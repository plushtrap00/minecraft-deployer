"""
set_password.py - Configura el usuario y la contraseña de administrador en .env.
También genera JWT_SECRET si no existe.

Uso:
    python3 set_password.py
"""
import bcrypt
import getpass
import re
import secrets
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


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
    print(f"✓ Usuario '{username}' configurado en {ENV_FILE}")
    print("  Ya puedes arrancar la app con: bash start.sh")


if __name__ == "__main__":
    main()
