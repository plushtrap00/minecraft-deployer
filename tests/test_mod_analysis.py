"""
Lectura de mods y de lo que pasa en el servidor, sin red:
metadatos de los .jar (services/mod_metadata.py), lado cliente/servidor y
duplicados (services/mod_checks.py), análisis de crash reports
(services/crash_analysis.py) y lectura de la consola (services/metrics.py).
"""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from services import crash_analysis, metrics
from services.mod_checks import _dedup_fingerprint, classify_mod_side, find_possible_duplicate_mods
from services.mod_metadata import compare_mod_versions, mc_version_compatible, mod_display_name, read_mod_metadata


def jar(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def fabric_jar(mod_id, version="1.0.0", environment=None, mc=">=1.21"):
    data = {"id": mod_id, "version": version, "depends": {"minecraft": mc, "fabricloader": ">=0.16"}}
    if environment:
        data["environment"] = environment
    return jar({"fabric.mod.json": json.dumps(data)})


NEOFORGE_TOML = '''
modLoader="javafml"
loaderVersion="[4,)"

[[mods]]
modId="examplemod"
version="${file.jarVersion}"
displayName="Example"

[[dependencies.examplemod]]
modId="neoforge"
type="required"
versionRange="[21.1.0,)"
side="CLIENT"

[[dependencies.examplemod]]
modId="minecraft"
type="required"
versionRange="[1.21.1,1.22)"
side="BOTH"
'''


class ModMetadataTests(unittest.TestCase):
    def test_fabric(self):
        meta = read_mod_metadata(fabric_jar("lithium", "0.13.1", environment="*", mc="~1.21.1"))
        self.assertEqual((meta["modloader"], meta["mod_id"], meta["mod_version"], meta["side"]),
                         ("Fabric", "lithium", "0.13.1", "*"))
        self.assertEqual(meta["mc_versions"], ["~1.21.1"])
        self.assertEqual(meta["loader_versions"], {"fabric": [">=0.16"]})
        self.assertIsNone(meta["error"])

    def test_neoforge_with_version_from_manifest(self):
        meta = read_mod_metadata(jar({
            "META-INF/neoforge.mods.toml": NEOFORGE_TOML,
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 2.4.1\n",
        }))
        self.assertEqual((meta["modloader"], meta["mod_id"], meta["mod_version"]), ("NeoForge", "examplemod", "2.4.1"))
        self.assertEqual(meta["mc_versions"], ["[1.21.1,1.22)"])
        self.assertEqual(meta["loader_versions"], {"neoforge": ["[21.1.0,)"]})
        self.assertEqual(meta["side"], "CLIENT")

    def test_quilt(self):
        data = {"quilt_loader": {"id": "qmod", "version": "3.0", "depends": [
            {"id": "minecraft", "versions": ">=1.20"}, {"id": "quilt_loader", "versions": "*"}, "texto suelto"]}}
        meta = read_mod_metadata(jar({"quilt.mod.json": json.dumps(data)}))
        self.assertEqual((meta["modloader"], meta["mod_id"], meta["mc_versions"]), ("Quilt", "qmod", [">=1.20"]))

    def test_no_metadata_or_not_a_zip(self):
        self.assertIn("No se encontró metadata", read_mod_metadata(jar({"readme.txt": "hola"}))["error"])
        self.assertTrue(read_mod_metadata(b"esto no es un jar")["error"])


class ModSideTests(unittest.TestCase):
    def test_classification(self):
        cases = [
            ({"mod_id": "sodium", "modloader": "Fabric"}, "client_only", "high"),
            ({"mod_id": "x", "modloader": "Fabric", "side": "client"}, "client_only", "high"),
            ({"mod_id": "x", "modloader": "Fabric", "side": "*"}, "server", None),
            ({"mod_id": "x", "modloader": "Fabric", "side": "raro"}, "unknown", None),
            ({"mod_id": "x", "modloader": "NeoForge", "side": "CLIENT"}, "client_only", "medium"),
            ({"mod_id": "x", "modloader": "NeoForge/Forge", "side": "both"}, "server", None),
            ({"mod_id": "x", "modloader": "NeoForge"}, "server", None),
            ({"mod_id": "x", "modloader": "Quilt", "side": "client"}, "server", None),
        ]
        for meta, category, confidence in cases:
            result = classify_mod_side(meta)
            self.assertEqual((result["category"], result["confidence"]), (category, confidence), meta)


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(compare_mod_versions("1.2.10", "1.2.9"), 1)
        self.assertEqual(compare_mod_versions("6.0.0-beta.83", "6.0.0"), -1)   # la estable es más nueva
        self.assertEqual(compare_mod_versions("6.0.0", "6.0.0-beta.83"), 1)
        self.assertEqual(compare_mod_versions("6.0.0-beta.83", "6.0.0-beta.90"), -1)
        self.assertEqual(compare_mod_versions("1.0", "1.0.0"), 0)
        self.assertEqual(compare_mod_versions("mc1.21.1-2.0", "mc1.21.1-1.9"), 1)

    def test_minecraft_compatibility(self):
        self.assertTrue(mc_version_compatible("1.21.1", ["1.21.1"]))
        self.assertTrue(mc_version_compatible("1.21.1", ["1.21.x"]))
        self.assertTrue(mc_version_compatible("1.21.1", ["1.21"]))                 # prefijo
        self.assertTrue(mc_version_compatible("1.21.1", ["[1.21,1.22)"]))
        self.assertTrue(mc_version_compatible("1.21.1", ["[1.21,1.21.1)"]))        # límite alto laxo
        self.assertTrue(mc_version_compatible("1.21.1", ["[1.21]"]))
        self.assertTrue(mc_version_compatible("1.21.1", ["${minecraft_version_range}"]))  # sin resolver: no bloquea
        self.assertTrue(mc_version_compatible("1.21.1", []))
        self.assertFalse(mc_version_compatible("1.20.1", ["[1.21,)"]))
        self.assertFalse(mc_version_compatible("1.20.1", ["1.21.x", "[1.21]"]))
        self.assertFalse(mc_version_compatible("1.21.1", ["(1.21.1,1.22)"]))       # límite bajo exclusivo

    def test_loader_versions_as_minimum(self):
        self.assertTrue(mc_version_compatible("21.1.228", ["21.1.200"], bare_as_minimum=True))
        self.assertFalse(mc_version_compatible("21.1.100", ["21.1.200"], bare_as_minimum=True))
        self.assertFalse(mc_version_compatible("21.1.228", ["21.1.200"]))           # como prefijo no calza


class ModNamesAndDuplicatesTests(unittest.TestCase):
    def test_display_name_and_fingerprint(self):
        self.assertEqual(mod_display_name("sodium-fabric-0.6.0+mc1.21.1.jar"), "sodium")
        self.assertEqual(mod_display_name("Better_Than_Mending-2.2.0.jar.disabled"), "Better Than Mending")
        self.assertEqual(_dedup_fingerprint("custom_nether_portals-neoforge-1.21.1-1.0.0.jar"),
                         _dedup_fingerprint("Custom Nether Portals - Neoforge - MC 1.21.1- 2.0.0.jar"))
        self.assertEqual(_dedup_fingerprint("sodium-neoforge-0.8.12+mc1.21.1.jar"), "sodium")

    def test_possible_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp)
            (mods / "lithium-0.12.jar").write_bytes(fabric_jar("lithium", "0.12"))
            (mods / "lithium-fabric-0.13.jar.disabled").write_bytes(fabric_jar("lithium", "0.13"))
            (mods / "custom_nether_portals-1.0.0.jar").write_bytes(fabric_jar("custom_nether_portals"))
            (mods / "Custom-Nether-Portals-2.0.0.jar").write_bytes(fabric_jar("customnetherportals"))
            (mods / "solo-1.0.jar").write_bytes(fabric_jar("solo"))
            (mods / "notas.txt").write_text("no es un mod")
            groups = find_possible_duplicate_mods(mods)
        self.assertEqual([g["confidence"] for g in groups], ["high", "medium"])
        self.assertEqual(sorted(m["filename"] for m in groups[0]["mods"]),
                         ["lithium-0.12.jar", "lithium-fabric-0.13.jar.disabled"])
        self.assertEqual(len(groups[1]["mods"]), 2)
        self.assertEqual(find_possible_duplicate_mods(Path(tmp) / "no-existe"), [])


CRASH = """---- Minecraft Crash Report ----
// Who set us up the TNT?

Time: 2026-11-23 20:00:00
Description: Ticking entity

java.lang.NullPointerException: Cannot invoke "Object.toString()" because "x" is null
\tat com.example.toms_mobs.entity.Ghost.tick(Ghost.java:42)
\tat net.minecraft.world.entity.Entity.tick(Entity.java:100)
Caused by: java.lang.IllegalStateException: estado roto
\tat me.jellysquid.mods.lithium.common.Thing.run(Thing.java:7)
Caused by: java.lang.IllegalStateException: estado roto

-- Head --
Thread: Server thread

-- System Details --
\tMod List:
\t\tsodium-fabric-0.6.0.jar
\t\tterralith-2.5.jar
"""


class CrashAnalysisTests(unittest.TestCase):
    def test_culprits_come_from_the_stack_trace_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "pack" / "mods"
            mods.mkdir(parents=True)
            for name in ("toms_mobs-2.0.2.jar", "lithium-fabric-0.13.1.jar", "sodium-fabric-0.6.0.jar",
                         "terralith-2.5.jar", "ae-1.0.jar"):
                (mods / name).write_bytes(b"")
            with mock.patch.object(crash_analysis, "DEFAULT_SERVERS_PATH", Path(tmp)):
                result = crash_analysis.analyze_crash(CRASH, "pack")
        self.assertTrue(result["exception_summary"].startswith("java.lang.NullPointerException"))
        self.assertEqual(result["caused_by_chain"], ["Caused by: java.lang.IllegalStateException: estado roto"])
        # tomsmobs sale antes que lithium (aparece antes en la traza); sodium y
        # terralith solo están en la lista de mods, así que no cuentan.
        self.assertEqual(result["culprit_mods"], ["toms_mobs-2.0.2.jar", "lithium-fabric-0.13.1.jar"])

    def test_text_without_markers(self):
        result = crash_analysis.analyze_crash("Algo raro pasó\njava.lang.OutOfMemoryError: Java heap space\n", "no-existe")
        self.assertEqual(result["exception_summary"], "java.lang.OutOfMemoryError: Java heap space")
        self.assertEqual(result["culprit_mods"], [])


class ConsoleParsingTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(metrics.mc_metrics, {"players_online": [], "players_max": 20, "tps": None,
                                                        "mspt": None, "ram_used_mb": None, "ram_max_mb": None})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.m = metrics.mc_metrics

    def feed(self, *lines):
        for line in lines:
            metrics._parse_metrics_line(line)

    def test_players_join_and_leave(self):
        self.feed("[20:00:01] [Server thread/INFO]: Steve joined the game",
                  "[20:00:02] [Server thread/INFO]: Alex joined the game",
                  "[20:00:03] [Server thread/INFO]: Steve joined the game",
                  "[20:05:00] [Server thread/INFO]: Steve left the game",
                  "[20:06:00] [Server thread/INFO]: There are 1 of a max of 10 players online: Alex")
        self.assertEqual(self.m["players_online"], ["Alex"])
        self.assertEqual(self.m["players_max"], 10)

    def test_tps_formats(self):
        cases = [
            ("Overall: 20,000 TPS (1,459 ms/tick)", 20.0, 1.459),           # /neoforge tps, coma decimal
            ("Overall: 19.50 TPS, 51.20 MSPT", 19.5, 51.2),
            ("TPS: 18.2, MSPT: 54.9", 18.2, 54.9),                            # Fabric/Carpet
        ]
        for line, tps, mspt in cases:
            self.m["tps"] = self.m["mspt"] = None
            self.feed(line)
            self.assertEqual((self.m["tps"], self.m["mspt"]), (tps, mspt), line)
        self.m["tps"] = None
        self.feed("The server is running at 17.5/20 ticks per second")
        self.assertEqual(self.m["tps"], 17.5)

    def test_jvm_memory(self):
        self.feed("Used Memory: 2048 MB / 6144 MB")
        self.assertEqual((self.m["ram_used_mb"], self.m["ram_max_mb"]), (2048, 6144))


if __name__ == "__main__":
    unittest.main()
