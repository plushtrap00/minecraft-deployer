"""
Actualizaciones de mods (services/mod_updates.py) con las APIs simuladas.
"""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import mod_updates


def mr_version(vid, project, number, date, vtype="release", data=b"", filename=None):
    return {"id": vid, "project_id": project, "version_number": number, "version_type": vtype,
            "date_published": date,
            "files": [{"primary": True, "url": f"https://cdn.modrinth.com/{vid}.jar",
                       "filename": filename or f"{project}-{number}.jar",
                       "hashes": {"sha1": hashlib.sha1(data).hexdigest()}}]}


class FingerprintTests(unittest.TestCase):
    def test_known_values(self):
        # Contrastados con la implementación en C del paquete «murmurhash2».
        self.assertEqual(mod_updates.curseforge_fingerprint(b""), 1540447798)
        self.assertEqual(mod_updates.curseforge_fingerprint(b"hola mundo\n"),
                         mod_updates.curseforge_fingerprint(b"holamundo"))


class ModUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.server = root / "pack"
        self.mods = self.server / "mods"
        self.mods.mkdir(parents=True)
        (self.mods / "sodium-1.0.jar").write_bytes(b"sodium old")
        (self.mods / "jei-1.0.jar.disabled").write_bytes(b"jei old")
        (self.mods / "hecho-a-mano.jar").write_bytes(b"nadie lo conoce")
        (self.mods / "cfmod-1.jar").write_bytes(b"curseforge old")
        self.new_sodium = b"sodium new"
        self.new_jei = b"jei new"
        self.new_cf = b"curseforge new"
        for patcher in (
            mock.patch.object(mod_updates, "DEFAULT_SERVERS_PATH", root),
            mock.patch.object(mod_updates, "detect_modpack_version",
                              return_value={"mc_version": "1.20.1", "modloader": "Fabric"}),
            mock.patch.object(mod_updates, "CURSEFORGE_API_KEY", "clave"),
            mock.patch.object(mod_updates, "_curseforge_headers", return_value={}),
            mock.patch.dict(mod_updates._jobs, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

    def fake_post(self, url, body, headers=None):
        self.calls.append(url)
        sha = lambda b: hashlib.sha1(b).hexdigest()
        if url.endswith("/version_files"):
            known = {sha(b"sodium old"): mr_version("s1", "AANobbMI", "1.0", "2024-01-01"),
                     sha(b"jei old"): mr_version("j1", "u6dRKJwZ", "1.0", "2024-01-01")}
            return {h: v for h, v in known.items() if h in body["hashes"]}
        if url.endswith("/version_files/update"):
            self.assertEqual(body["loaders"], ["fabric"])
            self.assertEqual(body["game_versions"], ["1.20.1"])
            return {sha(b"sodium old"): mr_version("s2", "AANobbMI", "2.0", "2024-05-01", data=self.new_sodium, filename="sodium-2.0.jar"),
                    # La más nueva de JEI es beta y la instalada no: se busca la última estable.
                    sha(b"jei old"): mr_version("j3", "u6dRKJwZ", "3.0-beta", "2024-06-01", "beta")}
        if "/fingerprints/" in url:
            fp = mod_updates.curseforge_fingerprint(b"curseforge old")
            self.assertIn(fp, body["fingerprints"])
            self.assertNotIn(mod_updates.curseforge_fingerprint(b"sodium old"), body["fingerprints"])
            return {"data": {"exactMatches": [{"id": 77, "file": {"id": 100, "fileFingerprint": fp,
                                                                  "displayName": "CF Mod 1", "releaseType": 1}}]}}
        if url.endswith("/mods"):
            return {"data": [{"id": 77, "name": "CF Mod", "links": {"websiteUrl": "https://cf/x"},
                              "latestFilesIndexes": [
                                  {"gameVersion": "1.20.1", "fileId": 130, "modLoader": 4, "releaseType": 1},
                                  {"gameVersion": "1.20.1", "fileId": 150, "modLoader": 4, "releaseType": 2},
                                  {"gameVersion": "1.21", "fileId": 170, "modLoader": 4, "releaseType": 1},
                                  {"gameVersion": "1.20.1", "fileId": 160, "modLoader": 1, "releaseType": 1}]}]}
        if url.endswith("/mods/files"):
            self.assertEqual(body["fileIds"], [130])
            return {"data": [{"id": 130, "displayName": "CF Mod 2", "fileName": "cfmod-2.jar",
                              "downloadUrl": "https://edge.forgecdn.net/cfmod-2.jar", "releaseType": 1,
                              "hashes": [{"algo": 1, "value": hashlib.sha1(self.new_cf).hexdigest()}]}]}
        raise AssertionError(url)

    def fake_get(self, url, headers=None):
        if "/project/u6dRKJwZ/version" in url:
            return [mr_version("j3", "u6dRKJwZ", "3.0-beta", "2024-06-01", "beta"),
                    mr_version("j2", "u6dRKJwZ", "2.0", "2024-04-01", data=self.new_jei)]
        if "/projects?ids=" in url:
            return [{"id": "AANobbMI", "title": "Sodium", "slug": "sodium", "project_type": "mod"}]
        raise AssertionError(url)

    def fake_download(self, url):
        return {"https://cdn.modrinth.com/s2.jar": self.new_sodium, "https://cdn.modrinth.com/j2.jar": self.new_jei,
                "https://edge.forgecdn.net/cfmod-2.jar": self.new_cf}[url]

    def run_check(self):
        with mock.patch.object(mod_updates, "_http_post_json", side_effect=self.fake_post), \
                mock.patch.object(mod_updates, "_http_get_json", side_effect=self.fake_get):
            result = mod_updates.check("pack")
        mod_updates._jobs["pack"] = {"state": "done", "result": result}
        return result

    def test_check_finds_updates(self):
        result = self.run_check()
        by_file = {u["filename"]: u for u in result["updates"]}
        self.assertEqual(set(by_file), {"sodium-1.0.jar", "jei-1.0.jar.disabled", "cfmod-1.jar"})
        self.assertEqual(by_file["sodium-1.0.jar"]["name"], "Sodium")
        self.assertEqual(by_file["sodium-1.0.jar"]["page_url"], "https://modrinth.com/mod/sodium")
        self.assertEqual(by_file["jei-1.0.jar.disabled"]["new_version"], "2.0")  # no la beta
        self.assertTrue(by_file["jei-1.0.jar.disabled"]["disabled"])
        self.assertEqual(by_file["cfmod-1.jar"]["new_version"], "CF Mod 2")  # ni beta, ni 1.21, ni Forge
        self.assertEqual((result["total"], result["known"], result["unknown"]), (4, 3, 1))
        cache = json.loads((self.server / mod_updates.HASH_CACHE_NAME).read_text())
        self.assertIn("cf", cache["cfmod-1.jar"])
        self.assertNotIn("cf", cache["sodium-1.0.jar"])  # la huella lenta solo para lo que hace falta

    def test_hash_cache_avoids_rereading(self):
        self.run_check()
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("releído")):
            self.run_check()

    def test_apply_and_undo(self):
        self.run_check()
        with mock.patch.object(mod_updates, "download_bytes", side_effect=self.fake_download):
            first = mod_updates.apply_one("pack", "sodium-1.0.jar")
            mod_updates.apply_one("pack", "jei-1.0.jar.disabled")
            mod_updates.apply_one("pack", "cfmod-1.jar")
        self.assertEqual(first["new_filename"], "sodium-2.0.jar")
        names = sorted(p.name for p in self.mods.iterdir())
        self.assertEqual(names, ["cfmod-2.jar", "hecho-a-mano.jar", "sodium-2.0.jar", "u6dRKJwZ-2.0.jar.disabled"])
        self.assertEqual((self.mods / "sodium-2.0.jar").read_bytes(), self.new_sodium)
        batch = self.server / mod_updates.REPLACED_DIR_NAME / first["batch"]
        self.assertEqual((batch / "sodium-1.0.jar").read_bytes(), b"sodium old")

        undone = mod_updates.undo_batch("pack", first["batch"])
        self.assertEqual(len(undone["restored"]), 3)
        names = sorted(p.name for p in self.mods.iterdir())
        self.assertEqual(names, ["cfmod-1.jar", "hecho-a-mano.jar", "jei-1.0.jar.disabled", "sodium-1.0.jar"])
        self.assertFalse(batch.exists())
        with self.assertRaises(ValueError):
            mod_updates.undo_batch("pack", "../../etc")

    def test_bad_hash_changes_nothing(self):
        self.run_check()
        with mock.patch.object(mod_updates, "download_bytes", return_value=b"manipulado"):
            with self.assertRaises(ValueError):
                mod_updates.apply_one("pack", "sodium-1.0.jar")
        self.assertTrue((self.mods / "sodium-1.0.jar").is_file())
        self.assertFalse((self.mods / "sodium-2.0.jar").exists())

    def test_changed_or_unknown_file_is_refused(self):
        self.run_check()
        with self.assertRaises(ValueError):
            mod_updates.apply_one("pack", "hecho-a-mano.jar")
        os.utime(self.mods / "sodium-1.0.jar", (1, 1))
        with self.assertRaises(ValueError):
            mod_updates.apply_one("pack", "sodium-1.0.jar")

    def test_old_batches_are_pruned(self):
        root = self.server / mod_updates.REPLACED_DIR_NAME
        for i in range(5):
            (root / f"2024010{i}-000000").mkdir(parents=True)
        mod_updates._prune_batches(root)
        self.assertEqual(sorted(p.name for p in root.iterdir()),
                         ["20240102-000000", "20240103-000000", "20240104-000000"])


if __name__ == "__main__":
    unittest.main()
