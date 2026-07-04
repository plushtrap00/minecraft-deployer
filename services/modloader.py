"""
services/modloader.py - Descubrimiento y cambio de versión del modloader de un modpack.

Contiene:
- Consulta a las APIs oficiales de Forge/NeoForge/Fabric/Quilt para saber qué
  versiones de loader existen para una versión de Minecraft dada
- Verificación de si algún mod instalado dejaría de ser compatible con una
  versión de loader propuesta (usa loader_versions de read_mod_metadata)
- Instalación real: descarga el instalador oficial y lo corre contra la
  carpeta del server, con backup/restauración de los archivos que toca

Solo se permite cambiar entre versiones del MISMO tipo de loader y la MISMA
versión de Minecraft detectada (routes/modloader.py aplica esa restricción).
"""
import re
import json
import shutil
import asyncio
import urllib.request
import urllib.error
from pathlib import Path

from config import DEFAULT_SERVERS_PATH, TEMP_DIR
from services.modpack import (
    read_mod_metadata, mod_display_name, mc_version_compatible, _version_cache,
)

_HTTP_TIMEOUT = 15

# Nombres canónicos internos (como los usa esta app puertas adentro) vs. el
# valor que detect_modpack_version() reporta en el campo "modloader".
LOADER_DISPLAY_NAMES = {
    "neoforge": "NeoForge",
    "forge": "Forge",
    "fabric": "Fabric",
    "quilt": "Quilt",
}


def loader_key_from_display(modloader: str | None) -> str | None:
    """Convierte el valor de detect_modpack_version()['modloader'] a la clave interna."""
    if not modloader:
        return None
    low = modloader.lower()
    if "neoforge" in low:
        return "neoforge"
    if "forge" in low:
        return "forge"
    if "fabric" in low:
        return "fabric"
    if "quilt" in low:
        return "quilt"
    return None


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "minecraft-deployer"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return resp.read()


def _sort_versions_desc(versions: list) -> list:
    def key(v):
        return tuple(int(x) for x in re.findall(r'\d+', v))
    return sorted(set(versions), key=key, reverse=True)


# ── Descubrimiento de versiones disponibles ────────────────────────────────────

def _neoforge_versions_for(mc_version: str) -> list:
    m = re.match(r'^1\.(\d+)(?:\.(\d+))?$', mc_version)
    if not m:
        return []
    prefix = f"{m.group(1)}.{m.group(2) or '0'}."
    data = _http_get("https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml")
    text = data.decode("utf-8", errors="replace")
    all_versions = re.findall(r'<version>([^<]+)</version>', text)
    return _sort_versions_desc([v for v in all_versions if v.startswith(prefix)])


def _forge_versions_for(mc_version: str) -> list:
    data = _http_get("https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
    text = data.decode("utf-8", errors="replace")
    all_versions = re.findall(r'<version>([^<]+)</version>', text)
    prefix = f"{mc_version}-"
    return _sort_versions_desc([v for v in all_versions if v.startswith(prefix)])


def _fabric_versions_for(mc_version: str) -> list:
    data = _http_get(f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}")
    entries = json.loads(data.decode("utf-8", errors="replace"))
    return [e["loader"]["version"] for e in entries if e.get("loader", {}).get("version")]


def _quilt_versions_for(mc_version: str) -> list:
    data = _http_get(f"https://meta.quiltmc.org/v3/versions/loader/{mc_version}")
    entries = json.loads(data.decode("utf-8", errors="replace"))
    return [e["loader"]["version"] for e in entries if e.get("loader", {}).get("version")]


_VERSION_FETCHERS = {
    "neoforge": _neoforge_versions_for,
    "forge": _forge_versions_for,
    "fabric": _fabric_versions_for,
    "quilt": _quilt_versions_for,
}


def get_available_versions(loader_key: str, mc_version: str) -> list:
    """
    Devuelve las versiones del loader indicado compatibles con mc_version,
    de más reciente a más antigua. Lanza excepción si la consulta a la API
    oficial falla (el llamador debe traducirla en un error legible).
    """
    fetcher = _VERSION_FETCHERS.get(loader_key)
    if not fetcher or not mc_version:
        return []
    return fetcher(mc_version)


# ── Compatibilidad de mods instalados con una versión de loader propuesta ──────

def check_mod_compatibility(modpack: str, loader_key: str, target_version: str) -> list:
    """
    Revisa cada mod instalado y devuelve los que quedarían CLARAMENTE
    incompatibles con target_version (mismo criterio laxo que ya usa
    mc_version_compatible: solo bloquea si el rango declarado excluye la
    versión de forma inequívoca; datos ambiguos o sin poder interpretar no
    cuentan en contra).
    """
    mods_dir = DEFAULT_SERVERS_PATH / modpack / "mods"
    if not mods_dir.exists():
        return []

    incompatible = []
    for f in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        if not f.is_file():
            continue
        low = f.name.lower()
        if not (low.endswith(".jar") or low.endswith(".jar.disabled")):
            continue
        try:
            meta = read_mod_metadata(f.read_bytes())
        except Exception:
            continue
        ranges = meta.get("loader_versions", {}).get(loader_key)
        if not ranges:
            continue
        if not mc_version_compatible(target_version, ranges, bare_as_minimum=True):
            incompatible.append({
                "filename": f.name,
                "display_name": mod_display_name(f.name),
                "required": ", ".join(ranges),
            })
    return incompatible


# ── Instalación ─────────────────────────────────────────────────────────────────

_BACKUP_ROOT = TEMP_DIR / "modloader-backups"
_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

# Rutas conocidas que el instalador de cada loader crea o reemplaza (relativas
# a la carpeta del server). Todo lo demás (mods/, config/, mundos, logs...) no
# se toca ni se respalda.
_LOADER_ARTIFACTS = [
    "libraries", "run.sh", "run.bat", "user_jvm_args.txt", "fabric-server-launch.jar",
    "variables.txt", "Variables.txt",
]


def _installer_url(loader_key: str, mc_version: str, target_version: str) -> tuple:
    """Devuelve (url_instalador, args_de_instalación) para el loader/versión dados."""
    if loader_key == "neoforge":
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{target_version}/neoforge-{target_version}-installer.jar"
        return url, ["--installServer"]
    if loader_key == "forge":
        url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{target_version}/forge-{target_version}-installer.jar"
        return url, ["--installServer"]
    if loader_key == "fabric":
        meta = _http_get("https://maven.fabricmc.net/net/fabricmc/fabric-installer/maven-metadata.xml")
        installer_ver = re.findall(r'<version>([^<]+)</version>', meta.decode("utf-8", errors="replace"))[-1]
        url = f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/{installer_ver}/fabric-installer-{installer_ver}.jar"
        return url, ["server", "-mcversion", mc_version, "-loader", target_version, "-downloadMinecraft"]
    if loader_key == "quilt":
        meta = _http_get("https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/maven-metadata.xml")
        installer_ver = re.findall(r'<version>([^<]+)</version>', meta.decode("utf-8", errors="replace"))[-1]
        url = f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/{installer_ver}/quilt-installer-{installer_ver}.jar"
        return url, ["install", "server", mc_version, target_version, "--download-server"]
    raise ValueError(f"Loader no soportado: {loader_key}")


def _update_variables_txt(server_dir: Path, modloader_version: str):
    """
    detect_modpack_version() prioriza variables.txt sobre los nombres de jar;
    si existe hay que actualizar MODLOADER_VERSION ahí o la app seguiría
    mostrando la versión vieja aunque los archivos ya se hayan reemplazado.
    """
    for fname in ["variables.txt", "Variables.txt"]:
        vfile = server_dir / fname
        if not vfile.exists():
            continue
        text = vfile.read_text(encoding="utf-8", errors="replace")
        if re.search(r'(?m)^MODLOADER_VERSION\s*=', text):
            text = re.sub(
                r'(?m)^(MODLOADER_VERSION\s*=\s*)"?[^"\n]*"?\s*$',
                lambda m: m.group(1) + f'"{modloader_version}"',
                text,
            )
            vfile.write_text(text, encoding="utf-8")
        return


def _backup_artifacts(server_dir: Path, backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in _LOADER_ARTIFACTS:
        src = server_dir / name
        if not src.exists():
            continue
        dst = backup_dir / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def _restore_artifacts(server_dir: Path, backup_dir: Path):
    for name in _LOADER_ARTIFACTS:
        current = server_dir / name
        if current.exists():
            if current.is_dir():
                shutil.rmtree(current, ignore_errors=True)
            else:
                current.unlink(missing_ok=True)
        backed_up = backup_dir / name
        if backed_up.exists():
            if backed_up.is_dir():
                shutil.copytree(backed_up, current)
            else:
                shutil.copy2(backed_up, current)


async def install_loader_stream(modpack: str, loader_key: str, mc_version: str, target_version: str):
    """
    Generador async que instala target_version del loader en el modpack, cediendo
    dicts de progreso: {"type": "log"|"done"|"error", ...}. Hace backup de los
    artefactos conocidos del loader antes de arrancar y los restaura si algo falla.
    """
    server_dir = DEFAULT_SERVERS_PATH / modpack
    backup_dir = _BACKUP_ROOT / f"{modpack}-{loader_key}-{target_version}".replace("/", "_")
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    try:
        yield {"type": "log", "message": "Respaldando archivos actuales del modloader..."}
        await asyncio.to_thread(_backup_artifacts, server_dir, backup_dir)

        yield {"type": "log", "message": f"Descargando instalador de {LOADER_DISPLAY_NAMES.get(loader_key, loader_key)} {target_version}..."}
        url, install_args = await asyncio.to_thread(_installer_url, loader_key, mc_version, target_version)
        installer_path = backup_dir / "installer.jar"
        await asyncio.to_thread(lambda: installer_path.write_bytes(_http_get(url)))

        yield {"type": "log", "message": "Ejecutando instalador..."}
        proc = await asyncio.create_subprocess_exec(
            # El instalador corre con cwd=server_dir, así que installer_path
            # tiene que ser absoluto (TEMP_DIR es una ruta relativa al directorio
            # desde el que arrancó la app, no al del modpack).
            "java", "-jar", str(installer_path.resolve()), *install_args,
            cwd=str(server_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                yield {"type": "log", "message": line}
        returncode = await proc.wait()

        if returncode != 0:
            raise RuntimeError(f"El instalador terminó con código de salida {returncode}")

        await asyncio.to_thread(_update_variables_txt, server_dir, target_version)
        _version_cache.pop(modpack, None)
        yield {"type": "done", "success": True, "version": target_version}

    except Exception as e:
        yield {"type": "log", "message": f"Error: {e}. Restaurando archivos anteriores..."}
        try:
            await asyncio.to_thread(_restore_artifacts, server_dir, backup_dir)
            _version_cache.pop(modpack, None)
            yield {"type": "done", "success": False, "detail": str(e), "restored": True}
        except Exception as restore_error:
            yield {
                "type": "done", "success": False,
                "detail": f"{e} — Además falló la restauración: {restore_error}. Revisa la carpeta del server manualmente.",
                "restored": False,
            }
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
