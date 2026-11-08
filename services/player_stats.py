"""
services/player_stats.py - Estadísticas de los jugadores de un modpack,
leídas de lo que el propio Minecraft guarda en el mundo:

- <mundo>/stats/<uuid>.json: tiempo jugado, muertes, bichos, bloques picados,
  distancia... (formato 1.13+ con "stats", y el plano «stat.xxx» de antes).
- usercache.json (en la carpeta del servidor): de UUID a nombre.
- <mundo>/playerdata/<uuid>.dat: la fecha de modificación es la última vez
  que el servidor guardó al jugador (al salir o en el autoguardado).
"""
import json
from datetime import datetime
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.modpack import parse_server_properties

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
    players.sort(key=lambda p: p["play_seconds"], reverse=True)
    return {"world": world, "players": players}
