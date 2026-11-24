"""
EULA de Minecraft (services/eula.py): el panel nunca la acepta solo. Un
servidor sin ella no arranca (ni forzando) hasta que una persona la acepta.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import eula, server_control


class EulaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_accepted(self):
        self.assertFalse(eula.accepted(self.dir))
        (self.dir / "eula.txt").write_text("#comentario eula=true\neula=false\n", encoding="utf-8")
        self.assertFalse(eula.accepted(self.dir))
        (self.dir / "eula.txt").write_text("#x\neula=TRUE\n", encoding="utf-8")
        self.assertTrue(eula.accepted(self.dir))

    def test_accept_records_who(self):
        eula.accept(self.dir, "ana")
        text = (self.dir / "eula.txt").read_text(encoding="utf-8")
        self.assertIn("by ana", text)
        self.assertIn(eula.EULA_URL, text)
        self.assertTrue(eula.accepted(self.dir))

    def test_start_refuses_without_eula_even_forced(self):
        (self.dir / "start.sh").write_text("java -jar server.jar\n", encoding="utf-8")
        with mock.patch.object(server_control, "modpack_path", return_value=self.dir), \
                mock.patch.object(server_control.proc_module, "mc_process", None):
            with self.assertRaises(server_control.EulaRequiredError):
                server_control.start_server("pack", force=True)
        self.assertFalse((self.dir / "eula.txt").exists())


if __name__ == "__main__":
    unittest.main()
