"""
services/metrics.py - Métricas en tiempo real del servidor Minecraft.

Contiene:
- mc_metrics: dict con el estado actual (TPS, RAM, jugadores, CPU...)
- mc_start_time: momento de arranque del servidor
- _parse_metrics_line(): parsea una línea de consola y actualiza mc_metrics
- read_proc_ram(): lee la RAM del proceso desde /proc/<pid>/status
"""
import re
import datetime
from pathlib import Path

# ── Estado de métricas ─────────────────────────────────────────────────────────
mc_metrics: dict = {
    "players_online": [],
    "players_max": 20,
    "tps": None,
    "mspt": None,
    "cpu_process": None,
    "cpu_system": None,
    "ram_used_mb": None,
    "ram_max_mb": None,
    "uptime_seconds": 0,
    "last_updated": None,
    "spark_available": False,
}

mc_start_time: datetime.datetime | None = None


# ── Parseo de líneas de consola ────────────────────────────────────────────────
def _parse_metrics_line(line: str):
    """Extrae métricas de una línea de consola y actualiza mc_metrics."""

    # Jugador entró
    join = re.search(r'(\w+) joined the game', line)
    if join:
        name = join.group(1)
        if name not in mc_metrics["players_online"]:
            mc_metrics["players_online"].append(name)

    # Jugador salió
    leave = re.search(r'(\w+) left the game', line)
    if leave:
        name = leave.group(1)
        if name in mc_metrics["players_online"]:
            mc_metrics["players_online"].remove(name)

    # Spark TPS (líneas con ⚡)
    if mc_metrics["spark_available"] and '[⚡]' in line:
        tps_spark = re.search(r'\[⚡\]\s*\*?([\d.]+),\s*\*?([\d.]+)', line)
        if tps_spark and 'TPS from' not in line and 'Tick' not in line and 'CPU' not in line:
            mc_metrics["tps"] = float(tps_spark.group(1))

        mspt_spark = re.search(r'\[⚡\]\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+;', line)
        if mspt_spark:
            mc_metrics["mspt"] = float(mspt_spark.group(1))

        cpu_sys = re.search(r'\[⚡\]\s*(\d+)%.*\(system\)', line)
        if cpu_sys:
            mc_metrics["cpu_system"] = int(cpu_sys.group(1))

        cpu_proc = re.search(r'\[⚡\]\s*(\d+)%.*\(process\)', line)
        if cpu_proc:
            mc_metrics["cpu_process"] = int(cpu_proc.group(1))

    # NeoForge/Forge: "Overall: 20.00 TPS, 49.78 MSPT"
    tps_m = re.search(r'Overall[:\s]+([\d.]+)\s*TPS.*?([\d.]+)\s*MSPT', line, re.IGNORECASE)
    if tps_m:
        mc_metrics["tps"] = float(tps_m.group(1))
        mc_metrics["mspt"] = float(tps_m.group(2))
    else:
        tps_m2 = re.search(r'Overall[:\s]+([\d.]+)\s*TPS[^/]*/\s*([\d.]+)\s*ms', line, re.IGNORECASE)
        if tps_m2:
            mc_metrics["tps"] = float(tps_m2.group(1))
            mc_metrics["mspt"] = float(tps_m2.group(2))

    # Fabric/Carpet: "TPS: 20.0, MSPT: 49.7"
    tps_fab = re.search(r'TPS[:\s]+([\d.]+).*?MSPT[:\s]+([\d.]+)', line, re.IGNORECASE)
    if tps_fab:
        mc_metrics["tps"] = float(tps_fab.group(1))
        mc_metrics["mspt"] = float(tps_fab.group(2))

    # Vanilla: "The server is running at 20.0/20 ticks per second"
    tps_v = re.search(r'running at ([\d.]+)/20 ticks per second', line, re.IGNORECASE)
    if tps_v:
        mc_metrics["tps"] = float(tps_v.group(1))

    # Fallback genérico
    tps_gen = re.search(r'([\d.]+)\s*tps.*?([\d.]+)\s*ms', line, re.IGNORECASE)
    if tps_gen and mc_metrics["tps"] is None:
        mc_metrics["tps"] = float(tps_gen.group(1))
        mc_metrics["mspt"] = float(tps_gen.group(2))

    # RAM desde JVM: "Used Memory: 1234 MB / 4096 MB"
    ram_m = re.search(r'[Uu]sed [Mm]emory:\s*(\d+)\s*MB\s*/\s*(\d+)\s*MB', line)
    if ram_m:
        mc_metrics["ram_used_mb"] = int(ram_m.group(1))
        mc_metrics["ram_max_mb"] = int(ram_m.group(2))

    # Conteo de jugadores del /list
    list_m = re.search(r'[Tt]here are (\d+) of a max(?: of)? (\d+) players online', line)
    if list_m:
        mc_metrics["players_max"] = int(list_m.group(2))

    mc_metrics["last_updated"] = datetime.datetime.utcnow().isoformat()


# ── RAM desde /proc ────────────────────────────────────────────────────────────
def _get_child_pids(pid: int) -> list:
    """Devuelve todos los PIDs del arbol de procesos hijos (incluyendo el propio)."""
    pids = [pid]
    try:
        children_path = Path(f"/proc/{pid}/task/{pid}/children")
        if children_path.exists():
            for child in children_path.read_text().split():
                pids.extend(_get_child_pids(int(child)))
        else:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    for line in (entry / "status").read_text().splitlines():
                        if line.startswith("PPid:") and int(line.split()[1]) == pid:
                            pids.extend(_get_child_pids(int(entry.name)))
                except Exception:
                    pass
    except Exception:
        pass
    return pids


def _read_pid_vmrss_kb(pid: int) -> int:
    """Lee VmRSS en KB de un PID. Devuelve 0 si falla."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 0


def _find_java_pid(root_pid: int):
    """Busca el PID del proceso java con mas RAM dentro del arbol de root_pid."""
    java_pids = []
    for pid in _get_child_pids(root_pid):
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b'\x00', b' ').decode(errors='replace')
            if 'java' in cmdline.lower():
                java_pids.append(pid)
        except Exception:
            pass
    if not java_pids:
        return None
    return max(java_pids, key=_read_pid_vmrss_kb)


def read_proc_ram(root_pid: int):
    """
    Lee la RAM real del proceso Java del servidor.
    Busca el java dentro del arbol de procesos del script de arranque
    y lee su VmRSS desde /proc/<pid>/status.
    """
    java_pid = _find_java_pid(root_pid)
    target_pid = java_pid if java_pid else root_pid
    try:
        for line in Path(f"/proc/{target_pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                mc_metrics["ram_used_mb"] = round(int(line.split()[1]) / 1024, 1)
            elif line.startswith("VmPeak:"):
                mc_metrics["ram_max_mb"] = round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
