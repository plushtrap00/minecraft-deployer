import unittest

from services.mod_search import modrinth_result_extras, curseforge_result_extras


class SearchExtrasTests(unittest.TestCase):
    def test_modrinth_separates_loaders_and_formats_color(self):
        hit = {
            "categories": ["optimization", "fabric", "neoforge", "babric"],
            "display_categories": ["optimization", "fabric", "babric", "decoration"],
            "date_modified": "2026-11-01T10:43:17Z",
            "color": 0x84CC6C,
        }
        extras = modrinth_result_extras(hit)
        self.assertEqual(extras["categories"], ["optimization", "decoration"])
        # Todos los loaders; el frontend solo pinta los que conoce.
        self.assertEqual(extras["loaders"], ["fabric", "neoforge", "babric"])
        self.assertEqual(extras["updated"], "2026-11-01T10:43:17Z")
        self.assertEqual(extras["color"], "#84cc6c")

    def test_modrinth_without_optional_fields(self):
        extras = modrinth_result_extras({"color": "rojo"})
        self.assertEqual(extras, {"categories": [], "loaders": [], "updated": None, "color": None})

    def test_curseforge_loaders_from_latest_files(self):
        mod = {
            "categories": [{"name": "Tech"}, {"name": "Magic"}, {"name": "Storage"}, {"name": "Extra"}],
            "latestFilesIndexes": [{"modLoader": 6}, {"modLoader": 1}, {"modLoader": 6}, {"modLoader": 99}],
            "dateModified": "2026-10-01T00:00:00Z",
        }
        extras = curseforge_result_extras(mod)
        self.assertEqual(extras["categories"], ["Tech", "Magic", "Storage"])
        self.assertEqual(extras["loaders"], ["neoforge", "forge"])
        self.assertEqual(extras["updated"], "2026-10-01T00:00:00Z")
        self.assertIsNone(extras["color"])


if __name__ == "__main__":
    unittest.main()
