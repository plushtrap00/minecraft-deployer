"""
services/history.py - Historial de rendimiento por modpack: una muestra por
minuto (TPS, MSPT, jugadores y RAM) mientras el servidor está encendido, en
SERVERS_PATH/.global/history/<modpack>.jsonl. Se guardan 7 días.

Las muestras las toma services/scheduler.py aunque nadie tenga el panel
abierto. query() reduce el periodo pedido a unos cientos de puntos para la
gráfica.
"""
import json
import threading
import time

from config import DEFAULT_SERVERS_PATH

HISTORY_DIR = DEFAULT_SERVERS_PATH / ".global" / "history"
MAX_HOURS = 24 * 7
MAX_POINTS = 360
_lock = threading.Lock()


def _file(modpack: str):
    return HISTORY_DIR / (modpack + ".jsonl")


def append(modpack: str, sample: dict) -> None:
    record = {"t": int(sample.get("t") or time.time())}
    for key in ("tps", "mspt", "players", "ram"):
        value = sample.get(key)
        if isinstance(value, (int, float)):
            record[key] = round(float(value), 2)
    with _lock:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(_file(modpack), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def _read(modpack: str, since: float) -> list:
    path = _file(modpack)
    if not path.exists():
        return []
    samples = []
    with _lock, open(path, encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("t", 0) >= since:
                samples.append(record)
    return samples


def prune(modpack: str, now: float | None = None) -> None:
    """Quita lo que tenga más de 7 días (reescribe el archivo solo si hace falta)."""
    now = now or time.time()
    path = _file(modpack)
    if not path.exists():
        return
    keep = _read(modpack, now - MAX_HOURS * 3600)
    with _lock:
        with open(path, encoding="utf-8") as f:
            total = sum(1 for _ in f)
        if total == len(keep):
            return
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for record in keep:
                f.write(json.dumps(record) + "\n")
        tmp.replace(path)


def prune_all() -> None:
    if HISTORY_DIR.is_dir():
        for path in HISTORY_DIR.glob("*.jsonl"):
            prune(path.stem)


def query(modpack: str, hours: int, now: float | None = None) -> list:
    """
    Muestras de las últimas `hours` horas, agrupadas en como mucho MAX_POINTS
    tramos iguales: de cada tramo, la media de TPS/MSPT/RAM y el máximo de
    jugadores. Los tramos sin datos (servidor apagado) no aparecen; la gráfica
    deja ahí un hueco.
    """
    now = now or time.time()
    since = now - hours * 3600
    samples = _read(modpack, since)
    if not samples:
        return []
    bucket = max(60, (hours * 3600) / MAX_POINTS)
    groups: dict = {}
    for record in samples:
        groups.setdefault(int((record["t"] - since) // bucket), []).append(record)
    points = []
    for index in sorted(groups):
        group = groups[index]
        point = {"t": int(since + index * bucket + bucket / 2)}
        for key in ("tps", "mspt", "ram"):
            values = [r[key] for r in group if key in r]
            if values:
                point[key] = round(sum(values) / len(values), 2)
        players = [r["players"] for r in group if "players" in r]
        if players:
            point["players"] = max(players)
        points.append(point)
    return points
