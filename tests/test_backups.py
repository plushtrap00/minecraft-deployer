"""
Copias de seguridad (services/backups.py): del mundo y completas, restaurar,
destino secundario y espacio en disco. Todo en carpetas temporales.
"""
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from services import automation, backups, modpack


def make_server(root: Path, name: str = "pack") -> Path:
    server = root / name
    (server / "world" / "region").mkdir(parents=True)
    (server / "world" / "region" / "r.0.0.mca").write_bytes(b"mundo-original")
    (server / "world" / "session.lock").write_bytes(b"x")
    (server / "world_nether").mkdir()
    (server / "mods").mkdir()
    (server / "mods" / "a.jar").write_bytes(b"mod-a")
    (server / "config").mkdir()
    (server / "config" / "a.toml").write_text("x = 1\n", encoding="utf-8")
    (server / "libraries" / "net").mkdir(parents=True)
    (server / "libraries" / "net" / "forge.jar").write_bytes(b"lib")
    (server / "logs").mkdir()
    (server / "logs" / "latest.log").write_text("log", encoding="utf-8")
    (server / "server.properties").write_text("level-name=world\nmotd=hola\n", encoding="utf-8")
    (server / "ops.json").write_text("[]", encoding="utf-8")
    (server / "server.log").write_text("x", encoding="utf-8")
    (server / ".restore-old").mkdir()
    return server


class BackupsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.servers = self.tmp / "servers"
        self.servers.mkdir()
        self.server = make_server(self.servers)
        for patcher in (
            mock.patch.object(backups, "DEFAULT_SERVERS_PATH", self.servers),
            mock.patch.object(modpack, "DEFAULT_SERVERS_PATH", self.servers),
            mock.patch.object(backups, "BACKUPS_DIR", self.servers / ".global" / "backups"),
            mock.patch.object(automation, "AUTOMATION_FILE", self.servers / ".global" / "automation.json"),
            # Las copias al destino secundario se hacen aquí mismo, sin hilos.
            mock.patch.object(backups, "sync_mirror_in_background", lambda modpacks=None: backups.sync_mirror(modpacks)),
            mock.patch("services.server_control.running_modpack", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def zip_names(self, name: str) -> set:
        with zipfile.ZipFile(backups.backup_file("pack", name)) as zf:
            return {entry.rstrip("/") for entry in zf.namelist()}

    def test_world_backup_only_has_the_world(self):
        result = backups.create_backup("pack")
        self.assertEqual(result["kind"], "world")
        self.assertFalse(result["name"].endswith("__full.zip"))
        names = self.zip_names(result["name"])
        self.assertIn("world/region/r.0.0.mca", names)
        self.assertIn("world_nether", names)
        self.assertNotIn("world/session.lock", names)
        self.assertFalse(any(n.startswith(("mods", "config")) for n in names))

    def test_full_backup_has_everything_but_the_regenerable(self):
        result = backups.create_backup("pack", full=True)
        self.assertTrue(result["name"].endswith("__manual__full.zip"))
        names = self.zip_names(result["name"])
        for expected in ("mods/a.jar", "config/a.toml", "server.properties", "ops.json", "world/region/r.0.0.mca"):
            self.assertIn(expected, names)
        for skipped in ("libraries", "logs", "server.log", ".restore-old"):
            self.assertFalse(any(n == skipped or n.startswith(skipped + "/") for n in names), skipped)
        item = backups.list_backups("pack")[0]
        self.assertEqual((item["kind"], item["kind_label"], item["local"], item["mirrored"]), ("full", "Completa", True, False))

    def test_full_restore_puts_the_server_back(self):
        name = backups.create_backup("pack", full=True)["name"]
        # Cambios después de la copia: un mod nuevo, otro borrado, config y mundo distintos.
        (self.server / "mods" / "a.jar").unlink()
        (self.server / "mods" / "b.jar").write_bytes(b"mod-b")
        (self.server / "config" / "a.toml").write_text("x = 2\n", encoding="utf-8")
        (self.server / "world" / "region" / "r.0.0.mca").write_bytes(b"mundo-cambiado")
        (self.server / "server.properties").write_text("level-name=world\nmotd=otro\n", encoding="utf-8")
        time.sleep(1.1)  # que la copia de seguridad previa no choque de nombre
        result = backups.restore_backup("pack", name)
        self.assertEqual(result["kind"], "full")
        self.assertTrue(result["safety_backup"].endswith("__safety__full.zip"))
        self.assertEqual(sorted(p.name for p in (self.server / "mods").iterdir()), ["a.jar"])
        self.assertEqual((self.server / "config" / "a.toml").read_text(encoding="utf-8"), "x = 1\n")
        self.assertEqual((self.server / "world" / "region" / "r.0.0.mca").read_bytes(), b"mundo-original")
        self.assertIn("motd=hola", (self.server / "server.properties").read_text(encoding="utf-8"))
        # Lo que no va en la copia sigue ahí.
        self.assertTrue((self.server / "libraries" / "net" / "forge.jar").is_file())
        self.assertTrue((self.server / "logs" / "latest.log").is_file())

    def test_world_restore_does_not_touch_mods(self):
        name = backups.create_backup("pack")["name"]
        (self.server / "mods" / "b.jar").write_bytes(b"mod-b")
        (self.server / "world" / "region" / "r.0.0.mca").write_bytes(b"mundo-cambiado")
        time.sleep(1.1)
        backups.restore_backup("pack", name)
        self.assertTrue((self.server / "mods" / "b.jar").is_file())
        self.assertEqual((self.server / "world" / "region" / "r.0.0.mca").read_bytes(), b"mundo-original")

    def test_world_zip_with_mods_is_rejected(self):
        folder = backups.backup_dir("pack")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "world__20260101-000000__manual.zip", "w") as zf:
            zf.writestr("world/level.dat", "x")
            zf.writestr("mods/evil.jar", "x")
        with self.assertRaises(HTTPException) as ctx:
            backups.restore_backup("pack", "world__20260101-000000__manual.zip")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_not_enough_space(self):
        fake = mock.Mock(free=10 * 1024 * 1024, total=100 * 1024 ** 3)
        with mock.patch.object(backups.shutil, "disk_usage", return_value=fake):
            with self.assertRaises(HTTPException) as ctx:
                backups.create_backup("pack")
        self.assertEqual(ctx.exception.status_code, 507)
        self.assertIn("quedan 10 MB libres", ctx.exception.detail)
        self.assertEqual(backups.list_backups("pack"), [])
        self.assertFalse(any(backups.backup_dir("pack").glob("*.part")))
        fake = mock.Mock(free=5 * 1024 ** 3, total=100 * 1024 ** 3)
        with mock.patch.object(backups.shutil, "disk_usage", return_value=fake):
            self.assertTrue(backups.disk_info()["low"])

    def test_human_sizes_have_no_decimals(self):
        self.assertEqual(backups._human(1536 * 1024 * 1024), "1536 MB")
        self.assertEqual(backups._human(25 * 1024 ** 3), "25 GB")
        self.assertEqual(backups._human(10), "1 MB")

    def test_mirror_validation(self):
        mirror = self.tmp / "nas"
        with self.assertRaises(ValueError):
            backups.validate_mirror_dir("relativa/carpeta")
        with self.assertRaises(ValueError):
            backups.validate_mirror_dir(str(mirror))  # no existe: no se crea
        self.assertFalse(mirror.exists())
        backups.BACKUPS_DIR.mkdir(parents=True)
        with self.assertRaises(ValueError):
            backups.validate_mirror_dir(str(backups.BACKUPS_DIR / "dentro"))
        (backups.BACKUPS_DIR / "dentro").mkdir()
        with self.assertRaises(ValueError):
            backups.validate_mirror_dir(str(backups.BACKUPS_DIR / "dentro"))
        mirror.mkdir()
        self.assertEqual(backups.validate_mirror_dir(str(mirror)), str(mirror))
        self.assertEqual(list(mirror.iterdir()), [])  # la prueba de escritura no deja rastro
        self.assertEqual(backups.validate_mirror_dir("  "), "")

    def test_mirror_copies_lists_and_survives_local_loss(self):
        old = backups.create_backup("pack")["name"]  # de antes de configurar el destino
        mirror = self.tmp / "nas"
        mirror.mkdir()
        automation.set_mirror_dir(str(mirror))
        self.assertEqual(backups.sync_mirror(), 1)
        self.assertTrue((mirror / "pack" / old).is_file())
        time.sleep(1.1)
        new = backups.create_backup("pack", full=True)["name"]
        self.assertTrue((mirror / "pack" / new).is_file())
        self.assertFalse(any(mirror.rglob("*.part")))
        self.assertTrue(all(item["local"] and item["mirrored"] for item in backups.list_backups("pack")))
        # El disco principal pierde una copia: sigue en la lista y se descarga del destino.
        (backups.backup_dir("pack") / old).unlink()
        item = next(i for i in backups.list_backups("pack") if i["name"] == old)
        self.assertEqual((item["local"], item["mirrored"]), (False, True))
        self.assertEqual(backups.backup_file("pack", old), mirror / "pack" / old)
        # Borrarla la quita también del destino.
        backups.delete_backup("pack", new)
        self.assertFalse((mirror / "pack" / new).exists())
        status = backups.mirror_status()
        self.assertTrue(status["configured"] and status["available"])
        self.assertIsNone(status["last_error"])

    def test_prune_also_cleans_the_mirror(self):
        mirror = self.tmp / "nas"
        mirror.mkdir()
        automation.set_mirror_dir(str(mirror))
        names = []
        for _ in range(3):
            names.append(backups.create_backup("pack", "auto", keep=2)["name"])
            time.sleep(1.1)
        self.assertEqual(sorted(p.name for p in (mirror / "pack").iterdir()), sorted(names[1:]))
        self.assertEqual(sorted(i["name"] for i in backups.list_backups("pack")), sorted(names[1:]))

    def test_unmounted_mirror_is_reported_not_created(self):
        mirror = self.tmp / "nas"
        mirror.mkdir()
        automation.set_mirror_dir(str(mirror))
        mirror.rmdir()  # el disco se desmonta
        with mock.patch("services.notify.notify") as notify:
            backups.create_backup("pack")
        self.assertFalse(mirror.exists())
        status = backups.mirror_status()
        self.assertFalse(status["available"])
        self.assertIn("no está disponible", status["last_error"])
        notify.assert_called_once()

    def test_non_admin_settings_cannot_change_mirror(self):
        automation.set_mirror_dir("/mnt/nas")
        saved = automation.save_settings(backups={"mirror_dir": "/etc", "full": True})
        self.assertEqual(saved["backups"]["mirror_dir"], "/mnt/nas")
        self.assertTrue(saved["backups"]["full"])


if __name__ == "__main__":
    unittest.main()
