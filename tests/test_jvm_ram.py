"""Detectar y cambiar la RAM de la JVM en los tres formatos que usan los modpacks."""
import shutil
import tempfile
import unittest
from pathlib import Path

from services.utils import configure_jvm_ram, detect_jvm_ram


class JvmRamTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_user_jvm_args_keeps_other_flags(self):
        f = self.dir / "user_jvm_args.txt"
        f.write_text("# comentario -Xmx1G\n-Xmx12G -Xms4G -XX:+UseG1GC\n", encoding="utf-8")
        self.assertEqual(configure_jvm_ram(self.dir, "6G", "10G"), "user_jvm_args.txt")
        text = f.read_text(encoding="utf-8")
        self.assertIn("-Xmx10G -Xms6G -XX:+UseG1GC", text)
        self.assertIn("# comentario -Xmx1G", text)
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["ram_min"], info["ram_max"]), ("6G", "10G"))

    def test_variables_txt(self):
        (self.dir / "variables.txt").write_text('JAVA_ARGS="-Xms2G -Xmx4G"\n', encoding="utf-8")
        self.assertEqual(configure_jvm_ram(self.dir, "3G", "8G"), "variables.txt")
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["ram_min"], info["ram_max"]), ("3G", "8G"))

    def test_run_script(self):
        (self.dir / "run.sh").write_text("#!/bin/bash\njava -Xms1G -Xmx2G -jar server.jar nogui\n", encoding="utf-8")
        self.assertEqual(configure_jvm_ram(self.dir, "2G", "6G"), "run.sh")
        self.assertIn("-Xms2G -Xmx6G", (self.dir / "run.sh").read_text(encoding="utf-8"))

    def test_nothing_to_configure(self):
        self.assertIsNone(configure_jvm_ram(self.dir, "2G", "4G"))
        self.assertIsNone(detect_jvm_ram(self.dir)["source"])


if __name__ == "__main__":
    unittest.main()
