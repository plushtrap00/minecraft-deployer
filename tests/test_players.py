"""
UUID de los jugadores en ops.json / whitelist.json / banned-players.json.

Minecraft descarta al arrancar las entradas cuyo "uuid" no es un UUID válido,
así que el panel tiene que guardar siempre uno: el real de la cuenta en
servidores online y el offline en los que tienen online-mode=false.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import players


class OfflineUuidTest(unittest.TestCase):
    def test_matches_java_name_uuid_from_bytes(self):
        # Valor conocido de UUID.nameUUIDFromBytes("OfflinePlayer:Notch").
        self.assertEqual(players.offline_uuid("Notch"), "b50ad385-829d-3141-a216-7e7d7539ba7f")


class PlayerFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        for pack, online in (("online_pack", "true"), ("offline_pack", "false")):
            (root / pack).mkdir()
            (root / pack / "server.properties").write_text(f"motd=x\nonline-mode={online}\n", encoding="utf-8")
        (root / "online_pack" / "usercache.json").write_text(json.dumps([
            {"name": "Plushyyy", "uuid": "0fd22dbf-6e4f-49fd-a555-15cb3a744c43", "expiresOn": "2026-12-06 17:24:53 +0100"},
        ]), encoding="utf-8")
        self.patches = [
            mock.patch.object(players, "DEFAULT_SERVERS_PATH", root),
            mock.patch.object(players, "GLOBAL_DIR", root / ".global"),
            mock.patch("services.utils.DEFAULT_SERVERS_PATH", root),
            mock.patch.object(players, "_global_dir_initialized", False),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_resolve_uses_usercache_without_network(self):
        with mock.patch.object(players, "_uuid_from_mojang", side_effect=AssertionError("no debería llamar a Mojang")):
            found = players.resolve_player("plushyyy")
        self.assertEqual(found, {"uuid": "0fd22dbf-6e4f-49fd-a555-15cb3a744c43", "name": "Plushyyy"})

    def test_unknown_account_falls_back_to_offline_when_a_pack_is_offline(self):
        with mock.patch.object(players, "_uuid_from_mojang", return_value=None):
            found = players.resolve_player("NoExiste")
        self.assertEqual(found["uuid"], players.offline_uuid("NoExiste"))

    def test_unknown_account_is_rejected_when_every_pack_is_online(self):
        (self.root / "offline_pack" / "server.properties").write_text("online-mode=true\n", encoding="utf-8")
        with mock.patch.object(players, "_uuid_from_mojang", return_value=None):
            with self.assertRaises(ValueError):
                players.resolve_player("NoExiste")

    def test_mojang_down_is_reported_when_every_pack_is_online(self):
        (self.root / "offline_pack" / "server.properties").write_text("online-mode=true\n", encoding="utf-8")
        with mock.patch.object(players, "_uuid_from_mojang", side_effect=players.PlayerLookupError("sin red")):
            with self.assertRaises(players.PlayerLookupError):
                players.resolve_player("Alguien")

    def test_fill_missing_uuids_completes_old_entries(self):
        data = [{"uuid": "", "name": "plushyyy", "level": 4}, {"uuid": "", "name": "Desconocido"}]
        with mock.patch.object(players, "_uuid_from_mojang", return_value=None):
            self.assertTrue(players.fill_missing_uuids(data))
        self.assertEqual(data[0]["uuid"], "0fd22dbf-6e4f-49fd-a555-15cb3a744c43")
        self.assertEqual(data[1]["uuid"], "")

    def test_sync_writes_offline_uuids_only_to_offline_packs(self):
        data = [{"uuid": "0fd22dbf-6e4f-49fd-a555-15cb3a744c43", "name": "Plushyyy", "level": 4}]
        with mock.patch("services.process.mc_running_modpack", None):
            synced, skipped = players.sync_to_all_modpacks("ops.json", data)
        self.assertEqual(sorted(synced), ["offline_pack", "online_pack"])
        online = json.loads((self.root / "online_pack" / "ops.json").read_text(encoding="utf-8"))
        offline = json.loads((self.root / "offline_pack" / "ops.json").read_text(encoding="utf-8"))
        self.assertEqual(online[0]["uuid"], "0fd22dbf-6e4f-49fd-a555-15cb3a744c43")
        self.assertEqual(offline[0]["uuid"], players.offline_uuid("Plushyyy"))

    def test_ip_bans_are_copied_unchanged(self):
        data = [{"ip": "10.0.0.5", "reason": "x"}]
        with mock.patch("services.process.mc_running_modpack", None):
            players.sync_to_all_modpacks("banned-ips.json", data)
        offline = json.loads((self.root / "offline_pack" / "banned-ips.json").read_text(encoding="utf-8"))
        self.assertEqual(offline, data)


if __name__ == "__main__":
    unittest.main()
