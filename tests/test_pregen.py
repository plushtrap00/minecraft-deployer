"""
Pregenerar con Chunky (services/pregen.py): versión según el servidor,
instalar solo lo pedido (con hash), estimación con los datos del propio
mundo, comandos a Chunky, lectura de su progreso y pausa con jugadores.
"""
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import pregen
from services import process as proc_module
from services import server_control
from services.metrics import mc_metrics


def mca(chunks: int, sectors: int, status: str) -> bytes:
    """
    Archivo de región con «chunks» chunks que dicen ocupar «sectors» sectores y
    tienen ese Status. Todos apuntan a los mismos datos (sector 2) para no
    escribir megas en la prueba.
    """
    import zlib
    header = b"".join(struct.pack(">I", 2 << 8 | sectors) for _ in range(chunks)) + b"\0" * 4 * (1024 - chunks)
    nbt = b"\x0a\x00\x00\x08\x00\x06Status" + struct.pack(">H", len(status)) + status.encode() + b"\x00"
    payload = zlib.compress(nbt)
    chunk = struct.pack(">I", len(payload) + 1) + b"\x02" + payload
    return header + b"\0" * 4096 + chunk + b"\0" * (4096 - len(chunk))


def nbt_level(spawn_x: int, spawn_z: int, modern: bool = False) -> bytes:
    """level.dat mínimo (gzip): Data con SpawnX/SpawnZ o, en versiones recientes, spawn.pos."""
    import gzip

    def name(text):
        return struct.pack(">H", len(text)) + text.encode()

    if modern:
        spawn = (b"\x0a" + name("spawn") + b"\x08" + name("dimension") + name("minecraft:overworld")
                 + b"\x0b" + name("pos") + struct.pack(">i3i", 3, spawn_x, 70, spawn_z) + b"\x00")
    else:
        spawn = b"\x03" + name("SpawnX") + struct.pack(">i", spawn_x) + b"\x03" + name("SpawnZ") + struct.pack(">i", spawn_z)
    data = (b"\x0a" + name("Data") + b"\x08" + name("LevelName") + name("mundo")
            + b"\x09" + name("ScheduledEvents") + b"\x0a" + struct.pack(">i", 0) + spawn + b"\x00")
    return gzip.compress(b"\x0a" + name("") + data + b"\x00")


class PregenTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.server = self.root / "pack"
        (self.server / "mods").mkdir(parents=True)
        (self.server / "server.properties").write_text("level-name=mundo\n", encoding="utf-8")
        self.sent = []
        self.running = None
        for patcher in (
            mock.patch.object(pregen, "DEFAULT_SERVERS_PATH", self.root),
            mock.patch.object(pregen, "_server_versions", return_value=("1.21.1", "neoforge")),
            mock.patch.object(server_control, "send_command", side_effect=self.sent.append),
            mock.patch.object(server_control, "running_modpack", side_effect=lambda: self.running),
            mock.patch.object(proc_module, "mc_ready", True),
            mock.patch.dict(mc_metrics, {"players_online": []}),
            mock.patch("services.notify.notify"),
            mock.patch("services.activity.record"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        pregen._last_save = 0.0
        pregen._live.clear()

    # ── Chunky ────────────────────────────────────────────────────────────────
    def versions(self, url):
        self.assertIn("neoforge", url)
        jar = b"chunky jar"
        return [
            {"version_number": "1.5-beta", "version_type": "beta", "date_published": "2026-10-01",
             "files": [{"primary": True, "filename": "Chunky-beta.jar", "url": "https://cdn.modrinth.com/b.jar"}]},
            {"version_number": "1.4.23", "version_type": "release", "date_published": "2026-01-01",
             "files": [{"primary": True, "filename": "Chunky-NeoForge-1.4.23.jar", "url": "https://cdn.modrinth.com/c.jar",
                        "hashes": {"sha512": hashlib.sha512(jar).hexdigest()}}]},
        ]

    def test_available_prefers_release(self):
        with mock.patch("services.mod_updates._get_list", side_effect=self.versions):
            found = pregen.available_version("pack")
        self.assertTrue(found["ok"])
        self.assertEqual(found["version"], "1.4.23")

    def test_vanilla_is_not_offered(self):
        with mock.patch.object(pregen, "_server_versions", return_value=("1.21.1", None)):
            self.assertFalse(pregen.available_version("pack")["ok"])

    def test_install_checks_hash_and_marks_it_as_panel_mod(self):
        with mock.patch("services.mod_updates._get_list", side_effect=self.versions), \
                mock.patch("services.mod_search.download_bytes", return_value=b"otra cosa"):
            with self.assertRaises(pregen.PregenError):
                pregen.install("pack")
        self.assertIsNone(pregen.find_chunky(self.server))
        with mock.patch("services.mod_updates._get_list", side_effect=self.versions), \
                mock.patch("services.mod_search.download_bytes", return_value=b"chunky jar"):
            pregen.install("pack")
        self.assertEqual(pregen.find_chunky(self.server), "Chunky-NeoForge-1.4.23.jar")
        self.assertEqual(pregen.panel_mods(self.server), {"chunky": "Chunky-NeoForge-1.4.23.jar"})
        pregen.uninstall("pack")
        self.assertIsNone(pregen.find_chunky(self.server))
        self.assertFalse((self.server / pregen.PANEL_MODS_FILE).exists())

    def test_required_dependency_is_installed_with_it(self):
        # Chunky para Fabric necesita Fabric API: si el servidor no la tiene, va con él.
        api = b"fabric api jar"
        chunky = b"chunky jar"

        def get_list(url):
            if "/project/chunky/" in url:
                return [{"version_number": "1.4.23", "version_type": "release", "dependencies": [
                            {"project_id": "P7dR8mSH", "dependency_type": "required"},
                            {"project_id": "OPCIONAL", "dependency_type": "optional"}],
                         "files": [{"primary": True, "filename": "Chunky-Fabric.jar", "url": "https://cdn.modrinth.com/c.jar",
                                    "hashes": {"sha512": hashlib.sha512(chunky).hexdigest()}}]}]
            if "/project/P7dR8mSH/" in url:
                return [{"version_number": "0.116", "version_type": "release",
                         "files": [{"primary": True, "filename": "fabric-api.jar", "url": "https://cdn.modrinth.com/f.jar",
                                    "hashes": {"sha512": hashlib.sha512(api).hexdigest()}}]}]
            self.assertIn("/projects?ids=", url)
            return [{"id": "P7dR8mSH", "title": "Fabric API"}]

        downloads = {"https://cdn.modrinth.com/c.jar": chunky, "https://cdn.modrinth.com/f.jar": api}
        with mock.patch.object(pregen, "_server_versions", return_value=("1.21.1", "fabric")), \
                mock.patch("services.mod_updates._get_list", side_effect=get_list), \
                mock.patch.object(pregen, "_installed_projects", return_value=set()), \
                mock.patch("services.mod_search.download_bytes", side_effect=downloads.get):
            found = pregen.available_version("pack")
            self.assertEqual([d["title"] for d in found["dependencies"]], ["Fabric API"])
            result = pregen.install("pack")
        self.assertEqual(result["dependencies"], ["fabric-api.jar"])
        self.assertTrue((self.server / "mods" / "fabric-api.jar").is_file())
        # Solo Chunky es «del panel»: Fabric API se queda si luego se quita Chunky.
        self.assertEqual(pregen.panel_mods(self.server), {"chunky": "Chunky-Fabric.jar"})
        # Si ya la tiene, no se vuelve a pedir.
        with mock.patch.object(pregen, "_server_versions", return_value=("1.21.1", "fabric")), \
                mock.patch("services.mod_updates._get_list", side_effect=get_list), \
                mock.patch.object(pregen, "_installed_projects", return_value={"P7dR8mSH"}):
            self.assertEqual(pregen.available_version("pack")["dependencies"], [])

    def test_a_chunky_the_panel_did_not_install_is_left_alone(self):
        (self.server / "mods" / "chunky-fabric-1.0.jar").write_bytes(b"x")
        (self.server / "mods" / "ChunkyBorder-1.0.jar").write_bytes(b"x")
        self.assertEqual(pregen.find_chunky(self.server), "chunky-fabric-1.0.jar")
        with self.assertRaises(pregen.PregenError):
            pregen.uninstall("pack")

    # ── Estimación ────────────────────────────────────────────────────────────
    def test_estimate_uses_this_world(self):
        region = self.server / "mundo" / "region"
        region.mkdir(parents=True)
        # Región 0,0 (chunks 0..31): completos de 5 sectores. Región -1,0 (chunks
        # -32..-1): borde a medio hacer, pequeño, que no cuenta como hecho.
        (region / "r.0.0.mca").write_bytes(mca(1000, 5, "minecraft:full"))
        (region / "r.-1.0.mca").write_bytes(mca(1024, 1, "minecraft:noise"))
        est = pregen.estimate("pack", 300, ["minecraft:overworld"])
        # Radio 300 alrededor de 0,0: chunks -19..19. Dentro: 20·20 = 400 completos de
        # r.0.0 y 19·20 = 380 a medias de r.-1.0. Se mira una muestra: ±.
        self.assertEqual(est["chunks"], pregen.chunks_in_radius(300))
        self.assertAlmostEqual(est["existing"], 400, delta=60)
        self.assertFalse(est["approx"])
        self.assertEqual(est["bytes_per_chunk"], 5 * 4096)
        self.assertEqual(est["new_chunks"], est["chunks"] - est["existing"])
        self.assertEqual(est["bytes"], int(est["new_chunks"] * 5 * 4096 * 1.1))
        # Mundo recién creado: estimación aproximada.
        self.assertTrue(pregen.estimate("pack", 1000, ["minecraft:the_nether"])["approx"])

    def test_spawn_from_level_dat(self):
        (self.server / "mundo").mkdir()
        self.assertEqual(pregen.centers(self.server)["minecraft:overworld"], (0, 0))
        for modern in (False, True):
            (self.server / "mundo" / "level.dat").write_bytes(nbt_level(160, -320, modern))
            c = pregen.centers(self.server)
            self.assertEqual(c["minecraft:overworld"], (160, -320), modern)
            self.assertEqual(c["minecraft:the_nether"], (20, -40))
            self.assertEqual(c["minecraft:the_end"], (0, 0))

    def test_no_start_without_disk(self):
        (self.server / "mods" / "Chunky-1.jar").write_bytes(b"x")
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=1024)):
            with self.assertRaises(pregen.PregenError):
                pregen.start("pack", 2000, ["minecraft:overworld"], True, "ana")

    # ── La tarea ──────────────────────────────────────────────────────────────
    def start(self, dims, only_empty=True):
        (self.server / "mods" / "Chunky-1.jar").write_bytes(b"x")
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10 ** 13)):
            return pregen.start("pack", 1500, dims, only_empty, "ana")

    def test_waits_for_the_server_then_runs_each_dimension(self):
        state = self.start(["minecraft:the_nether", "minecraft:overworld"])
        self.assertEqual(state["status"], "waiting")
        self.assertEqual(state["dimensions"], ["minecraft:overworld", "minecraft:the_nether"])
        self.assertEqual(self.sent, [])
        self.running = "pack"
        pregen._kick("pack")
        self.assertEqual(self.sent, [f"chunky quiet {pregen.QUIET_SECONDS}", "chunky world minecraft:overworld",
                                     "chunky center 0 0", "chunky radius 1500", "chunky start"])
        line = ("[12:00:00] [Server thread/INFO] [Chunky/]: [Chunky] Task running for minecraft:overworld. "
                "Processed: 5000 chunks (14.25%), ETA: 1:02:03, Rate: 87.5 cps, Current: 10, -3")
        pregen.on_line("pack", line)
        progress = pregen.load_state("pack")["progress"]
        self.assertEqual((progress["chunks"], progress["percent"], progress["eta_seconds"], progress["rate"]),
                         (5000, 14.25, 3723, 87.5))
        self.sent.clear()
        pregen.on_line("pack", "[Chunky] Task finished for minecraft:overworld. Processed: 35000 chunks (100.00%), Total time: 0:40:00")
        self.assertIn("chunky world minecraft:the_nether", self.sent)
        pregen.on_line("pack", "[Chunky] Task finished for minecraft:the_nether. Processed: 35000 chunks (100.00%), Total time: 0:40:00")
        state = pregen.load_state("pack")
        self.assertEqual(state["status"], "done")
        self.assertEqual([d["dimension"] for d in state["done"]], ["minecraft:overworld", "minecraft:the_nether"])

    def test_pauses_with_players_and_resumes_when_empty_or_after_restart(self):
        self.start(["minecraft:overworld"])
        self.running = "pack"
        pregen._kick("pack")
        self.sent.clear()
        mc_metrics["players_online"] = ["Steve"]
        pregen.on_players_changed("pack")
        self.assertEqual(self.sent, ["chunky pause"])
        self.assertEqual(pregen.load_state("pack")["status"], "paused_players")
        mc_metrics["players_online"] = []
        pregen.on_players_changed("pack")
        self.assertIn("chunky continue", self.sent)
        self.assertEqual(pregen.load_state("pack")["status"], "running")
        # Se apaga el servidor: espera y, al volver, sigue la misma tarea.
        pregen.on_exit("pack")
        self.assertEqual(pregen.load_state("pack")["status"], "waiting")
        self.sent.clear()
        pregen._kick("pack")
        self.assertEqual(self.sent, [f"chunky quiet {pregen.QUIET_SECONDS}", "chunky continue"])

    def test_with_players_it_does_not_start(self):
        self.start(["minecraft:overworld"])
        self.running = "pack"
        mc_metrics["players_online"] = ["Steve"]
        pregen._kick("pack")
        self.assertEqual(self.sent, [])
        self.assertEqual(pregen.load_state("pack")["status"], "paused_players")

    def test_chat_cannot_fake_progress(self):
        self.start(["minecraft:overworld"])
        self.running = "pack"
        pregen._kick("pack")
        pregen.on_line("pack", "[12:00] [Server thread/INFO]: <Steve> Task finished for minecraft:overworld. Processed: 1 chunks")
        self.assertEqual(pregen.load_state("pack")["status"], "running")

    def test_cancel(self):
        self.start(["minecraft:overworld"])
        self.running = "pack"
        pregen._kick("pack")
        pregen.cancel("pack")
        self.assertEqual(self.sent[-2:], ["chunky cancel", "chunky confirm"])
        self.assertEqual(pregen.load_state("pack")["status"], "cancelled")
        with self.assertRaises(pregen.PregenError):
            pregen.cancel("pack")


class PanelModsKeptOnUpdateTests(unittest.TestCase):
    def test_merge_keeps_panel_mods_even_without_pack_list(self):
        from services import modpack_update
        with tempfile.TemporaryDirectory() as tmp:
            server, staging = Path(tmp) / "server", Path(tmp) / "staging"
            (server / "mods").mkdir(parents=True)
            (staging / "mods").mkdir(parents=True)
            (server / "mods" / "Chunky-1.jar").write_bytes(b"x")
            (server / "mods" / "viejo.jar").write_bytes(b"x")
            (server / pregen.PANEL_MODS_FILE).write_text(json.dumps({"chunky": "Chunky-1.jar"}), encoding="utf-8")
            result = modpack_update.merge_into(staging, server, None)
        self.assertIn("Chunky-1.jar", result["kept"])
        self.assertIn("viejo.jar", result["removed"])


if __name__ == "__main__":
    unittest.main()
