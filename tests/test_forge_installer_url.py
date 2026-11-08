import unittest
from unittest import mock

from services import modloader


KNOWN = ["1.20.1-47.2.0", "1.20.1-47.1.0", "1.7.10-10.13.4.1614-1.7.10"]


def fake_versions(mc_version):
    return [v for v in KNOWN if v.startswith(mc_version + "-")]


class ForgeInstallerUrlTests(unittest.TestCase):
    def url(self, mc, version):
        with mock.patch.object(modloader, "_forge_versions_for", side_effect=fake_versions):
            return modloader._installer_url("forge", mc, version)[0]

    def test_bare_version_from_modpack_gets_mc_prefix(self):
        # Lo que trae un modpack de Modrinth/CurseForge: solo la parte de Forge.
        self.assertTrue(self.url("1.20.1", "47.2.0").endswith("/forge/1.20.1-47.2.0/forge-1.20.1-47.2.0-installer.jar"))

    def test_full_version_from_panel_list_is_untouched(self):
        self.assertIn("/forge/1.20.1-47.1.0/", self.url("1.20.1", "1.20.1-47.1.0"))

    def test_old_builds_with_suffix_are_found_in_the_list(self):
        self.assertIn("/forge/1.7.10-10.13.4.1614-1.7.10/", self.url("1.7.10", "10.13.4.1614"))

    def test_list_unreachable_falls_back_to_prefix(self):
        with mock.patch.object(modloader, "_forge_versions_for", side_effect=OSError("sin red")):
            url = modloader._installer_url("forge", "1.20.1", "47.2.0")[0]
        self.assertIn("/forge/1.20.1-47.2.0/", url)


if __name__ == "__main__":
    unittest.main()
