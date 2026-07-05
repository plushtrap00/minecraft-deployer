"""
services/server_create.py - Creación de servidores nuevos desde cero.

A diferencia de services/modloader.py (que cambia la versión de loader de un
modpack YA EXISTENTE), este módulo arranca de una carpeta vacía: descubre
versiones de Minecraft vanilla (API oficial de Mojang), reusa la descarga/
instalación de modloader ya existente para Forge/NeoForge/Fabric/Quilt, y
escribe los archivos base (server.properties, eula.txt, run.sh, variables.txt)
para que el resto de la app funcione con el servidor desde el primer arranque.
"""
import re
import os
import json
import stat
import shutil
import asyncio
from pathlib import Path

from config import DEFAULT_SERVERS_PATH
from services.modloader import _http_get, _installer_url, LOADER_DISPLAY_NAMES
from services.utils import configure_jvm_ram
from services.players import ensure_global_dir, read_global_file, PLAYER_FILES

_VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

_SERVER_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def get_vanilla_mc_versions() -> list:
    """Versiones "release" de Minecraft vanilla, más reciente primero (API oficial de Mojang)."""
    data = json.loads(_http_get(_VERSION_MANIFEST_URL))
    return [v["id"] for v in data["versions"] if v["type"] == "release"]


def _vanilla_server_jar_url(mc_version: str) -> str:
    data = json.loads(_http_get(_VERSION_MANIFEST_URL))
    entry = next((v for v in data["versions"] if v["id"] == mc_version), None)
    if not entry:
        raise ValueError(f"Versión de Minecraft no encontrada: {mc_version}")
    version_data = json.loads(_http_get(entry["url"]))
    server_info = version_data.get("downloads", {}).get("server")
    if not server_info:
        raise ValueError(f"La versión {mc_version} no tiene server.jar oficial (probablemente muy antigua)")
    return server_info["url"]


def validate_new_server_name(name: str) -> None:
    """Lanza ValueError con un mensaje legible si el nombre no sirve para crear la carpeta."""
    if not name or not _SERVER_NAME_RE.match(name):
        raise ValueError("Nombre inválido: solo letras, números, guiones y guiones bajos (sin espacios)")
    if (DEFAULT_SERVERS_PATH / name).exists():
        raise ValueError(f'Ya existe una carpeta "{name}" en servers-minecraft')


def _write_run_script(server_dir: Path, jar_name: str, ram_min: str, ram_max: str) -> None:
    """
    Genera un run.sh mínimo para los casos que no traen uno propio: el
    instalador oficial de Forge/NeoForge SÍ genera el suyo (se reusa tal
    cual), pero Fabric, Quilt y el server.jar vanilla no.
    """
    script = "#!/bin/bash\n" + f"java -Xms{ram_min} -Xmx{ram_max} -jar {jar_name} nogui\n"
    run_path = server_dir / "run.sh"
    run_path.write_text(script, encoding="utf-8")
    run_path.chmod(run_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _bootstrap_common_files(server_dir: Path, mc_version: str, loader_key: str | None, loader_version: str | None) -> None:
    """
    server.properties mínimo + eula ya aceptada (mismo criterio que ya usa
    _accept_eula en services/process.py: se acepta sin preguntar) + los
    archivos globales de jugadores, igual que ya hace upload_and_extract al
    importar un modpack existente, para que ops/whitelist/bans sean
    consistentes en todos los servers desde el primer arranque.
    """
    props_file = server_dir / "server.properties"
    if not props_file.exists():
        props_file.write_text(
            "motd=A Minecraft Server\n"
            "server-port=25565\n"
            "max-players=20\n"
            "level-name=world\n"
            "online-mode=true\n"
            "white-list=false\n"
            "difficulty=easy\n"
            "gamemode=survival\n",
            encoding="utf-8",
        )
    (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")

    # El loader la crea solo al primer arranque, pero el objetivo es poder
    # subir mods ANTES de arrancar el server por primera vez (routes/modpacks.py
    # ::upload_mod exige que mods/ ya exista) — vanilla no tiene este concepto.
    if loader_key:
        (server_dir / "mods").mkdir(exist_ok=True)

    ensure_global_dir()
    for fname in PLAYER_FILES:
        data = read_global_file(fname)
        if data:
            (server_dir / fname).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # detect_modpack_version() prioriza variables.txt: sin esto, la app no
    # reconocería el modloader/versión hasta el primer parseo de nombres de jar.
    loader_display = LOADER_DISPLAY_NAMES.get(loader_key, "Vanilla") if loader_key else "Vanilla"
    lines = [f'MINECRAFT_VERSION="{mc_version}"\n', f'MODLOADER="{loader_display}"\n']
    if loader_version:
        lines.append(f'MODLOADER_VERSION="{loader_version}"\n')
    (server_dir / "variables.txt").write_text("".join(lines), encoding="utf-8")


async def create_server_stream(
    name: str, mc_version: str, loader_key: str | None, loader_version: str | None,
    ram_min: str, ram_max: str,
):
    """
    Generador async que crea un servidor nuevo desde cero. Cede dicts de
    progreso {"type": "log"|"done", ...}. Asume que name/mc_version/loader_key/
    loader_version YA fueron validados por el llamador (routes/create_server.py) —
    aquí solo se maneja lo que puede fallar durante la propia descarga/instalación,
    limpiando la carpeta creada si algo se rompe a mitad de camino.
    """
    server_dir = DEFAULT_SERVERS_PATH / name
    server_dir.mkdir(parents=True)

    try:
        if not loader_key or loader_key == "vanilla":
            yield {"type": "log", "message": f"Descargando server.jar vanilla {mc_version}..."}
            jar_url = await asyncio.to_thread(_vanilla_server_jar_url, mc_version)
            jar_bytes = await asyncio.to_thread(_http_get, jar_url)
            (server_dir / "server.jar").write_bytes(jar_bytes)
            await asyncio.to_thread(_write_run_script, server_dir, "server.jar", ram_min, ram_max)

        else:
            loader_display = LOADER_DISPLAY_NAMES.get(loader_key, loader_key)
            yield {"type": "log", "message": f"Descargando instalador de {loader_display} {loader_version}..."}
            url, install_args = await asyncio.to_thread(_installer_url, loader_key, mc_version, loader_version)
            installer_path = server_dir / "installer.jar"
            jar_bytes = await asyncio.to_thread(_http_get, url)
            installer_path.write_bytes(jar_bytes)

            yield {"type": "log", "message": "Ejecutando instalador..."}
            proc = await asyncio.create_subprocess_exec(
                "java", "-jar", str(installer_path.resolve()), *install_args,
                cwd=str(server_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                if len(line) > 500:
                    line = line[:500] + "… [línea truncada]"
                yield {"type": "log", "message": line}
            returncode = await proc.wait()
            installer_path.unlink(missing_ok=True)

            if returncode != 0:
                raise RuntimeError(f"El instalador terminó con código de salida {returncode}")

            if loader_key in ("fabric", "quilt"):
                jar_name = "fabric-server-launch.jar" if loader_key == "fabric" else "quilt-server-launch.jar"
                if not (server_dir / jar_name).exists():
                    raise RuntimeError(f"El instalador no generó {jar_name} como se esperaba")
                await asyncio.to_thread(_write_run_script, server_dir, jar_name, ram_min, ram_max)
            else:
                # Forge/NeoForge generan su propio run.sh + user_jvm_args.txt;
                # solo hace falta aplicarles la RAM elegida.
                await asyncio.to_thread(configure_jvm_ram, server_dir, ram_min, ram_max)

        await asyncio.to_thread(_bootstrap_common_files, server_dir, mc_version, loader_key, loader_version)
        yield {"type": "done", "success": True, "name": name}

    except Exception as e:
        shutil.rmtree(server_dir, ignore_errors=True)
        yield {"type": "done", "success": False, "detail": str(e)}
