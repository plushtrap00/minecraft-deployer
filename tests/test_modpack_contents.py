import io
import json
import zipfile
import unittest
from unittest import mock

from services import modpack_install as mi


def _zip(files: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class PackContentsTests(unittest.TestCase):
    def setUp(self):
        mi._pack_contents_cache.clear()
        mi._pack_contents_locks.clear()

    def test_modrinth_statuses_and_embedded_jars(self):
        index = {
            "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.0"},
            "files": [
                {"path": "mods/lithium.jar", "env": {"server": "required"}, "fileSize": 10,
                 "downloads": ["https://cdn.modrinth.com/data/gvQqBUqZ/versions/x/lithium.jar"]},
                {"path": "mods/zoomify.jar", "env": {"server": "unsupported"},
                 "downloads": ["https://cdn.modrinth.com/data/w7ThoJFB/versions/x/zoomify.jar"]},
                {"path": "mods/sodium-fabric-0.6.0.jar", "env": {"server": "optional"},
                 "downloads": ["https://cdn.modrinth.com/data/AANobbMI/versions/x/sodium.jar"]},
                {"path": "resourcepacks/pack.zip", "downloads": ["https://example.com/pack.zip"]},
            ],
        }
        zf = _zip({"modrinth.index.json": json.dumps(index), "overrides/mods/custom-1.0.jar": b"x",
                   "overrides/config/a.toml": b"", "client-overrides/mods/cli.jar": b"x"})
        projects = {"gvQqBUqZ": {"id": "gvQqBUqZ", "title": "Lithium", "slug": "lithium", "project_type": "mod",
                                 "icon_url": "https://cdn.modrinth.com/i.png"}}
        with mock.patch.object(mi, "_get_modrinth_pack_index", return_value=(index, zf)) as get_index, \
                mock.patch.object(mi, "_resolve_modrinth_projects", return_value=projects):
            result = mi.get_modrinth_modpack_mods("p", "v")
            mi.get_modrinth_modpack_mods("p", "v")  # cacheado: no vuelve a descargar
        self.assertEqual(get_index.call_count, 1)
        by_file = {m["filename"]: m for m in result["mods"]}
        self.assertEqual(by_file["lithium.jar"]["name"], "Lithium")
        self.assertEqual(by_file["lithium.jar"]["page_url"], "https://modrinth.com/mod/lithium")
        self.assertEqual(by_file["lithium.jar"]["status"], "install")
        self.assertEqual(by_file["zoomify.jar"]["status"], "client_only")
        self.assertEqual(by_file["sodium-fabric-0.6.0.jar"]["status"], "known_bad")
        self.assertEqual(by_file["pack.zip"]["kind"], "resourcepack")
        self.assertTrue(by_file["custom-1.0.jar"]["embedded"])
        self.assertNotIn("cli.jar", by_file)  # client-overrides no se instala en el servidor
        # Mismo criterio de siempre para la comprobación de duplicados.
        self.assertEqual(sorted(result["filenames"]), ["lithium.jar", "pack.zip", "sodium-fabric-0.6.0.jar"])
        self.assertEqual(result["mc_version"], "1.21.1")
        self.assertEqual(result["mods"][0]["status"], "install")

    def test_curseforge_statuses(self):
        manifest = {
            "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0"}]},
            "files": [
                {"projectID": 1, "fileID": 11}, {"projectID": 2, "fileID": 22},
                {"projectID": 3, "fileID": 33}, {"projectID": 4, "fileID": 44},
                {"projectID": 5, "fileID": 55},
            ],
            "overrides": "overrides",
        }
        zf = _zip({"manifest.json": json.dumps(manifest), "overrides/mods/extra.jar": b"x"})
        files = {
            11: {"downloadUrl": "https://x/a.jar", "fileName": "create-1.20.1.jar", "fileLength": 5},
            22: {"downloadUrl": None, "fileName": "blocked-mod.jar", "fileLength": 1},
            33: {"downloadUrl": "https://x/r.zip", "fileName": "faithful.zip", "fileLength": 1},
            44: {"downloadUrl": "https://x/e.jar", "fileName": "embeddium-0.3.jar", "fileLength": 1},
        }
        projects = {
            1: {"name": "Create", "classId": 6, "logo": {"thumbnailUrl": "https://x/l.png"},
                "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/create"}},
            2: {"name": "Bloqueado", "classId": 6}, 3: {"name": "Faithful", "classId": 12},
            4: {"name": "Embeddium", "classId": 6}, 5: {"name": "Borrado", "classId": 6},
        }
        with mock.patch.object(mi, "_download_curseforge_pack_zip", return_value=(zf, {"server_pack_file_id": 99})), \
                mock.patch.object(mi, "_resolve_curseforge_file_urls", return_value=files), \
                mock.patch.object(mi, "_resolve_curseforge_projects", return_value=projects):
            result = mi.get_curseforge_modpack_mods(10, 20)
        by_name = {m["name"]: m for m in result["mods"]}
        self.assertEqual(by_name["Create"]["status"], "install")
        self.assertEqual(by_name["Create"]["icon_url"], "https://x/l.png")
        self.assertEqual(by_name["Bloqueado"]["status"], "blocked")
        self.assertEqual(by_name["Faithful"]["status"], "not_needed")
        self.assertEqual(by_name["Faithful"]["kind"], "resourcepack")
        self.assertEqual(by_name["Embeddium"]["status"], "known_bad")
        self.assertEqual(by_name["Borrado"]["status"], "unresolved")
        self.assertTrue(by_name["extra"]["embedded"])
        self.assertTrue(result["server_pack"])
        self.assertEqual(result["mc_version"], "1.20.1")


if __name__ == "__main__":
    unittest.main()
