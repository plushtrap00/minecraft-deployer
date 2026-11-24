"""
Paquete para jugadores (services/client_pack.py) con Modrinth y CurseForge
simulados: qué mods van referenciados, cuáles dentro del paquete, cuáles se
quitan por ser solo de servidor, lo que aporta el modpack original y el aviso
de paquete desactualizado.
"""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from services import client_pack, mod_updates


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class ClientPackTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.server = self.root / "pack"
        self.mods = self.server / "mods"
        self.mods.mkdir(parents=True)
        (self.mods / "jei.jar").write_bytes(b"jei")                 # Modrinth y CurseForge
        (self.mods / "solo-cf.jar").write_bytes(b"solo cf")         # solo CurseForge
        (self.mods / "propio.jar").write_bytes(b"hecho a mano")     # ninguno
        (self.mods / "chunky.jar").write_bytes(b"chunky")           # solo de servidor (Modrinth)
        (self.mods / "viejo.jar.disabled").write_bytes(b"viejo")    # desactivado, no es de cliente
        for patcher in (
            mock.patch.object(client_pack, "DEFAULT_SERVERS_PATH", self.root),
            mock.patch.object(mod_updates, "DEFAULT_SERVERS_PATH", self.root),
            mock.patch("services.modpack_update.DEFAULT_SERVERS_PATH", self.root),
            mock.patch.object(client_pack, "detect_modpack_version", return_value={
                "mc_version": "1.21.1", "modloader": "NeoForge", "modloader_version": "21.1.266"}),
            mock.patch.object(client_pack, "CURSEFORGE_API_KEY", "clave"),
            mock.patch.object(client_pack, "_is_client_only", return_value=False),
            mock.patch.dict(client_pack._jobs, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    # Modrinth: version_files + projects (client_side)
    def fake_mr_post(self, url, body, headers=None):
        def version(project, data, name):
            return {"project_id": project, "files": [{
                "url": f"https://cdn.modrinth.com/data/{project}/{name}", "filename": name, "size": len(data),
                "hashes": {"sha1": sha1(data), "sha512": hashlib.sha512(data).hexdigest()}}]}
        if url.endswith("/version_files"):
            known = {sha1(b"jei"): version("JEI", b"jei", "jei.jar"),
                     sha1(b"chunky"): version("CHUNKY", b"chunky", "chunky.jar")}
            return {h: v for h, v in known.items() if h in body["hashes"]}
        if "/fingerprints/" in url:
            fp = {mod_updates.curseforge_fingerprint(b"jei"): (238222, 1),
                  mod_updates.curseforge_fingerprint(b"solo cf"): (555, 2)}
            url = None if getattr(self, "restricted", False) else "https://edge.forgecdn.net/x"
            matches = [{"id": pid, "file": {"id": fid, "fileFingerprint": f, "downloadUrl": url}}
                       for f, (pid, fid) in fp.items() if f in body["fingerprints"]]
            return {"data": {"exactMatches": matches}}
        raise AssertionError(url)

    def fake_get_list(self, url):
        self.assertIn("/projects?ids=", url)
        return [{"id": "JEI", "client_side": "required"}, {"id": "CHUNKY", "client_side": "unsupported"}]

    def build(self, fmt):
        with mock.patch.object(mod_updates, "_post", side_effect=self.fake_mr_post), \
             mock.patch.object(mod_updates, "_get_list", side_effect=self.fake_get_list), \
             mock.patch("services.mod_search._curseforge_headers", return_value={}):
            return client_pack.build("pack", fmt)

    def test_mrpack(self):
        meta = self.build("mrpack")
        self.assertEqual(meta["excluded"], ["chunky.jar"])
        self.assertEqual(meta["bundled"], ["propio.jar", "solo-cf.jar"])
        self.assertEqual(meta["linked"], 1)
        with zipfile.ZipFile(self.server / ".client-pack" / "pack.mrpack") as zf:
            index = json.loads(zf.read("modrinth.index.json"))
            names = set(zf.namelist())
        self.assertEqual(index["dependencies"], {"minecraft": "1.21.1", "neoforge": "21.1.266"})
        self.assertEqual([f["path"] for f in index["files"]], ["mods/jei.jar"])
        self.assertEqual(index["files"][0]["hashes"]["sha512"], hashlib.sha512(b"jei").hexdigest())
        self.assertIn("overrides/mods/propio.jar", names)
        self.assertNotIn("overrides/mods/viejo.jar", names)

    def test_mrpack_respects_authors_that_forbid_redistribution(self):
        # CurseForge da downloadUrl null cuando el autor no permite descargas por terceros:
        # ese jar no se mete en el .mrpack (cada jugador lo baja de CurseForge).
        self.restricted = True
        meta = self.build("mrpack")
        self.assertEqual(meta["restricted"], ["solo-cf.jar"])
        self.assertEqual(meta["bundled"], ["propio.jar"])
        with zipfile.ZipFile(self.server / ".client-pack" / "pack.mrpack") as zf:
            self.assertNotIn("overrides/mods/solo-cf.jar", zf.namelist())

    def test_curseforge_zip(self):
        meta = self.build("curseforge")
        self.assertEqual(meta["bundled"], ["propio.jar"])
        with zipfile.ZipFile(self.server / ".client-pack" / "pack.zip") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["minecraft"]["modLoaders"], [{"id": "neoforge-21.1.266", "primary": True}])
        self.assertEqual(sorted((f["projectID"], f["fileID"]) for f in manifest["files"]), [(555, 2), (238222, 1)])

    def test_original_pack_keeps_its_client_mods(self):
        # El modpack original pone chunky en el cliente: va aunque Modrinth diga que no hace falta.
        # Y aporta un mod solo de cliente que el servidor no tiene (ni tuvo) y su configuración.
        (self.server / ".pack_source.json").write_text(json.dumps({
            "source": "modrinth", "project_id": "P", "version_id": "V", "version_number": "1.0",
            "pack_mods": ["jei.jar", "chunky.jar", "quitado.jar"]}), encoding="utf-8")
        original = {"files": [{"folder": "mods", "filename": "sodium.jar", "mr": {"path": "mods/sodium.jar"}}],
                    "overrides": {"config/a.toml": b"x"}, "client_mods": {"chunky.jar", "sodium.jar", "jei.jar"}}
        with mock.patch.object(client_pack, "_original_pack", return_value=original):
            meta = self.build("mrpack")
        self.assertEqual(meta["excluded"], [])
        self.assertEqual(meta["extras"], 1)
        self.assertEqual(meta["overrides"], 1)
        with zipfile.ZipFile(self.server / ".client-pack" / "pack.mrpack") as zf:
            index = json.loads(zf.read("modrinth.index.json"))
            self.assertEqual(zf.read("overrides/config/a.toml"), b"x")
        self.assertIn("mods/sodium.jar", [f["path"] for f in index["files"]])

    def test_stale_when_mods_change(self):
        self.build("mrpack")
        self.assertFalse(client_pack.status("pack")["formats"]["mrpack"]["file"]["stale"])
        (self.mods / "nuevo.jar").write_bytes(b"nuevo")
        status = client_pack.status("pack")
        self.assertTrue(status["formats"]["mrpack"]["file"]["stale"])
        self.assertIsNone(status["formats"]["curseforge"]["file"])

    def test_unknown_format(self):
        with self.assertRaises(client_pack.ClientPackError):
            client_pack.build("pack", "exe")
        self.assertIsNone(client_pack.file_for_download("pack", "exe"))


if __name__ == "__main__":
    unittest.main()
