"""
routes/players.py - Endpoints de gestión global de jugadores.

Rutas:
- GET    /api/players                  → todos los archivos de jugadores
- POST   /api/players/op               → añadir op
- DELETE /api/players/op/{name}        → quitar op
- POST   /api/players/whitelist        → añadir a whitelist
- DELETE /api/players/whitelist/{name} → quitar de whitelist
- POST   /api/players/ban              → banear jugador
- DELETE /api/players/ban/{name}       → desbanear jugador
- POST   /api/players/ban-ip           → banear IP
- DELETE /api/players/ban-ip/{ip}      → desbanear IP
- POST   /api/players/sync             → sincronizar a todos los modpacks
"""
import datetime
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from services.players import (
    ensure_global_dir, read_global_file, write_global_file,
    find_player, sync_to_all_modpacks, send_console_if_running,
    validate_player_name, validate_ip, sanitize_reason,
    resolve_player, fill_missing_uuids, PlayerLookupError,
    PLAYER_FILES, PROFILE_FILES,
)

router = APIRouter(prefix="/api/players", tags=["players"])


def _resolve(name: str) -> dict:
    """UUID y nombre exacto de la cuenta, o error 400/502 legible."""
    try:
        return resolve_player(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PlayerLookupError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _save(fname: str, data: list) -> list:
    """Guarda el archivo global (completando UUID que falten) y lo sincroniza."""
    if fname in PROFILE_FILES:
        fill_missing_uuids(data)
    write_global_file(fname, data)
    synced, _ = sync_to_all_modpacks(fname, data)
    return synced


@router.get("")
def get_all_players():
    ensure_global_dir()
    return JSONResponse({
        "ops": read_global_file("ops.json"),
        "whitelist": read_global_file("whitelist.json"),
        "banned_players": read_global_file("banned-players.json"),
        "banned_ips": read_global_file("banned-ips.json"),
    })


@router.post("/op")
def add_op(name: str = Form(...), level: int = Form(4)):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("ops.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya es op")
    player = _resolve(name)
    name = player["name"]
    data.append({"uuid": player["uuid"], "name": name, "level": level, "bypassesPlayerLimit": False})
    synced = _save("ops.json", data)
    send_console_if_running("__all__", [f"op {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/op/{name}")
def remove_op(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("ops.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no es op")
    data.pop(idx)
    synced = _save("ops.json", data)
    send_console_if_running("__all__", [f"deop {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/whitelist")
def add_whitelist(name: str = Form(...)):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("whitelist.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está en la whitelist")
    player = _resolve(name)
    name = player["name"]
    data.append({"uuid": player["uuid"], "name": name})
    synced = _save("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist add {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/whitelist/{name}")
def remove_whitelist(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("whitelist.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está en la whitelist")
    data.pop(idx)
    synced = _save("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist remove {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/ban")
def ban_player(name: str = Form(...), reason: str = Form("Banned by admin")):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    reason = sanitize_reason(reason)
    data = read_global_file("banned-players.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está baneado")
    player = _resolve(name)
    name = player["name"]
    data.append({
        "uuid": player["uuid"],
        "name": name,
        "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"),
        "source": "Deployer",
        "expires": "forever",
        "reason": reason,
    })
    synced = _save("banned-players.json", data)
    send_console_if_running("__all__", [f"ban {name} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/ban/{name}")
def unban_player(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("banned-players.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está baneado")
    data.pop(idx)
    synced = _save("banned-players.json", data)
    send_console_if_running("__all__", [f"pardon {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/ban-ip")
def ban_ip(ip: str = Form(...), reason: str = Form("Banned by admin")):
    try:
        ip = validate_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    reason = sanitize_reason(reason)
    data = read_global_file("banned-ips.json")
    if any(e.get("ip") == ip for e in data):
        raise HTTPException(status_code=400, detail=f"{ip} ya está baneada")
    data.append({
        "ip": ip,
        "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"),
        "source": "Deployer",
        "expires": "forever",
        "reason": reason,
    })
    synced = _save("banned-ips.json", data)
    send_console_if_running("__all__", [f"ban-ip {ip} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/ban-ip/{ip}")
def unban_ip(ip: str):
    try:
        ip = validate_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("banned-ips.json")
    idx = next((i for i, e in enumerate(data) if e.get("ip") == ip), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{ip} no está baneada")
    data.pop(idx)
    synced = _save("banned-ips.json", data)
    send_console_if_running("__all__", [f"pardon-ip {ip}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/sync")
def sync_all():
    """Fuerza la sincronización de todos los archivos globales a todos los modpacks."""
    results = {}
    skipped = []
    for fname in PLAYER_FILES:
        data = read_global_file(fname)
        # Las entradas que el panel guardaba antes sin UUID se completan
        # aquí: Minecraft las ignora mientras no lo tengan.
        if fname in PROFILE_FILES and fill_missing_uuids(data):
            write_global_file(fname, data)
        synced, skipped = sync_to_all_modpacks(fname, data)
        results[fname] = synced
    warning = None
    if skipped:
        warning = (
            f"El servidor '{skipped[0]}' estaba activo y no se sincronizó "
            "para no interrumpirlo. Usa los comandos de consola en su lugar."
        )
    return JSONResponse({"success": True, "results": results, "warning": warning})
