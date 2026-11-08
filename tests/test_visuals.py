"""
services/visuals.py: cabezas de jugador y logos de modpack. Todo sin red: la
descarga se sustituye por una función falsa.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from services import visuals

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


class ImageTypeTest(unittest.TestCase):
    def test_known_formats(self):
        self.assertEqual(visuals.image_type(PNG), ("image/png", "png"))
        self.assertEqual(visuals.image_type(JPG), ("image/jpeg", "jpg"))
        self.assertEqual(visuals.image_type(WEBP), ("image/webp", "webp"))

    def test_rejects_anything_else(self):
        self.assertIsNone(visuals.image_type(b"<html>no soy una imagen</html>"))
        self.assertIsNone(visuals.image_type(b""))


class HeadCacheKeyTest(unittest.TestCase):
    def test_premium_uuid_is_used(self):
        key = visuals.head_cache_key("Notch", "069a79f4-44e9-4726-a5be-fca90e38aaf5")
        self.assertEqual(key, "069a79f444e94726a5befca90e38aaf5")

    def test_offline_uuid_falls_back_to_name(self):
        # Los UUID de online-mode=false son versión 3 y no llevan a ninguna skin.
        self.assertEqual(visuals.head_cache_key("Steve", "8667ba71-b85a-3004-af54-457a9734eed7"), "steve")

    def test_garbage_uuid_cannot_escape_the_folder(self):
        self.assertEqual(visuals.head_cache_key("Alex", "../../etc/passwd"), "alex")
        self.assertEqual(visuals.head_cache_key("Alex", None), "alex")


class PlayerHeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(visuals, "HEADS_DIR", Path(self.tmp.name) / "heads")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        visuals._failed_heads.clear()

    def test_downloads_once_and_then_uses_the_cache(self):
        with mock.patch.object(visuals, "_download_image", return_value=PNG) as download:
            self.assertEqual(visuals.player_head("Alex"), PNG)
            self.assertEqual(visuals.player_head("Alex"), PNG)
        self.assertEqual(download.call_count, 1)
        self.assertTrue((visuals.HEADS_DIR / "alex.png").is_file())

    def test_stale_copy_is_better_than_nothing(self):
        visuals.HEADS_DIR.mkdir(parents=True)
        cached = visuals.HEADS_DIR / "alex.png"
        cached.write_bytes(PNG)
        old = time.time() - visuals.HEAD_TTL_SECONDS - 60
        os.utime(cached, (old, old))
        with mock.patch.object(visuals, "_download_image", return_value=None):
            self.assertEqual(visuals.player_head("Alex"), PNG)

    def test_failures_are_not_retried_right_away(self):
        with mock.patch.object(visuals, "_download_image", return_value=None) as download:
            self.assertIsNone(visuals.player_head("Nadie"))
            self.assertIsNone(visuals.player_head("Nadie"))
        self.assertEqual(download.call_count, 1)


class PackIconTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = Path(self.tmp.name)

    def test_no_icon(self):
        self.assertIsNone(visuals.pack_icon_path(self.server))

    def test_store_logo_is_saved_with_its_extension(self):
        with mock.patch.object(visuals, "_download_image", return_value=JPG):
            self.assertTrue(visuals.save_pack_icon(self.server, "https://cdn.example/logo"))
        self.assertEqual(visuals.pack_icon_path(self.server), self.server / ".mcdeployer" / "icon.jpg")

    def test_server_icon_wins_over_the_store_logo(self):
        with mock.patch.object(visuals, "_download_image", return_value=JPG):
            visuals.save_pack_icon(self.server, "https://cdn.example/logo")
        (self.server / "server-icon.png").write_bytes(PNG)
        self.assertEqual(visuals.pack_icon_path(self.server), self.server / "server-icon.png")

    def test_failed_download_saves_nothing(self):
        with mock.patch.object(visuals, "_download_image", return_value=None):
            self.assertFalse(visuals.save_pack_icon(self.server, "https://cdn.example/logo"))
        self.assertFalse(visuals.save_pack_icon(self.server, None))
        self.assertIsNone(visuals.pack_icon_path(self.server))

    def test_only_http_urls_are_downloaded(self):
        self.assertIsNone(visuals._download_image("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
