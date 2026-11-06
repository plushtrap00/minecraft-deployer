"""
routes/firewall.py - Abrir el puerto de Minecraft solo a la red local o a todo
internet (ufw).

Rutas:
- POST      /api/firewall/set
- GET       /api/firewall/status

La red local y los puertos ya no van fijos (antes eran 192.168.1.0/24 y el
25565): la red se saca de la interfaz de la ruta por defecto de este equipo, y
los puertos del server-port de cada modpack instalado. Las reglas que creaba
la versión anterior con la red fija se siguen borrando al cambiar de modo.
"""
import ipaddress
import re
import subprocess

from fastapi import APIRouter, Form, HTTPException, Request

from routes.auth import require_admin
from services.modpack import parse_server_properties
from services.utils import get_modpacks

router = APIRouter(tags=["firewall"])

_DEFAULT_PORT = 25565
_LEGACY_LAN_SUBNET = "192.168.1.0/24"

_UFW_UNAVAILABLE_DETAIL = (
    "ufw no está disponible en este entorno (normal si corres en Docker: el "
    "firewall se gestiona desde el host, no desde dentro del contenedor — "
    "controla el acceso público/LAN con el mapeo de puertos de docker-compose.yml)."
)
_SUDO_PASSWORD_DETAIL = (
    "sudo pide contraseña para ejecutar ufw. Permite ese comando sin contraseña "
    "al usuario del panel (por ejemplo, con una regla en /etc/sudoers.d/)."
)


class UfwUnavailable(Exception):
    pass


def _run_ufw(args: list) -> subprocess.CompletedProcess:
    """
    sudo -n: si sudo pidiera contraseña, sin -n el proceso se quedaba
    esperándola para siempre (nadie la puede escribir desde el panel).
    """
    try:
        return subprocess.run(["sudo", "-n", "ufw"] + args, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise UfwUnavailable()


def lan_subnet() -> str:
    """Red de la interfaz por la que sale la ruta por defecto (ej. 192.168.0.0/24)."""
    try:
        route = subprocess.run(["ip", "-o", "-4", "route", "show", "default"],
                               capture_output=True, text=True, timeout=5).stdout
        dev = re.search(r"\bdev (\S+)", route)
        if dev:
            addr = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", dev.group(1)],
                                  capture_output=True, text=True, timeout=5).stdout
            inet = re.search(r"\binet (\d+\.\d+\.\d+\.\d+/\d+)", addr)
            if inet:
                network = ipaddress.ip_interface(inet.group(1)).network
                if network.is_private:
                    return str(network)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return _LEGACY_LAN_SUBNET


def minecraft_ports() -> list:
    """El server-port de cada modpack instalado (25565 si no lo cambia ninguno)."""
    ports = set()
    for pack in get_modpacks():
        value = parse_server_properties(pack).get("server-port", "").strip()
        ports.add(int(value) if value.isdigit() and 0 < int(value) < 65536 else _DEFAULT_PORT)
    return sorted(ports or {_DEFAULT_PORT})


def parse_ufw_mode(output: str, ports: list, subnet: str) -> str:
    """
    "public" si algún puerto está abierto a cualquier IP, "lan" si están
    abiertos solo a la red local, "unknown" si no hay reglas del panel.
    Cada línea de `ufw status` empieza por el puerto, con /tcp o /udp
    opcional y " (v6)" en las reglas de IPv6.
    """
    has_public = has_lan = False
    for line in output.splitlines():
        if "ALLOW" not in line:
            continue
        target = line.split()[0].split("/")[0] if line.split() else ""
        if not target.isdigit() or int(target) not in ports:
            continue
        if "Anywhere" in line:
            has_public = True
        elif subnet in line or _LEGACY_LAN_SUBNET in line:
            has_lan = True
    if has_public:
        return "public"
    if has_lan:
        return "lan"
    return "unknown"


def _set_mode(mode: str) -> dict:
    subnet = lan_subnet()
    ports = minecraft_ports()
    for port in ports:
        # Las reglas que no existan dan error al borrarlas: se ignora.
        _run_ufw(["delete", "allow", str(port)])
        for net in {subnet, _LEGACY_LAN_SUBNET}:
            _run_ufw(["delete", "allow", "from", net, "to", "any", "port", str(port)])
    for port in ports:
        if mode == "public":
            result = _run_ufw(["allow", str(port)])
        else:
            result = _run_ufw(["allow", "from", subnet, "to", "any", "port", str(port)])
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            if "password is required" in output:
                raise HTTPException(status_code=500, detail=_SUDO_PASSWORD_DETAIL)
            raise HTTPException(status_code=500, detail=f"Error ejecutando ufw: {output}")
    return {"success": True, "mode": mode, "subnet": subnet, "ports": ports}


@router.post("/api/firewall/set")
def set_firewall(request: Request, mode: str = Form(...)):
    """mode='lan' → solo la red local de este equipo; mode='public' → cualquier IP."""
    require_admin(request)
    if mode not in ("lan", "public"):
        raise HTTPException(status_code=400, detail="mode debe ser 'lan' o 'public'")
    try:
        return _set_mode(mode)
    except UfwUnavailable:
        raise HTTPException(status_code=409, detail=_UFW_UNAVAILABLE_DETAIL)


@router.get("/api/firewall/status")
def firewall_status(request: Request):
    """
    Modo actual, o mode="unavailable" si ufw/sudo no existen en este entorno
    (p. ej. dentro de un contenedor Docker, donde además no tendría efecto
    real sobre el host aunque estuviera instalado).
    """
    require_admin(request)
    subnet = lan_subnet()
    ports = minecraft_ports()
    try:
        result = _run_ufw(["status"])
    except UfwUnavailable:
        return {"mode": "unavailable", "ufw_output": "", "subnet": subnet, "ports": ports}
    return {
        "mode": parse_ufw_mode(result.stdout, ports, subnet),
        "ufw_output": result.stdout,
        "subnet": subnet,
        "ports": ports,
    }
