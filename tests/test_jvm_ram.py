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

    def _server_pack_creator(self, java_args):
        # Lo esencial de un start.sh de ServerPackCreator: rehace
        # user_jvm_args.txt desde JAVA_ARGS en cada arranque.
        (self.dir / "start.sh").write_text(
            '#!/usr/bin/env bash\n'
            'rm -f user_jvm_args.txt\n'
            '{\n  echo "${JAVA_ARGS}"\n} >>user_jvm_args.txt\n',
            encoding="utf-8",
        )
        (self.dir / "variables.txt").write_text(
            'MINECRAFT_VERSION=1.21.1\nJAVA="java"\nJAVA_ARGS="' + java_args + '"\nRESTART=false\n',
            encoding="utf-8",
        )

    def test_server_pack_creator_uses_variables_even_after_a_start(self):
        # Tras arrancar, user_jvm_args.txt ya trae -Xmx, pero se rehace en cada
        # arranque: guardar ahí la RAM no serviría de nada.
        self._server_pack_creator("-Xms2G -Xmx4G -XX:+UseG1GC")
        (self.dir / "user_jvm_args.txt").write_text("-Xms2G -Xmx4G -XX:+UseG1GC\n", encoding="utf-8")
        self.assertEqual(configure_jvm_ram(self.dir, "6G", "10G"), "variables.txt")
        text = (self.dir / "variables.txt").read_text(encoding="utf-8")
        self.assertIn('JAVA_ARGS="-Xms6G -Xmx10G -XX:+UseG1GC"', text)
        self.assertIn('JAVA="java"', text)
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["source"], info["ram_min"], info["ram_max"]), ("variables.txt", "6G", "10G"))

    def test_server_pack_creator_with_empty_java_args(self):
        self._server_pack_creator("")
        # Plantilla del instalador de NeoForge, como queda antes del primer arranque.
        (self.dir / "user_jvm_args.txt").write_text("# -Xmx4G\n", encoding="utf-8")
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["source"], info["unset"]), ("variables.txt", True))
        self.assertEqual(configure_jvm_ram(self.dir, "4G", "8G"), "variables.txt")
        self.assertEqual(detect_jvm_ram(self.dir)["ram_max"], "8G")
        self.assertEqual((self.dir / "user_jvm_args.txt").read_text(encoding="utf-8"), "# -Xmx4G\n")


    def test_script_comments_are_not_ram(self):
        script = self.dir / "start.sh"
        script.write_text(
            '#!/bin/bash\n'
            'echo "# To set the minimum to 2.5GB: -Xms2500M"\n'
            'java -Xms1G -Xmx2G -jar server.jar nogui  # antes -Xmx1G\n',
            encoding="utf-8",
        )
        info = detect_jvm_ram(self.dir)
        self.assertEqual((info["source"], info["ram_min"], info["ram_max"]), ("start.sh", "1G", "2G"))
        configure_jvm_ram(self.dir, "3G", "5G")
        text = script.read_text(encoding="utf-8")
        self.assertIn('echo "# To set the minimum to 2.5GB: -Xms2500M"', text)
        self.assertIn("java -Xms3G -Xmx5G -jar server.jar nogui  # antes -Xmx1G", text)

    def test_script_with_only_example_ram_is_not_detected(self):
        (self.dir / "start.sh").write_text('echo "# For example: -Xmx3G"\n', encoding="utf-8")
        self.assertIsNone(detect_jvm_ram(self.dir)["source"])
        self.assertIsNone(configure_jvm_ram(self.dir, "2G", "4G"))


class BootstrapVariablesTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "pack"
        self.dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.dir.parent, ignore_errors=True)

    def _bootstrap(self):
        from unittest import mock
        from services import server_create
        with mock.patch.object(server_create, "write_player_files"):
            server_create._bootstrap_common_files(self.dir, "1.21.1", "neoforge", "21.1.256")

    def test_keeps_the_modpack_variables_txt(self):
        original = 'MINECRAFT_VERSION=1.21.1\nMODLOADER=NeoForge\nMODLOADER_VERSION=21.1.256\nJAVA="java"\nJAVA_ARGS="-Xmx8G"\n'
        (self.dir / "variables.txt").write_text(original, encoding="utf-8")
        self._bootstrap()
        self.assertEqual((self.dir / "variables.txt").read_text(encoding="utf-8"), original)

    def test_adds_only_what_is_missing(self):
        (self.dir / "variables.txt").write_text('JAVA="java"', encoding="utf-8")
        self._bootstrap()
        text = (self.dir / "variables.txt").read_text(encoding="utf-8")
        self.assertTrue(text.startswith('JAVA="java"\nMINECRAFT_VERSION="1.21.1"\n'))
        self.assertIn('MODLOADER_VERSION="21.1.256"', text)

    def test_creates_it_when_absent(self):
        self._bootstrap()
        text = (self.dir / "variables.txt").read_text(encoding="utf-8")
        self.assertIn('MINECRAFT_VERSION="1.21.1"', text)
        self.assertIn('MODLOADER="NeoForge"', text)


if __name__ == "__main__":
    unittest.main()
