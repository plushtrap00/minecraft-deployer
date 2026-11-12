"""
services/player_stats.py - Estadísticas de los jugadores de un modpack,
leídas de lo que el propio Minecraft guarda en el mundo:

- <mundo>/stats/<uuid>.json: tiempo jugado, muertes, bichos, bloques picados,
  distancia... (formato 1.13+ con "stats", y el plano «stat.xxx» de antes).
- usercache.json (en la carpeta del servidor): de UUID a nombre.
- <mundo>/playerdata/<uuid>.dat: la fecha de modificación es la última vez
  que el servidor guardó al jugador (al salir o en el autoguardado).

Si se cambia online-mode con el mundo ya jugado, Minecraft da a cada jugador
otro UUID (el premium o el «OfflinePlayer:nombre») y el mundo acaba con dos
archivos de estadísticas para la misma persona. Se juntan por nombre: se suman
los números y se queda el UUID del online-mode actual (para la cabeza/skin).
"""
import json
from datetime import datetime
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.modpack import parse_server_properties
from services.players import _pack_online_mode, offline_uuid

TICKS_PER_SECOND = 20


def _usercache(server_dir: Path) -> dict:
    try:
        entries = json.loads((server_dir / "usercache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(entry.get("uuid", "")).lower(): entry.get("name")
        for entry in entries if isinstance(entry, dict) and entry.get("name")
    }


def _number(value) -> float:
    return value if isinstance(value, (int, float)) else 0


def _summarize(data: dict) -> dict:
    stats = data.get("stats")
    if isinstance(stats, dict):
        custom = stats.get("minecraft:custom") or {}
        play_ticks = _number(custom.get("minecraft:play_time")) or _number(custom.get("minecraft:play_one_minute"))
        distance_cm = sum(
            _number(value) for key, value in custom.items()
            if key.endswith("_one_cm") and key != "minecraft:fall_one_cm"
        )
        return {
            "play_seconds": int(play_ticks / TICKS_PER_SECOND),
            "deaths": int(_number(custom.get("minecraft:deaths"))),
            "mob_kills": int(_number(custom.get("minecraft:mob_kills"))),
            "player_kills": int(_number(custom.get("minecraft:player_kills"))),
            "jumps": int(_number(custom.get("minecraft:jump"))),
            "blocks_mined": int(sum(_number(v) for v in (stats.get("minecraft:mined") or {}).values())),
            "distance_km": round(distance_cm / 100000, 1),
        }
    # Antes de 1.13: claves planas como "stat.playOneMinute".
    distance_cm = sum(
        _number(value) for key, value in data.items()
        if key.startswith("stat.") and key.endswith("OneCm") and key != "stat.fallOneCm"
    )
    return {
        "play_seconds": int(_number(data.get("stat.playOneMinute")) / TICKS_PER_SECOND),
        "deaths": int(_number(data.get("stat.deaths"))),
        "mob_kills": int(_number(data.get("stat.mobKills"))),
        "player_kills": int(_number(data.get("stat.playerKills"))),
        "jumps": int(_number(data.get("stat.jump"))),
        "blocks_mined": int(sum(_number(v) for k, v in data.items() if k.startswith("stat.mineBlock."))),
        "distance_km": round(distance_cm / 100000, 1),
    }


def player_stats(modpack: str) -> dict:
    server_dir = DEFAULT_SERVERS_PATH / modpack
    world = parse_server_properties(modpack).get("level-name", "world") or "world"
    stats_dir = server_dir / world / "stats"
    names = _usercache(server_dir)
    players = []
    if stats_dir.is_dir():
        for path in stats_dir.glob("*.json"):
            uuid = path.stem.lower()
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            seen_file = server_dir / world / "playerdata" / (path.stem + ".dat")
            last_seen = (seen_file if seen_file.exists() else path).stat().st_mtime
            players.append({
                "uuid": uuid,
                "name": names.get(uuid),
                "last_seen": datetime.fromtimestamp(last_seen).isoformat(timespec="seconds"),
                **_summarize(data),
            })
    players = _merge_same_name(players, _pack_online_mode(modpack))
    players.sort(key=lambda p: p["play_seconds"], reverse=True)
    return {"world": world, "players": players}


def _merge_same_name(players: list, online: bool) -> list:
    """Junta las entradas de un mismo nombre (UUID premium + UUID offline)."""
    merged, order = {}, []
    for player in players:
        key = (player["name"] or "").lower() or player["uuid"]
        if key not in merged:
            merged[key] = [player]
            order.append(key)
        else:
            merged[key].append(player)
    result = []
    for key in order:
        group = merged[key]
        if len(group) == 1:
            result.append(group[0])
            continue
        name = group[0]["name"]
        wanted = offline_uuid(name) if not online else None
        current = next((p for p in group if p["uuid"] == wanted), None) if wanted else             next((p for p in group if p["uuid"] != offline_uuid(name)), None)
        current = current or max(group, key=lambda p: p["last_seen"])
        combined = {"uuid": current["uuid"], "name": name,
                    "last_seen": max(p["last_seen"] for p in group)}
        for field in ("play_seconds", "deaths", "mob_kills", "player_kills", "jumps", "blocks_mined"):
            combined[field] = sum(p[field] for p in group)
        combined["distance_km"] = round(sum(p["distance_km"] for p in group), 1)
        result.append(combined)
    return result
