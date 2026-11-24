"""
services/eula.py - La EULA de Minecraft de cada servidor (su eula.txt).

Minecraft no arranca hasta que eula.txt dice eula=true, y eso significa que
quien monta el servidor ha aceptado la EULA de Mojang. El panel no la acepta
nunca por su cuenta: antes de arrancar un servidor que no la tiene aceptada,
pide a una persona que la lea y la acepte (ver routes/server.py), y solo
entonces escribe eula.txt.
"""
import re
from datetime import datetime
from pathlib import Path

from services.secure_files import atomic_write_text

EULA_URL = "https://aka.ms/MinecraftEULA"

_ACCEPTED_RE = re.compile(r"(?im)^\s*eula\s*=\s*true\s*$")


def accepted(server_dir: Path) -> bool:
    try:
        text = (server_dir / "eula.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_ACCEPTED_RE.search(text))


def accept(server_dir: Path, username: str | None) -> None:
    """Escribe eula.txt aceptada (lo que haría la persona a mano), con quién y cuándo."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    who = f" by {username}" if username else ""
    atomic_write_text(
        server_dir / "eula.txt",
        f"#By changing the setting below to TRUE you are indicating your agreement to our EULA ({EULA_URL}).\n"
        f"#Accepted{who} from the panel on {stamp}\n"
        "eula=true\n",
    )
