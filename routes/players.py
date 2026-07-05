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
    PLAYER_FILES,
)
from services.process import mc_running_modpack

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("")
async def get_all_players():
    ensure_global_dir()
    return JSONResponse({
        "ops": read_global_file("ops.json"),
        "whitelist": read_global_file("whitelist.json"),
        "banned_players": read_global_file("banned-players.json"),
        "banned_ips": read_global_file("banned-ips.json"),
    })


@router.post("/op")
async def add_op(name: str = Form(...), uuid: str = Form(""), level: int = Form(4)):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("ops.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya es op")
    data.append({"uuid": uuid or "", "name": name, "level": level, "bypassesPlayerLimit": False})
    write_global_file("ops.json", data)
    synced, _ = sync_to_all_modpacks("ops.json", data)
    send_console_if_running("__all__", [f"op {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/op/{name}")
async def remove_op(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("ops.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no es op")
    data.pop(idx)
    write_global_file("ops.json", data)
    synced, _ = sync_to_all_modpacks("ops.json", data)
    send_console_if_running("__all__", [f"deop {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/whitelist")
async def add_whitelist(name: str = Form(...), uuid: str = Form("")):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("whitelist.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está en la whitelist")
    data.append({"uuid": uuid or "", "name": name})
    write_global_file("whitelist.json", data)
    synced, _ = sync_to_all_modpacks("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist add {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/whitelist/{name}")
async def remove_whitelist(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("whitelist.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está en la whitelist")
    data.pop(idx)
    write_global_file("whitelist.json", data)
    synced, _ = sync_to_all_modpacks("whitelist.json", data)
    send_console_if_running("__all__", [f"whitelist remove {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/ban")
async def ban_player(name: str = Form(...), uuid: str = Form(""), reason: str = Form("Banned by admin")):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    reason = sanitize_reason(reason)
    data = read_global_file("banned-players.json")
    if find_player(data, name) != -1:
        raise HTTPException(status_code=400, detail=f"{name} ya está baneado")
    data.append({
        "uuid": uuid or "",
        "name": name,
        "created": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S +0000"),
        "source": "Deployer",
        "expires": "forever",
        "reason": reason,
    })
    write_global_file("banned-players.json", data)
    synced, _ = sync_to_all_modpacks("banned-players.json", data)
    send_console_if_running("__all__", [f"ban {name} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/ban/{name}")
async def unban_player(name: str):
    try:
        name = validate_player_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("banned-players.json")
    idx = find_player(data, name)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{name} no está baneado")
    data.pop(idx)
    write_global_file("banned-players.json", data)
    synced, _ = sync_to_all_modpacks("banned-players.json", data)
    send_console_if_running("__all__", [f"pardon {name}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/ban-ip")
async def ban_ip(ip: str = Form(...), reason: str = Form("Banned by admin")):
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
    write_global_file("banned-ips.json", data)
    synced, _ = sync_to_all_modpacks("banned-ips.json", data)
    send_console_if_running("__all__", [f"ban-ip {ip} {reason}"])
    return JSONResponse({"success": True, "synced": synced})


@router.delete("/ban-ip/{ip}")
async def unban_ip(ip: str):
    try:
        ip = validate_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = read_global_file("banned-ips.json")
    idx = next((i for i, e in enumerate(data) if e.get("ip") == ip), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"{ip} no está baneada")
    data.pop(idx)
    write_global_file("banned-ips.json", data)
    synced, _ = sync_to_all_modpacks("banned-ips.json", data)
    send_console_if_running("__all__", [f"pardon-ip {ip}"])
    return JSONResponse({"success": True, "synced": synced})


@router.post("/sync")
async def sync_all():
    """Fuerza la sincronización de todos los archivos globales a todos los modpacks."""
    results = {}
    for fname in PLAYER_FILES:
        data = read_global_file(fname)
        synced, _ = sync_to_all_modpacks(fname, data)
        results[fname] = synced
    warning = None
    if mc_running_modpack:
        warning = (
            f"El servidor '{mc_running_modpack}' estaba activo y no se sincronizó "
            "para no interrumpirlo. Usa los comandos de consola en su lugar."
        )
    return JSONResponse({"success": True, "results": results, "warning": warning})
