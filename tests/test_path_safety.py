"""
Las rutas que reciben un nombre o una ruta del navegador (configuración,
KubeJS, archivos del mundo, logs, mods) no pueden salirse de la carpeta del
servidor: ni leer el .env de al lado, ni escribir ni borrar fuera.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from routes import deps, logs, mod_files, mods, worlds

HOSTILE = ["../server.properties", "../../secreto.txt", "config/../../secreto.txt", "/etc/passwd"]


class PathSafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "servers"
        self.pack = self.root / "pack"
        for folder in ("config", "kubejs/server_scripts", "logs", "mods", "world"):
            (self.pack / folder).mkdir(parents=True)
        (self.pack / "config" / "mod.toml").write_text("a=1", encoding="utf-8")
        (self.pack / "kubejs" / "server_scripts" / "main.js").write_text("// hola", encoding="utf-8")
        (self.pack / "world" / "level.dat_old").write_text("mundo", encoding="utf-8")
        (self.pack / "server.properties").write_text("rcon.password=x", encoding="utf-8")
        (self.pack / "mods" / "lithium.jar").write_bytes(b"jar")
        (self.root.parent / "secreto.txt").write_text("no tocar", encoding="utf-8")
        (self.root / ".global").mkdir()
        for module in (deps, mod_files, mods, worlds):
            patcher = mock.patch.object(module, "DEFAULT_SERVERS_PATH", self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def refused(self, call, *codes):
        with self.assertRaises(HTTPException) as ctx:
            call()
        self.assertIn(ctx.exception.status_code, codes or (400, 403, 404))
        return ctx.exception.status_code

    def untouched(self):
        self.assertEqual((self.root.parent / "secreto.txt").read_text(encoding="utf-8"), "no tocar")
        self.assertEqual((self.pack / "server.properties").read_text(encoding="utf-8"), "rcon.password=x")

    def test_modpack_and_world_names(self):
        for bad in ("..", ".", ".global", "a/b", "a\\b", "", "pack\x00"):
            self.refused(lambda: deps.modpack_path(bad), 400)
        self.refused(lambda: deps.modpack_path("no-existe"), 404)
        self.assertEqual(deps.modpack_path("pack"), self.pack)
        for bad in ("..", "../pack", ".hidden", "a/b"):
            self.refused(lambda: deps.world_path(self.pack, bad), 400)

    def test_config_files(self):
        self.assertEqual(mod_files.get_config_file("pack", "mod.toml").status_code, 200)
        request = SimpleNamespace(state=SimpleNamespace())
        for path in HOSTILE:
            self.refused(lambda: mod_files.get_config_file("pack", path), 403)
            self.refused(lambda: mod_files.save_config_file(request, "pack", path, "pwned"), 403)
        self.untouched()

    def test_kubejs_files(self):
        for path in HOSTILE:
            self.refused(lambda: mod_files.get_kubejs_file("pack", path), 403)
            self.refused(lambda: mod_files.save_kubejs_file("pack", path, "pwned"), 403)
            self.refused(lambda: mod_files.delete_kubejs_file("pack", path), 403)
            self.refused(lambda: mod_files.move_kubejs_file("pack", "server_scripts/main.js", path), 403)
            self.refused(lambda: mod_files.move_kubejs_file("pack", path, "robado.txt"), 403)
        self.refused(lambda: mod_files.create_kubejs_file("pack", "server_scripts", "../x.js"), 400)
        self.refused(lambda: mod_files.create_kubejs_file("pack", "../..", "x.js"), 400)
        self.assertTrue((self.pack / "kubejs" / "server_scripts" / "main.js").exists())
        self.untouched()

    def test_world_files(self):
        self.assertEqual(worlds.get_world_file("pack", "world", "level.dat_old").status_code, 200)
        for path in HOSTILE:
            self.refused(lambda: worlds.get_world_file("pack", "world", path), 403)
            self.refused(lambda: worlds.save_world_file("pack", "world", path, "pwned"), 403)
        self.refused(lambda: worlds.get_world_file("pack", "..", "pack/server.properties"), 400)
        self.untouched()

    def test_logs_and_mods(self):
        for name in ("../server.properties", "..", "a/b.log", "a\\b.log"):
            self.refused(lambda: logs._find_log_or_crash_path(self.pack, name), 403)
        request = SimpleNamespace(state=SimpleNamespace())
        for name in ("../server.properties", "../../secreto.txt"):
            self.refused(lambda: mods.toggle_mod(request, "pack", name), 403)
        self.assertTrue((self.pack / "mods" / "lithium.jar").exists())
        self.untouched()


if __name__ == "__main__":
    unittest.main()
