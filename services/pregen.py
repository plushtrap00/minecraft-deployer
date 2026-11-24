"""
services/pregen.py - Pregenerar el mundo con Chunky.

Chunky (https://modrinth.com/mod/chunky, GPL-3.0) es un mod solo de servidor
que genera de antemano el terreno en un radio. El panel:

- Comprueba si hay Chunky para el loader y la versión de Minecraft del
  servidor (Modrinth). Vanilla o versiones viejas: no se ofrece.
- Lo instala solo si una persona lo pide (y lo puede quitar). Los mods que
  instala el panel para sí mismo se apuntan en .panel-mods.json: el paquete
  para jugadores no los lleva y «Actualizar modpack» los conserva.
- Lleva la tarea por la consola: manda los comandos de Chunky, lee sus
  mensajes de progreso y, si se pide, la pausa cuando entra alguien y la
  sigue cuando el servidor se queda vacío o vuelve a arrancar.
- Calcula cuánto disco hará falta con los datos de ESE mundo (lo que ocupa
  de media un chunk en sus archivos de región) y no empieza si no cabe.

El estado vive en <servidor>/.pregen.json. Si Chunky cambia el formato de
sus mensajes (o está en otro idioma), la tarea sigue funcionando: solo deja
de verse el porcentaje.
"""
import hashlib
import json
import math
import re
import shutil
import threading
import time
import urllib.parse
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.secure_files import atomic_write_text

PANEL_MODS_FILE = ".panel-mods.json"
STATE_FILE = ".pregen.json"
CHUNKY_PROJECT = "chunky"
MODRINTH = "https://api.modrinth.com/v2"

# Dimensiones que se ofrecen: (id de Chunky, carpeta de regiones dentro del mundo).
DIMENSIONS = {
    "minecraft:overworld": "region",
    "minecraft:the_nether": "DIM-1/region",
    "minecraft:the_end": "DIM1/region",
}
MIN_RADIUS, MAX_RADIUS = 100, 30000
# Lo que queda libre en disco después de pregenerar, como mínimo.
DISK_RESERVE_BYTES = 2 * 1024 ** 3
# Sin datos del propio mundo (recién creado): lo que suele ocupar un chunk
# generado sin explorar. Solo para la estimación, que entonces se marca como aproximada.
FALLBACK_BYTES_PER_CHUNK = 12 * 1024
# Chunky avisa de su progreso cada segundo por defecto: cada 30 basta y no llena la consola.
QUIET_SECONDS = 30
LOW_RAM_BYTES = 1536 * 1024 ** 2

_CHUNKY_JAR_RE = re.compile(r"(?i)^chunky[-_].*\.jar$")
_CHAT_RE = re.compile(r"\]:\s*<[^>]+>")
_RUNNING_RE = re.compile(
    r"Task running for (\S+?)\.? Processed: (\d+) chunks \(([\d.,]+)%\)"
    r"(?:, ETA: (\d+):(\d+):(\d+))?(?:, Rate: ([\d.,]+) cps)?")
_DONE_RE = re.compile(r"Task finished for (\S+?)\.? Processed: (\d+) chunks")
_ALREADY_RE = re.compile(r"A task was already started for this world")
_NO_DISK_RE = re.compile(r"The server only has (.+?) disk space remaining")

_lock = threading.RLock()
_last_save = 0.0
_live: dict = {}  # modpack → (dimensión, último progreso)


class PregenError(Exception):
    pass


# ── Archivos ──────────────────────────────────────────────────────────────────

def _server_dir(modpack: str) -> Path:
    return DEFAULT_SERVERS_PATH / modpack


def panel_mods(server_dir: Path) -> dict:
    """{función: jar} de los mods que ha instalado el panel para sí mismo."""
    try:
        data = json.loads((server_dir / PANEL_MODS_FILE).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_panel_mods(server_dir: Path, mods: dict) -> None:
    path = server_dir / PANEL_MODS_FILE
    if mods:
        atomic_write_text(path, json.dumps(mods, indent=2))
    elif path.exists():
        path.unlink()


def load_state(modpack: str) -> dict:
    """El estado guardado, con el último progreso leído de la consola (que se guarda menos a menudo)."""
    try:
        data = json.loads((_server_dir(modpack) / STATE_FILE).read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    live = _live.get(modpack)
    if live and data.get("current") == live[0]:
        data["progress"] = live[1]
    return data


def _save_state(modpack: str, state: dict, force: bool = True) -> None:
    """Con force=False (progreso), al disco como mucho una vez cada 20 s; en memoria, siempre."""
    global _last_save
    if state.get("current") and state.get("progress"):
        _live[modpack] = (state["current"], state["progress"])
    else:
        _live.pop(modpack, None)
    now = time.monotonic()
    if not force and now - _last_save < 20:
        return
    _last_save = now
    path = _server_dir(modpack) / STATE_FILE
    if state:
        atomic_write_text(path, json.dumps(state, indent=2))
    elif path.exists():
        path.unlink()


# ── Chunky: ¿está?, ¿hay versión?, instalar y quitar ──────────────────────────

def find_chunky(server_dir: Path) -> str | None:
    """El jar de Chunky que tenga el servidor (lo pusiera el panel o no)."""
    mods = server_dir / "mods"
    if not mods.is_dir():
        return None
    for path in sorted(mods.iterdir()):
        if path.is_file() and _CHUNKY_JAR_RE.match(path.name):
            return path.name
    return None


def _server_versions(modpack: str) -> tuple:
    from services.modloader import loader_key_from_display
    from services.modpack import detect_modpack_version
    info = detect_modpack_version(modpack)
    return info.get("mc_version"), loader_key_from_display(info.get("modloader"))


def _best_file(project: str, mc: str, loader: str) -> dict | None:
    """La última versión (mejor estable) de un proyecto de Modrinth para este loader y Minecraft."""
    from services import mod_updates
    query = urllib.parse.urlencode({
        "loaders": json.dumps(["fabric" if loader == "quilt" else loader]),
        "game_versions": json.dumps([mc]),
    })
    versions = mod_updates._get_list(f"{MODRINTH}/project/{project}/version?{query}")
    versions = sorted(versions, key=lambda v: (v.get("version_type") == "release", v.get("date_published") or ""), reverse=True)
    for version in versions:
        file = next((f for f in version.get("files") or [] if f.get("primary")), None) or (version.get("files") or [None])[0]
        if file and file.get("url", "").startswith("https://cdn.modrinth.com/"):
            return {"version": version.get("version_number"), "filename": file["filename"],
                    "url": file["url"], "sha512": (file.get("hashes") or {}).get("sha512"),
                    "sha1": (file.get("hashes") or {}).get("sha1"), "size": file.get("size"),
                    "requires": [d["project_id"] for d in version.get("dependencies") or []
                                 if d.get("dependency_type") == "required" and d.get("project_id")]}
    return None


def _installed_projects(server_dir: Path) -> set:
    """Proyectos de Modrinth de los mods del servidor (por hash)."""
    from services import mod_updates
    jars = [p for p in mod_updates._mod_files(server_dir / "mods") if p.name.endswith(".jar")]
    if not jars:
        return set()
    hashes = mod_updates._hashes(server_dir, jars, set(), prune=False)
    found = mod_updates._post(f"{MODRINTH}/version_files",
                              {"hashes": sorted({h["sha1"] for h in hashes.values()}), "algorithm": "sha1"})
    return {v.get("project_id") for v in found.values() if v.get("project_id")}


def available_version(modpack: str) -> dict:
    """
    {"ok": True, "version", "filename", ..., "dependencies": [lo que falta, con su
    "title"]} o {"ok": False, "reason": texto}. Quilt usa la versión de Fabric.
    Las dependencias obligatorias de Chunky (Fabric API en Fabric) que el servidor
    no tenga se instalan con él, y se dice antes.
    """
    mc, loader = _server_versions(modpack)
    if not loader:
        return {"ok": False, "reason": "Chunky necesita un servidor con mods (Fabric, Forge, NeoForge o Quilt); este no tiene modloader."}
    if not mc:
        return {"ok": False, "reason": "No se ha podido saber la versión de Minecraft de este servidor."}
    chunky = _best_file(CHUNKY_PROJECT, mc, loader)
    if not chunky:
        return {"ok": False, "reason": f"Chunky no tiene versión para {loader} {mc}."}
    deps = []
    if chunky["requires"]:
        from services import mod_updates
        installed = _installed_projects(_server_dir(modpack))
        for project in chunky["requires"]:
            if project in installed:
                continue
            file = _best_file(project, mc, loader)
            if not file:
                return {"ok": False, "reason": f"Chunky necesita otro mod que no tiene versión para {loader} {mc}."}
            info = mod_updates._get_list(f"{MODRINTH}/projects?ids=" + urllib.parse.quote(json.dumps([project])))
            deps.append({**file, "project_id": project, "title": (info[0] if info else {}).get("title") or project})
    return {"ok": True, **chunky, "dependencies": deps}


def _download_into(mods: Path, file: dict) -> None:
    from services.mod_search import download_bytes
    data = download_bytes(file["url"])
    if file.get("sha512") and hashlib.sha512(data).hexdigest() != file["sha512"]:
        raise PregenError(f"La descarga de {file['filename']} no coincide con la de Modrinth; no se ha instalado")
    if not file.get("sha512") and file.get("sha1") and hashlib.sha1(data).hexdigest() != file["sha1"]:
        raise PregenError(f"La descarga de {file['filename']} no coincide con la de Modrinth; no se ha instalado")
    tmp = mods / (file["filename"] + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(mods / file["filename"])


def install(modpack: str) -> dict:
    server_dir = _server_dir(modpack)
    if find_chunky(server_dir):
        raise PregenError("Chunky ya está instalado en este servidor")
    version = available_version(modpack)
    if not version["ok"]:
        raise PregenError(version["reason"])
    mods = server_dir / "mods"
    mods.mkdir(exist_ok=True)
    # Primero lo que necesita (si algo falla, Chunky no queda a medias sin ello).
    # Las dependencias son mods normales: se quedan aunque luego se quite Chunky,
    # porque otros mods pueden usarlas.
    for dep in version["dependencies"]:
        _download_into(mods, dep)
    _download_into(mods, version)
    with _lock:
        marks = panel_mods(server_dir)
        marks["chunky"] = version["filename"]
        _save_panel_mods(server_dir, marks)
    return {"filename": version["filename"], "version": version["version"],
            "dependencies": [d["filename"] for d in version["dependencies"]]}


def uninstall(modpack: str) -> None:
    """Solo lo que instaló el panel, con el servidor parado y sin tarea a medias."""
    from services import server_control
    server_dir = _server_dir(modpack)
    if server_control.running_modpack() == modpack:
        raise PregenError("Para quitar Chunky, para antes el servidor")
    if _active(load_state(modpack)):
        raise PregenError("Hay una pregeneración a medias: cancélala antes de quitar Chunky")
    with _lock:
        marks = panel_mods(server_dir)
        filename = marks.get("chunky")
        if not filename:
            raise PregenError("Este Chunky no lo instaló el panel: quítalo desde Mods si quieres")
        jar = server_dir / "mods" / filename
        if jar.is_file():
            jar.unlink()
        marks.pop("chunky", None)
        _save_panel_mods(server_dir, marks)


# ── Estimación ────────────────────────────────────────────────────────────────

_REGION_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")


SAMPLE_CHUNKS = 300
_STATUS_TAG = b"\x08\x00\x06Status"


def _chunk_is_full(path: Path, sector: int) -> bool | None:
    """¿El chunk está generado del todo (Status «full»)? None si no se puede leer."""
    import gzip
    import zlib
    try:
        with path.open("rb") as f:
            f.seek(sector * 4096)
            length = int.from_bytes(f.read(4), "big")
            kind = f.read(1)[0]
            raw = f.read(max(0, length - 1))
        if kind == 1:
            data = gzip.decompress(raw)
        elif kind == 2:
            data = zlib.decompress(raw)
        elif kind == 3:
            data = raw
        else:
            return None  # LZ4 o en un .mcc aparte: no se mira
    except (OSError, IndexError, zlib.error, EOFError, ValueError):
        return None
    at = data.find(_STATUS_TAG)
    if at < 0:
        return None
    start = at + len(_STATUS_TAG)
    size = int.from_bytes(data[start:start + 2], "big")
    return data[start + 2:start + 2 + size].endswith(b"full")


def _region_stats(region_dir: Path, window: tuple) -> dict:
    """
    Chunks guardados en region/ (cabecera de cada .mca: 1024 entradas de 4 bytes,
    los 3 primeros el sector donde empieza y el último cuántos sectores de 4 KiB
    ocupa), en total y dentro de window = (x0, z0, x1, z1) en coordenadas de chunk.

    Alrededor de lo generado Minecraft deja chunks a medio hacer, que son
    pequeños y luego hay que completar: contarlos como hechos hacía quedarse muy
    corto. Por eso se mira una muestra de chunks (su Status): qué parte de los de
    dentro están completos y cuánto ocupa de verdad uno completo.
    """
    import random
    rng = random.Random(0)
    out = {"inside": 0, "inside_full": 0, "inside_checked": 0, "full_sizes": []}
    if not region_dir.is_dir():
        return out
    x0, z0, x1, z1 = window
    inside_sample, any_sample, seen_any = [], [], 0
    for path in region_dir.iterdir():
        match = _REGION_RE.match(path.name)
        if not match:
            continue
        rx, rz = int(match.group(1)), int(match.group(2))
        try:
            with path.open("rb") as f:
                header = f.read(4096)
        except OSError:
            continue
        for i in range(len(header) // 4):
            entry = int.from_bytes(header[i * 4:i * 4 + 4], "big")
            if not entry:
                continue
            cx, cz = rx * 32 + i % 32, rz * 32 + i // 32
            item = (path, entry >> 8, (entry & 0xFF) * 4096, cx, cz)
            # Muestreo uniforme sin guardarlo todo (reservoir sampling).
            seen_any += 1
            if len(any_sample) < SAMPLE_CHUNKS:
                any_sample.append(item)
            elif (j := rng.randrange(seen_any)) < SAMPLE_CHUNKS:
                any_sample[j] = item
            if x0 <= cx <= x1 and z0 <= cz <= z1:
                out["inside"] += 1
                if len(inside_sample) < SAMPLE_CHUNKS:
                    inside_sample.append(item)
                elif (j := rng.randrange(out["inside"])) < SAMPLE_CHUNKS:
                    inside_sample[j] = item
    checked = {}
    for item in inside_sample + any_sample:
        if item not in checked:
            checked[item] = _chunk_is_full(item[0], item[1])
    for item in inside_sample:
        if checked[item] is not None:
            out["inside_checked"] += 1
            out["inside_full"] += checked[item]
    out["full_sizes"] = [item[2] for item, full in checked.items() if full]
    return out


def _world_dir(server_dir: Path) -> Path:
    from services.modpack_update import _level_name
    return server_dir / _level_name(server_dir)


def _nbt_spawn(data: bytes) -> tuple | None:
    """SpawnX/SpawnZ (o spawn.pos en versiones recientes) de un level.dat ya descomprimido."""
    import struct
    pos = [0]
    found = {}

    def read(fmt):
        size = struct.calcsize(fmt)
        value = struct.unpack_from(">" + fmt, data, pos[0])
        pos[0] += size
        return value[0]

    def name():
        length = read("H")
        text = data[pos[0]:pos[0] + length].decode("utf-8", "replace")
        pos[0] += length
        return text

    def payload(tag, key, depth):
        if depth > 64:
            raise ValueError
        if tag == 1:
            read("b")
        elif tag == 2:
            read("h")
        elif tag == 3:
            value = read("i")
            if key in ("SpawnX", "SpawnZ"):
                found.setdefault(key, value)
        elif tag in (4, 6):
            pos[0] += 8
        elif tag == 5:
            pos[0] += 4
        elif tag == 7:
            pos[0] += read("i")
        elif tag == 8:
            name()
        elif tag == 9:
            item, count = read("b"), read("i")
            for _ in range(count):
                payload(item, None, depth + 1)
        elif tag == 10:
            while True:
                child = read("b")
                if child == 0:
                    break
                payload(child, name(), depth + 1)
        elif tag == 11:
            count = read("i")
            values = struct.unpack_from(f">{count}i", data, pos[0])
            pos[0] += 4 * count
            if key == "pos" and count >= 3:
                found.setdefault("pos", values)
        elif tag == 12:
            pos[0] += 8 * read("i")
        else:
            raise ValueError

    root = read("b")
    name()
    payload(root, "", 0)
    if "SpawnX" in found and "SpawnZ" in found:
        return found["SpawnX"], found["SpawnZ"]
    if "pos" in found:
        return found["pos"][0], found["pos"][2]
    return None


def _spawn(server_dir: Path) -> tuple:
    """El spawn del mundo (bloques). Si no se puede leer, 0, 0."""
    import gzip
    try:
        spawn = _nbt_spawn(gzip.decompress((_world_dir(server_dir) / "level.dat").read_bytes()))
    except Exception:  # noqa: BLE001 - mundo sin estrenar o level.dat raro
        spawn = None
    return spawn or (0, 0)


def centers(server_dir: Path) -> dict:
    """Centro de cada dimensión: el spawn; en el Nether, ese punto entre 8 (donde llevan los portales); el End, 0, 0."""
    x, z = _spawn(server_dir)
    return {"minecraft:overworld": (x, z), "minecraft:the_nether": (x // 8, z // 8), "minecraft:the_end": (0, 0)}


def chunks_in_radius(radius: int) -> int:
    """Chunky, forma cuadrada (la de serie): un cuadrado de 2·radio de lado."""
    side = 2 * math.ceil(radius / 16) + 1
    return side * side


def _window(center: tuple, radius: int) -> tuple:
    half = math.ceil(radius / 16)
    cx, cz = center[0] // 16, center[1] // 16
    return cx - half, cz - half, cx + half, cz + half


def estimate(modpack: str, radius: int, dimensions: list) -> dict:
    server_dir = _server_dir(modpack)
    world = _world_dir(server_dir)
    dims_center = centers(server_dir)
    total_chunks = existing = 0
    full_sizes = []
    for dim in dimensions:
        stats = _region_stats(world / DIMENSIONS[dim], _window(dims_center[dim], radius))
        # De los que ya hay dentro, solo cuentan los completos (en la proporción de la muestra).
        if stats["inside_checked"]:
            existing += round(stats["inside"] * stats["inside_full"] / stats["inside_checked"])
        full_sizes += stats["full_sizes"]
        total_chunks += chunks_in_radius(radius)
    # Lo que ocupa un chunk completo en ESTE mundo; sin bastantes para medirlo
    # (mundo casi sin estrenar), una cifra típica y se avisa de que es aproximado.
    approx = len(full_sizes) < 30
    per_chunk = sum(full_sizes) / len(full_sizes) if not approx else FALLBACK_BYTES_PER_CHUNK
    new_chunks = max(0, total_chunks - existing)
    # +10 %: el borde a medio hacer que Minecraft deja alrededor de lo generado.
    need = int(new_chunks * per_chunk * 1.1)
    free = shutil.disk_usage(server_dir).free
    return {"radius": radius, "chunks": total_chunks, "existing": existing, "new_chunks": new_chunks,
            "bytes_per_chunk": int(per_chunk), "bytes": need, "approx": approx,
            "free": free, "enough": free - need >= DISK_RESERVE_BYTES, "reserve": DISK_RESERVE_BYTES}


def _low_ram() -> bool:
    try:
        import psutil
        return psutil.virtual_memory().available < LOW_RAM_BYTES
    except Exception:  # noqa: BLE001 - es solo un aviso
        return False


# ── Estado y órdenes ──────────────────────────────────────────────────────────

def _active(state: dict) -> bool:
    return state.get("status") in ("running", "paused_players", "waiting")


def status(modpack: str) -> dict:
    from services import server_control
    from services.metrics import mc_metrics
    server_dir = _server_dir(modpack)
    jar = find_chunky(server_dir)
    running_here = server_control.running_modpack() == modpack
    state = load_state(modpack)
    return {
        "chunky": {"filename": jar, "by_panel": bool(jar) and panel_mods(server_dir).get("chunky") == jar},
        "state": state,
        "server_running": running_here,
        "players": len(mc_metrics.get("players_online") or []) if running_here else 0,
        "low_ram": _low_ram(),
        "dimensions": list(DIMENSIONS),
        "limits": {"min": MIN_RADIUS, "max": MAX_RADIUS},
    }


def start(modpack: str, radius: int, dimensions: list, only_when_empty: bool, username: str | None) -> dict:
    server_dir = _server_dir(modpack)
    if not find_chunky(server_dir):
        raise PregenError("Primero hay que instalar Chunky")
    if not MIN_RADIUS <= radius <= MAX_RADIUS:
        raise PregenError(f"El radio tiene que estar entre {MIN_RADIUS} y {MAX_RADIUS} bloques")
    dims = [d for d in DIMENSIONS if d in dimensions]
    if not dims:
        raise PregenError("Elige al menos una dimensión")
    with _lock:
        if _active(load_state(modpack)):
            raise PregenError("Ya hay una pregeneración en marcha en este servidor")
        est = estimate(modpack, radius, dims)
        if not est["enough"]:
            raise PregenError("No hay espacio suficiente en disco para pregenerar ese radio")
        state = {"radius": radius, "dimensions": dims, "pending": list(dims), "done": [],
                 "only_when_empty": bool(only_when_empty), "status": "waiting", "current": None,
                 "progress": None, "started_at": int(time.time()), "started_by": username,
                 "centers": {d: list(c) for d, c in centers(server_dir).items() if d in dims},
                 "estimate": {"chunks": est["chunks"], "bytes": est["bytes"], "approx": est["approx"]}}
        _save_state(modpack, state)
    _kick(modpack)
    return load_state(modpack)


def cancel(modpack: str) -> None:
    from services import server_control
    with _lock:
        state = load_state(modpack)
        if not _active(state):
            raise PregenError("No hay ninguna pregeneración en marcha")
        if server_control.running_modpack() == modpack and state.get("current"):
            _send("chunky cancel")
            _send("chunky confirm")
        _save_state(modpack, {**state, "status": "cancelled", "current": None, "finished_at": int(time.time())})


def _send(command: str) -> bool:
    from services import server_control
    try:
        server_control.send_command(command)
        return True
    except Exception:  # noqa: BLE001 - sin servidor no hay nada que mandar
        return False


def _empty() -> bool:
    from services.metrics import mc_metrics
    return not (mc_metrics.get("players_online") or [])


def _kick(modpack: str) -> None:
    """Pone en marcha lo que toque si el servidor está listo (y vacío, si se pidió)."""
    from services import process as proc_module
    from services import server_control
    with _lock:
        state = load_state(modpack)
        if not _active(state) or server_control.running_modpack() != modpack or not proc_module.mc_ready:
            return
        if state["only_when_empty"] and not _empty():
            if state["status"] != "paused_players":
                _save_state(modpack, {**state, "status": "paused_players"})
            return
        _send(f"chunky quiet {QUIET_SECONDS}")
        if state.get("current"):
            # Chunky guarda la tarea al pausar o al apagarse el servidor.
            _send("chunky continue")
            _save_state(modpack, {**state, "status": "running"})
        else:
            _begin_next(modpack, state)


def _begin_next(modpack: str, state: dict) -> None:
    pending = list(state.get("pending") or [])
    if not pending:
        _finish(modpack, state)
        return
    dim = pending[0]
    # El mismo centro con el que se calculó la estimación (no «chunky spawn»).
    x, z = (state.get("centers") or {}).get(dim) or centers(_server_dir(modpack))[dim]
    for command in (f"chunky world {dim}", f"chunky center {x} {z}", f"chunky radius {state['radius']}", "chunky start"):
        _send(command)
    _save_state(modpack, {**state, "status": "running", "current": dim, "progress": None})


def _finish(modpack: str, state: dict) -> None:
    from services.notify import notify
    from services import activity
    _save_state(modpack, {**state, "status": "done", "current": None, "finished_at": int(time.time())})
    notify("task", f"🗺️ Pregeneración terminada en {modpack}.")
    activity.record("world.pregen_done", params={"modpack": modpack})


# ── Sucesos del servidor (los llama server_control) ───────────────────────────

def on_ready(modpack: str) -> None:
    # Unos segundos después de «Done»: los mods terminan de cargar y Chunky
    # retoma su tarea guardada antes de que le lleguen comandos.
    timer = threading.Timer(10, _kick, args=(modpack,))
    timer.daemon = True
    timer.start()


def on_players_changed(modpack: str) -> None:
    with _lock:
        state = load_state(modpack)
        if not _active(state) or not state.get("only_when_empty"):
            return
        if not _empty() and state["status"] == "running":
            _send("chunky pause")
            _save_state(modpack, {**state, "status": "paused_players"})
        elif _empty() and state["status"] == "paused_players":
            _kick(modpack)


def on_exit(modpack: str) -> None:
    with _lock:
        state = load_state(modpack)
        if state.get("status") in ("running", "paused_players"):
            _save_state(modpack, {**state, "status": "waiting"})


def on_line(modpack: str, line: str) -> None:
    if "Task " not in line and "A task" not in line and "disk space" not in line:
        return
    if _CHAT_RE.search(line):
        return  # alguien lo ha escrito en el chat
    with _lock:
        state = load_state(modpack)
        if not _active(state):
            return
        match = _RUNNING_RE.search(line)
        if match:
            world, chunks, percent, h, m, s, rate = match.groups()
            if world != state.get("current"):
                return
            state["progress"] = {
                "chunks": int(chunks), "percent": float(percent.replace(",", ".")),
                "eta_seconds": int(h) * 3600 + int(m) * 60 + int(s) if h else None,
                "rate": float(rate.replace(",", ".")) if rate else None, "at": int(time.time()),
            }
            _save_state(modpack, state, force=False)
            return
        match = _DONE_RE.search(line)
        if match and match.group(1) == state.get("current"):
            state["done"] = (state.get("done") or []) + [{"dimension": state["current"], "chunks": int(match.group(2))}]
            state["pending"] = [d for d in state.get("pending") or [] if d != state["current"]]
            state["current"] = None
            _begin_next(modpack, state)
            return
        if _ALREADY_RE.search(line):
            _send("chunky continue")
            return
        match = _NO_DISK_RE.search(line)
        if match:
            _send("chunky cancel")
            _send("chunky confirm")
            _save_state(modpack, {**state, "status": "error", "current": None,
                                  "error": "Chunky dice que no queda espacio en disco"})
