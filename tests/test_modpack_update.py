"""
Actualizar un servidor a otra versión de su modpack (services/modpack_update.py).
"""
import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from services import backups, modpack_update


def fabric_jar(mod_id: str, version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mod_id, "version": version}))
    return buf.getvalue()


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.server = root / "pack"
        self.staging = root / ".pack-update-pack"
        s, n = self.server, self.staging
        # Servidor actual (versión 1 del modpack + cosas tuyas).
        write(s / "mods/lithium-1.jar", fabric_jar("lithium", "1"))
        write(s / "mods/quitado-1.jar", fabric_jar("quitado", "1"))
        write(s / "mods/igual.jar", fabric_jar("igual", "1"))
        write(s / "mods/mio.jar", fabric_jar("mio", "1"))
        write(s / "mods/apagado.jar.disabled", fabric_jar("apagado", "1"))
        write(s / "config/lithium.properties", "viejo")
        write(s / "config/mio.toml", "mío")
        write(s / "world/level.dat", "mundo")
        write(s / "mundo2/level.dat", "otro mundo")
        write(s / "server.properties", "level-name=mundo2\nmotd=Mío\n")
        write(s / "ops.json", "[1]")
        write(s / "libraries/loader-1.jar", "l1")
        write(s / "run.sh", "viejo")
        # Instalación limpia de la versión 2.
        write(n / "mods/lithium-2.jar", fabric_jar("lithium", "2"))
        write(n / "mods/igual.jar", fabric_jar("igual", "1"))
        write(n / "mods/nuevo.jar", fabric_jar("nuevo", "1"))
        write(n / "config/lithium.properties", "nuevo")
        write(n / "mundo2/level.dat", "NO")
        write(n / "world/level.dat", "NO")
        write(n / "server.properties", "motd=A Minecraft Server\n")
        write(n / "ops.json", "[]")
        write(n / "libraries/loader-2.jar", "l2")
        write(n / "run.sh", "nuevo")
        write(n / ".pack_source.json", "{}")
        self.pack_mods = ["lithium-1.jar", "quitado-1.jar", "igual.jar"]

    def test_merge_keeps_yours_and_takes_the_new_pack(self):
        level = modpack_update._level_name(self.server)
        self.assertEqual(level, "mundo2")
        result = modpack_update.merge_into(self.staging, self.server, self.pack_mods, level)
        s = self.server
        self.assertEqual(sorted(p.name for p in (s / "mods").iterdir()),
                         ["apagado.jar.disabled", "igual.jar", "lithium-2.jar", "mio.jar", "nuevo.jar"])
        self.assertEqual(result["kept"], ["mio.jar"])
        self.assertEqual(result["removed"], ["quitado-1.jar"])
        self.assertEqual(result["replaced"], [{"old": "lithium-1.jar", "new": "lithium-2.jar"}])
        self.assertEqual((s / "config/lithium.properties").read_text(), "nuevo")
        self.assertEqual((s / "config/mio.toml").read_text(encoding="utf-8"), "mío")
        self.assertEqual((s / "mundo2/level.dat").read_text(), "otro mundo")
        self.assertEqual((s / "world/level.dat").read_text(), "mundo")
        self.assertIn("motd=Mío", (s / "server.properties").read_text(encoding="utf-8"))
        self.assertEqual((s / "ops.json").read_text(), "[1]")
        self.assertEqual((s / "run.sh").read_text(), "nuevo")
        # Las librerías del loader anterior se quedan: restaurar la copia sigue arrancando.
        self.assertTrue((s / "libraries/loader-1.jar").exists())
        self.assertTrue((s / "libraries/loader-2.jar").exists())

    def test_unknown_pack_mods_keeps_only_the_new_ones(self):
        result = modpack_update.merge_into(self.staging, self.server, None)
        self.assertFalse((self.server / "mods/mio.jar").exists())
        self.assertIn("mio.jar", result["removed"])
        self.assertTrue((self.server / "mods/apagado.jar.disabled").exists())


class SourceAndGuardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "pack/mods").mkdir(parents=True)
        (self.root / "pack/mods/a.jar").write_bytes(b"a")
        patcher = mock.patch.object(modpack_update, "DEFAULT_SERVERS_PATH", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_update(self, version_id="v2"):
        async def collect():
            return [e async for e in modpack_update.update_stream("pack", version_id)]
        return asyncio.run(collect())

    def test_record_and_link(self):
        self.assertIsNone(modpack_update.read_source("pack"))
        modpack_update.record_source(self.root / "pack", "modrinth", "abc", "v1", "1.0", "1.21.1", "fabric", "Pack")
        source = modpack_update.read_source("pack")
        self.assertEqual((source["version_id"], source["pack_mods"]), ("v1", ["a.jar"]))
        with self.assertRaises(ValueError):
            modpack_update.link_source("pack", "ftp", "x", None)
        modpack_update.link_source("pack", "curseforge", "123", "Otro")
        self.assertIsNone(modpack_update.read_source("pack")["pack_mods"])
        modpack_update.unlink_source("pack")
        self.assertIsNone(modpack_update.read_source("pack"))

    def test_guards(self):
        events = self.run_update()
        self.assertIn("no está vinculado", events[-1]["detail"])
        modpack_update.record_source(self.root / "pack", "modrinth", "abc", "v1", "1.0", "1.21.1", "fabric")
        self.assertIn("ya es la instalada", self.run_update("v1")[-1]["detail"])
        with mock.patch("services.server_control.running_modpack", return_value="pack"):
            self.assertIn("Para el servidor", self.run_update()[-1]["detail"])
        # Si la copia falla, no se toca nada más.
        with mock.patch.object(backups, "create_backup", side_effect=RuntimeError("sin sitio")), \
                mock.patch("services.modpack_install.install_modrinth_modpack_stream") as installer:
            events = self.run_update()
        self.assertFalse(events[-1]["success"])
        installer.assert_not_called()

    def test_full_backup_carries_the_source(self):
        modpack_update.record_source(self.root / "pack", "modrinth", "abc", "v1", "1.0", "1.21.1", "fabric")
        (self.root / "pack/.oculto").write_text("x")
        entries = backups.full_entries(self.root / "pack")
        self.assertIn(".pack_source.json", entries)
        self.assertNotIn(".oculto", entries)
        backups._check_entry_names({".pack_source.json", "mods"})
        with self.assertRaises(Exception):
            backups._check_entry_names({".oculto"})


if __name__ == "__main__":
    unittest.main()
