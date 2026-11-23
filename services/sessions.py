"""
services/sessions.py - Partidas de los jugadores: quién ha jugado, en qué
servidor y de qué hora a qué hora. Se apuntan al leer en la consola
«X joined the game» / «X left the game» (services/server_control.py) y al
pararse el servidor se cierran las que quedaran abiertas.

Se guardan en SERVERS_PATH/.global/sessions.jsonl (una línea por partida
terminada: {"m": modpack, "p": jugador, "s": inicio, "e": fin}) durante
KEEP_DAYS días. Con ellas se calculan:

- heatmap(): a qué horas de cada día de la semana se juega.
- streak(): cuántos días seguidos ha jugado alguien (y la mejor racha).
- week_summary(): el resumen de los últimos 7 días (también va por
  Telegram/Discord los lunes, ver services/scheduler.py).
"""
import json
import threading
import time
from datetime import date, datetime, timedelta

from config import DEFAULT_SERVERS_PATH

SESSIONS_FILE = DEFAULT_SERVERS_PATH / ".global" / "sessions.jsonl"
KEEP_DAYS = 400
MIN_SECONDS = 30          # entrar y salir al momento no cuenta como partida
_lock = threading.Lock()
_open: dict = {}          # (modpack, jugador) -> inicio
_writes = 0


# ── Apuntar ──────────────────────────────────────────────────────────────────
def joined(modpack: str, player: str, at: float | None = None) -> None:
    with _lock:
        _open.setdefault((modpack, player), at or time.time())


def left(modpack: str, player: str, at: float | None = None) -> None:
    with _lock:
        start = _open.pop((modpack, player), None)
    if start is not None:
        _write(modpack, player, start, at or time.time())


def server_stopped(modpack: str, at: float | None = None) -> None:
    """El servidor se ha parado (o caído): las partidas abiertas terminan aquí."""
    end = at or time.time()
    with _lock:
        closing = [(key, start) for key, start in _open.items() if key[0] == modpack]
        for key, _ in closing:
            _open.pop(key, None)
    for (mod, player), start in closing:
        _write(mod, player, start, end)


def _write(modpack: str, player: str, start: float, end: float) -> None:
    global _writes
    if end - start < MIN_SECONDS:
        return
    record = {"m": modpack, "p": player, "s": int(start), "e": int(end)}
    try:
        with _lock:
            SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SESSIONS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            _writes += 1
            due = _writes % 200 == 0
        if due:
            trim()
    except OSError as e:
        print(f"[partidas] no se pudo apuntar: {e!r}", flush=True)


def trim(now: float | None = None) -> None:
    """Olvida las partidas de hace más de KEEP_DAYS días."""
    limit = (now or time.time()) - KEEP_DAYS * 86400
    with _lock:
        if not SESSIONS_FILE.exists():
            return
        lines = SESSIONS_FILE.read_text(encoding="utf-8").splitlines()
        keep = [line for line in lines if (record := _parse(line)) and record["e"] >= limit]
        if len(keep) != len(lines):
            tmp = SESSIONS_FILE.with_suffix(".tmp")
            tmp.write_text("".join(line + "\n" for line in keep), encoding="utf-8")
            tmp.replace(SESSIONS_FILE)


# ── Leer ─────────────────────────────────────────────────────────────────────
def _parse(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or not all(k in record for k in ("m", "p", "s", "e")):
        return None
    return record


def all_sessions(modpack: str | None = None, now: float | None = None) -> list:
    """Partidas terminadas y las que siguen abiertas (hasta ahora), por orden de inicio."""
    now = now or time.time()
    result = []
    with _lock:
        if SESSIONS_FILE.exists():
            for line in SESSIONS_FILE.read_text(encoding="utf-8").splitlines():
                record = _parse(line)
                if record:
                    result.append(record)
        result += [{"m": m, "p": p, "s": int(s), "e": int(now), "open": True}
                   for (m, p), s in _open.items()]
    if modpack:
        result = [r for r in result if r["m"] == modpack]
    return sorted(result, key=lambda r: r["s"])


def online_since() -> dict:
    """{jugador: inicio} de las partidas abiertas ahora mismo."""
    with _lock:
        return {p: s for (_, p), s in _open.items()}


def heatmap(days: int = 56, modpack: str | None = None, now: float | None = None) -> dict:
    """
    Minutos jugados (sumando jugadores) por día de la semana (0 = lunes) y
    hora, en hora local, de los últimos `days` días.
    """
    now = now or time.time()
    since = now - days * 86400
    grid = [[0.0] * 24 for _ in range(7)]
    for record in all_sessions(modpack, now):
        t = max(record["s"], since)
        end = min(record["e"], now)
        while t < end:
            moment = datetime.fromtimestamp(t)
            slot_end = (moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
            step_end = min(end, slot_end)
            grid[moment.weekday()][moment.hour] += (step_end - t) / 60
            t = step_end
    grid = [[round(value, 1) for value in row] for row in grid]
    return {"days": days, "grid": grid, "max": max(max(row) for row in grid)}


def play_days(modpack: str | None = None, now: float | None = None) -> set:
    """Días (fecha local) en los que alguien jugó."""
    found = set()
    for record in all_sessions(modpack, now):
        day = datetime.fromtimestamp(record["s"]).date()
        last = datetime.fromtimestamp(record["e"]).date()
        while day <= last:
            found.add(day)
            day += timedelta(days=1)
    return found


def streak(modpack: str | None = None, now: float | None = None) -> dict:
    """
    Racha actual de días seguidos con alguien jugando (cuenta hoy si ya ha
    jugado alguien; si no, termina ayer y aún se puede alargar) y la mejor.
    """
    days = play_days(modpack, now)
    today = datetime.fromtimestamp(now or time.time()).date()
    played_today = today in days
    day = today if played_today else today - timedelta(days=1)
    current = 0
    while day in days:
        current += 1
        day -= timedelta(days=1)
    best = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return {"current": current, "best": best, "today": played_today}


def week_summary(modpack: str | None = None, now: float | None = None, days: int = 7) -> dict:
    """Lo jugado en los últimos `days` días."""
    now = now or time.time()
    since = now - days * 86400
    sessions = all_sessions(modpack, now)
    first_seen: dict = {}
    for record in sessions:
        first_seen.setdefault(record["p"], record["s"])
    minutes: dict = {}
    by_weekday = [0.0] * 7
    count = 0
    longest = None
    for record in sessions:
        start, end = max(record["s"], since), min(record["e"], now)
        if end <= start:
            continue
        count += 1
        played = (end - start) / 60
        minutes[record["p"]] = minutes.get(record["p"], 0) + played
        by_weekday[datetime.fromtimestamp(start).weekday()] += played
        if longest is None or played > longest["minutes"]:
            longest = {"player": record["p"], "minutes": round(played)}
    top = sorted(minutes.items(), key=lambda item: -item[1])[:3]
    total = sum(minutes.values())
    return {
        "days": days,
        "players": len(minutes),
        "sessions": count,
        "hours": round(total / 60, 1),
        "top": [{"player": player, "minutes": round(value)} for player, value in top],
        "new_players": sorted(p for p, first in first_seen.items() if first >= since),
        "busiest_weekday": by_weekday.index(max(by_weekday)) if total else None,
        "longest": longest,
    }
