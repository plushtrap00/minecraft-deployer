"""
Actualizaciones que se deshacen solas (update_guard.py y auto_update.apply_update).

Con repos de git de verdad en una carpeta temporal: un origin con una versión
nueva y un clon que hace de instalación. Nunca se toca el repo real: todas
las llamadas reciben la carpeta del clon.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import update_guard
from services import auto_update


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def version_file(version: str) -> str:
    return f'"""\nHistorial resumido:\n- {version} (2026-11-23): prueba.\n"""\nAPP_VERSION = "{version}"\n'


@unittest.skipUnless(shutil.which("git"), "hace falta git")
class UpdateRollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = self.tmp / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        git(self.origin, "config", "user.email", "test@example.invalid")
        git(self.origin, "config", "user.name", "test")
        (self.origin / "version.py").write_text(version_file("3.0.4"), encoding="utf-8")
        (self.origin / "main.py").write_text("OK = True\n", encoding="utf-8")
        (self.origin / "requirements.txt").write_text("fastapi==1\n", encoding="utf-8")
        (self.origin / ".gitignore").write_text(".update_state.json\n.update_state.tmp\n", encoding="utf-8")
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-q", "-m", "v3.0.4")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.clone))
        git(self.clone, "config", "user.email", "test@example.invalid")
        git(self.clone, "config", "user.name", "test")
        self.old_head = git(self.clone, "rev-parse", "HEAD")

        saved = dict(auto_update._status)
        self.addCleanup(auto_update._status.update, saved)
        for patcher in (
            mock.patch.object(auto_update, "_REPO_DIR", self.clone),
            mock.patch.object(auto_update, "APP_VERSION", "3.0.4"),
            mock.patch.object(auto_update, "_server_running", return_value=False),
            mock.patch.object(auto_update, "is_busy", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def publish(self, main_source: str, requirements: str = "fastapi==1\n"):
        (self.origin / "version.py").write_text(version_file("3.0.5"), encoding="utf-8")
        (self.origin / "main.py").write_text(main_source, encoding="utf-8")
        (self.origin / "requirements.txt").write_text(requirements, encoding="utf-8")
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-q", "-m", "v3.0.5")
        return git(self.origin, "rev-parse", "HEAD")

    def head(self) -> str:
        return git(self.clone, "rev-parse", "HEAD")

    def test_broken_version_is_undone_before_restarting(self):
        self.publish('raise ImportError("módulo roto")\n')
        with self.assertRaises(RuntimeError) as ctx:
            auto_update.apply_update()
        self.assertIn("no se puede cargar", str(ctx.exception))
        self.assertIn("módulo roto", str(ctx.exception))
        self.assertEqual(self.head(), self.old_head)
        self.assertEqual((self.clone / "main.py").read_text(encoding="utf-8"), "OK = True\n")
        self.assertEqual(update_guard.read_state(self.clone), {})

    def test_good_version_waits_for_confirmation(self):
        target = self.publish("OK = 2\n")
        auto_update.apply_update()
        self.assertEqual(self.head(), target)
        state = update_guard.read_state(self.clone)
        self.assertEqual((state["status"], state["previous"], state["target"]), ("verifying", self.old_head, target))
        self.assertEqual((state["from_version"], state["to_version"]), ("3.0.4", "3.0.5"))
        self.assertEqual(auto_update.get_status()["last_update"]["status"], "verifying")
        # Primer arranque de la nueva: cuenta, pero no hace nada más.
        update_guard.on_boot(self.clone, restart=mock.Mock())
        self.assertTrue(update_guard.confirm_ok(self.clone))
        self.assertEqual(update_guard.read_state(self.clone)["status"], "ok")
        # Ya confirmada: ni cuenta arranques ni puede deshacerse.
        restart = mock.Mock()
        for _ in range(5):
            update_guard.on_boot(self.clone, restart=restart)
        restart.assert_not_called()
        self.assertFalse(update_guard.rollback("x", self.clone))
        self.assertEqual(self.head(), target)

    def test_version_that_keeps_crashing_on_boot_is_undone(self):
        self.publish("OK = 2\n")
        auto_update.apply_update()
        restart = mock.Mock()
        for _ in range(update_guard.MAX_BOOTS):
            update_guard.on_boot(self.clone, restart=restart)
        restart.assert_not_called()
        update_guard.on_boot(self.clone, restart=restart)
        restart.assert_called_once()
        self.assertEqual(self.head(), self.old_head)
        state = update_guard.read_state(self.clone)
        self.assertEqual(state["status"], "rolled_back")
        self.assertIn("3.0.5 no ha conseguido arrancar", state["error"])
        last = auto_update.get_status()["last_update"]
        self.assertEqual((last["status"], last["to_version"]), ("rolled_back", "3.0.5"))

    def test_local_changes_block_the_update(self):
        self.publish("OK = 2\n")
        (self.clone / "main.py").write_text("OK = 'tocado a mano'\n", encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            auto_update.apply_update()
        self.assertIn("modificados a mano (main.py)", str(ctx.exception))
        self.assertEqual(self.head(), self.old_head)

    def test_new_requirements_are_installed(self):
        target = self.publish("OK = 2\n", requirements="fastapi==2\n")
        with mock.patch.object(auto_update, "_install_requirements") as install:
            auto_update.apply_update()
        install.assert_called_once()
        self.assertEqual(self.head(), target)

    def test_failed_requirements_undo_the_update(self):
        self.publish("OK = 2\n", requirements="fastapi==2\n")
        with mock.patch.object(auto_update, "_install_requirements", side_effect=RuntimeError("sin red")) as install:
            with self.assertRaises(RuntimeError) as ctx:
                auto_update.apply_update()
        self.assertIn("librerías nuevas", str(ctx.exception))
        self.assertEqual(self.head(), self.old_head)
        # Al volver atrás, se reinstalan las de la versión anterior.
        self.assertEqual(install.call_count, 2)

    def test_messages_are_translated(self):
        from services import i18n
        text = "La versión nueva no se puede cargar; se ha vuelto a la versión anterior. Error: ImportError: x"
        self.assertTrue(i18n.translate_message(text, "en").startswith("The new version can't be loaded"))
        self.assertEqual(i18n.translate_message("la versión 3.0.5 no ha conseguido arrancar (2 intentos)", "en"),
                         "version 3.0.5 couldn't start (2 attempts)")


if __name__ == "__main__":
    unittest.main()
