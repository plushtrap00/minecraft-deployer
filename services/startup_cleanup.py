"""
services/startup_cleanup.py - Limpieza antes de arrancar el panel (la llama
main.py en __main__, antes de uvicorn):

- Libera el puerto web si lo ocupa una instancia anterior del propio panel.
- Para con calma (save-all + stop por RCON) los servidores de Minecraft que
  quedaron huérfanos de una ejecución anterior, y si no responden los mata.
- Libera el puerto 25565 si lo ocupa un servidor del panel.
- Borra los session.lock abandonados por servidores que se cayeron.

Nunca toca procesos ajenos al panel: solo los que reconoce como propios por
su carpeta de trabajo o su línea de comandos.
"""
import os
import re
import subprocess
import time
from pathlib import Path


_APP_DIR = Path(__file__).resolve().parent.parent


def _proc_cwd(pid) -> Path | None:
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
    except (OSError, ValueError):
        return None


def _proc_cmdline(pid) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _is_under(path: Path | None, base: Path) -> bool:
    if path is None:
        return False
    try:
        path.relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _is_previous_panel(pid) -> bool:
    """Otra instancia de este mismo panel (python .../main.py desde esta carpeta)."""
    cmdline = _proc_cmdline(pid)
    return "main.py" in cmdline and (_proc_cwd(pid) == _APP_DIR or str(_APP_DIR) in cmdline)


def _is_our_minecraft(pid) -> bool:
    """Un proceso lanzado dentro de la carpeta de servidores del panel."""
    from config import DEFAULT_SERVERS_PATH
    return _is_under(_proc_cwd(pid), DEFAULT_SERVERS_PATH)


def _pids_on_port(port: int) -> list:
    pids = []
    try:
        result = subprocess.run(["ss", "-tlnp", "sport", "=", f":{port}"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if str(port) in line:
                pids.extend(int(p) for p in re.findall(r'pid=(\d+)', line))
    except (OSError, ValueError):
        pass
    if not pids:
        try:
            result = subprocess.run(["fuser", f"{port}/tcp"], capture_output=True, text=True)
            pids.extend(int(p) for p in result.stdout.split() if p.strip().isdigit())
        except OSError:
            pass
    return sorted(set(pid for pid in pids if pid != os.getpid()))


def kill_port(port: int, is_ours) -> tuple[list, list]:
    """
    Libera el puerto TCP matando los procesos que lo ocupan, pero SOLO los que
    is_ours(pid) reconoce como propios. Antes se mataba cualquier cosa que
    estuviera en el puerto (otra aplicación, o un servidor de Minecraft que no
    había lanzado el panel). Devuelve (matados, ajenos que se dejaron vivos).
    """
    killed, foreign = [], []
    for pid in _pids_on_port(port):
        if not is_ours(pid):
            foreign.append(pid)
            continue
        try:
            os.kill(pid, 9)
            killed.append(pid)
        except OSError:
            pass
    return killed, foreign


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except (ValueError, TypeError):
        return False


def _graceful_stop_orphan(pid: str) -> bool:
    """
    Intenta un apagado limpio (save-all + stop por RCON) de un proceso Java
    huérfano antes de recurrir a SIGKILL. Al arrancar el panel de cero no hay
    ningún Popen vivo con stdin propio para este PID (pertenecía al proceso
    anterior), así que la única vía de apagado ordenado disponible es RCON —
    para eso hay que averiguar de qué modpack es este proceso resolviendo su
    directorio de trabajo real (/proc/<pid>/cwd, Linux) y leyendo su propio
    server.properties. Devuelve True si se confirma que paró solo a tiempo.
    """
    from config import DEFAULT_SERVERS_PATH
    from app_constants import GRACEFUL_STOP_TIMEOUT_SECONDS
    from services.modpack import parse_server_properties
    from services.rcon import RconConnection, RconError

    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return False

    server_dir = Path(cwd)
    try:
        server_dir.resolve().relative_to(DEFAULT_SERVERS_PATH.resolve())
    except ValueError:
        return False  # no es una carpeta de modpack conocida, no arriesgarse

    props = parse_server_properties(server_dir.name)
    if props.get("enable-rcon") != "true":
        return False

    port_str = props.get("rcon.port", "").strip()
    password = props.get("rcon.password", "").strip()
    if not port_str.isdigit() or not password:
        return False

    host = props.get("server-ip", "").strip() or "127.0.0.1"
    conn = RconConnection(host, int(port_str), password)
    try:
        conn.command("save-all")
        conn.command("stop")
    except (RconError, OSError):
        return False
    finally:
        conn.close()

    deadline = time.time() + GRACEFUL_STOP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.5)
    return False


def kill_orphan_servers() -> list:
    """
    Limpia procesos Java residuales de ejecuciones anteriores del servidor
    Minecraft. Solo toca los que corren DENTRO de la carpeta de servidores del
    panel: antes bastaba con que la línea de comandos mencionara "minecraft"
    o "forge", y se llevaba por delante cualquier otro servidor del equipo.
    Antes de matarlos con SIGKILL, intenta un apagado limpio por RCON
    (save-all + stop) para no arriesgar el mundo en cada reinicio del panel.
    """
    killed = []
    try:
        result = subprocess.run(["pgrep", "-x", "java"], capture_output=True, text=True)
    except OSError:
        return killed
    for pid in result.stdout.split():
        if not pid.isdigit() or not _is_our_minecraft(pid):
            continue
        stopped_gracefully = _graceful_stop_orphan(pid)
        if not stopped_gracefully and _pid_alive(pid):
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass
        tag = "apagado limpio" if stopped_gracefully else "SIGKILL"
        killed.append(f"{pid} ({_proc_cmdline(pid)[:60]}) [{tag}]")
    return killed


def clean_orphan_locks() -> list:
    """Elimina archivos session.lock abandonados por servidores que crashearon."""
    from config import DEFAULT_SERVERS_PATH
    cleaned = []
    try:
        if not DEFAULT_SERVERS_PATH.exists():
            return cleaned
        for modpack_dir in DEFAULT_SERVERS_PATH.iterdir():
            if not modpack_dir.is_dir() or modpack_dir.name.startswith("."):
                continue
            for lock in modpack_dir.rglob("session.lock"):
                try:
                    lock.unlink()
                    cleaned.append(str(lock.relative_to(DEFAULT_SERVERS_PATH)))
                except Exception:
                    pass
    except Exception:
        pass
    return cleaned


def run_startup_cleanup(web_port: int) -> None:
    """Todo lo anterior, en orden y contándolo por consola."""
    print(f"Liberando puerto {web_port} si lo ocupa una instancia anterior del panel...")
    web_killed, web_foreign = kill_port(web_port, _is_previous_panel)
    if web_killed:
        print(f"  Eliminados {len(web_killed)} proceso(s) en el puerto {web_port}: {web_killed}")
        time.sleep(1)
    if web_foreign:
        print(f"  ⚠️  El puerto {web_port} lo usa otro programa (PID {web_foreign}); no se toca. "
              "Cambia WEB_PORT en .env si el panel no puede arrancar.")
    if not web_killed and not web_foreign:
        print(f"  Puerto {web_port} libre.")

    # Antes del kill duro por puerto: intenta un apagado limpio (save-all +
    # stop por RCON) de cualquier server huérfano, para no arriesgar el mundo
    # en cada simple reinicio del panel. El kill por puerto de abajo queda
    # como red de seguridad final para lo que no haya podido pararse solo.
    print("Buscando procesos huérfanos de servidores anteriores...")
    killed = kill_orphan_servers()
    if killed:
        print(f"  Procesados {len(killed)} proceso(s) huérfano(s):")
        for k in killed:
            print(f"    - {k}")
    else:
        print("  No se encontraron procesos huérfanos.")

    print("Liberando puerto 25565 si lo ocupa un servidor del panel...")
    port_killed, port_foreign = kill_port(25565, _is_our_minecraft)
    if port_killed:
        print(f"  Eliminados {len(port_killed)} proceso(s) en el puerto 25565: {port_killed}")
        time.sleep(1)
    if port_foreign:
        print(f"  ⚠️  El puerto 25565 lo usa un programa ajeno al panel (PID {port_foreign}); no se toca.")
    if not port_killed and not port_foreign:
        print("  Puerto 25565 libre.")

    print("Limpiando session.lock abandonados...")
    locks = clean_orphan_locks()
    if locks:
        print(f"  Eliminados {len(locks)} session.lock abandonado(s):")
        for l in locks:
            print(f"    - {l}")
    else:
        print("  No se encontraron session.lock abandonados.")
