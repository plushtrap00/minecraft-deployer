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

    # La plantilla que deja el instalador de NeoForge (copiada tal cual de un
    # servidor real, ATM10 To the Sky): todo comentado y sin salto final.
    NEOFORGE_TEMPLATE = (
        "# Xmx and Xms set the maximum and minimum RAM usage, respectively.\n"
        "# They can take any number, followed by an M or a G.\n"
        "# M means Megabyte, G means Gigabyte.\n"
        "# For example, to set the maximum to 3GB: -Xmx3G\n"
        "# To set the minimum to 2.5GB: -Xms2500M\n"
        "\n"
        "# A good default for a modded server is 4GB.\n"
        "# Uncomment the next line to set it.\n"
        "# -Xmx4G"
    )

    def test_template_without_ram_is_detected_as_unset(self):
        (self.dir / "user_jvm_args.txt").write_text(self.NEOFORGE_TEMPLATE, encoding="utf-8")
        info = detect_jvm_ram(self.dir)
        self.assertEqual(info["source"], "user_jvm_args.txt")
        self.assertTrue(info["unset"])
        self.assertIsNone(info["ram_max"])

    def test_template_without_ram_gets_ram_added(self):
        f = self.dir / "user_jvm_args.txt"
        f.write_text(self.NEOFORGE_TEMPLATE, encoding="utf-8")
        self.assertEqual(configure_jvm_ram(self.dir, "4G", "8G"), "user_jvm_args.txt")
        text = f.read_text(encoding="utf-8")
        self.assertIn("# Uncomment the next line to set it.", text)
        active = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(sorted(active), ["-Xms4G", "-Xmx8G"])
        self.assertTrue(text.endswith("\n"))
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["ram_min"], info["ram_max"], info["unset"]), ("4G", "8G", False))

    def test_saves_where_it_was_detected(self):
        # RAM en variables.txt y un user_jvm_args.txt sin RAM: se ve y se
        # guarda en variables.txt, no en el otro.
        (self.dir / "user_jvm_args.txt").write_text(self.NEOFORGE_TEMPLATE, encoding="utf-8")
        (self.dir / "variables.txt").write_text('JAVA_ARGS="-Xms2G -Xmx4G"\n', encoding="utf-8")
        self.assertEqual(detect_jvm_ram(self.dir)["source"], "variables.txt")
        self.assertEqual(configure_jvm_ram(self.dir, "3G", "6G"), "variables.txt")
        self.assertIn("-Xmx6G", (self.dir / "variables.txt").read_text(encoding="utf-8"))
        self.assertEqual((self.dir / "user_jvm_args.txt").read_text(encoding="utf-8"), self.NEOFORGE_TEMPLATE)

    def test_nothing_to_configure(self):
        self.assertIsNone(configure_jvm_ram(self.dir, "2G", "4G"))
        self.assertIsNone(detect_jvm_ram(self.dir)["source"])


if __name__ == "__main__":
    unittest.main()
