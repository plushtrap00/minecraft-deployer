"""Validación de rutas, nombres y sesiones: lo que separa a un usuario del resto del disco."""
import io
import os
import shutil
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

import bcrypt
from fastapi import HTTPException

from config import DEFAULT_SERVERS_PATH
from routes import auth
from routes.deps import modpack_path, world_path
from routes.firewall import parse_ufw_mode
from services.players import sanitize_reason, validate_ip, validate_player_name
from services.utils import extract_archive


class ModpackPathTest(unittest.TestCase):
    def setUp(self):
        (DEFAULT_SERVERS_PATH / "packA").mkdir(exist_ok=True)

    def test_existing_modpack(self):
        self.assertEqual(modpack_path("packA"), DEFAULT_SERVERS_PATH / "packA")

    def test_rejects_traversal_and_hidden(self):
        for name in ["..", ".", ".global", "a/b", "a\\b", "", "x\x00y"]:
            with self.subTest(name=name), self.assertRaises(HTTPException) as ctx:
                modpack_path(name)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_missing_modpack_is_404(self):
        with self.assertRaises(HTTPException) as ctx:
            modpack_path("noexiste")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_world_names(self):
        base = DEFAULT_SERVERS_PATH / "packA"
        self.assertEqual(world_path(base, "world"), base / "world")
        for name in ["..", ".", "../packB", "a/b"]:
            with self.subTest(name=name), self.assertRaises(HTTPException):
                world_path(base, name)


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tar(self, name: str, data: bytes = b"x", link_to: str | None = None) -> Path:
        path = self.tmp / "a.tar.gz"
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo(name)
            if link_to:
                info.type = tarfile.SYMTYPE
                info.linkname = link_to
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return path

    def test_normal_tar_extracts(self):
        extract_archive(self._tar("start.sh"), self.tmp / "out")
        self.assertTrue((self.tmp / "out" / "start.sh").exists())

    def test_tar_slip_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            extract_archive(self._tar("../../fuera.txt"), self.tmp / "out")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertFalse((self.tmp / "fuera.txt").exists())

    def test_symlink_outside_rejected(self):
        with self.assertRaises(HTTPException):
            extract_archive(self._tar("enlace", link_to="/etc/passwd"), self.tmp / "out")


class PlayerInputTest(unittest.TestCase):
    def test_player_names(self):
        self.assertEqual(validate_player_name("  Steve_01 "), "Steve_01")
        for bad in ["a b", "x\nstop", "nombre_demasiado_largo", ""]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_player_name(bad)

    def test_ip(self):
        self.assertEqual(validate_ip("192.168.1.50"), "192.168.1.50")
        with self.assertRaises(ValueError):
            validate_ip("1.2.3.4\nstop")

    def test_reason_strips_control_chars(self):
        self.assertEqual(sanitize_reason("spam\nstop"), "spamstop")
        self.assertEqual(sanitize_reason("\n"), "Sin motivo especificado")


class SessionTokenTest(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("JWT_SECRET", "APP_USERNAME", "APP_PASSWORD_HASH")}
        os.environ["JWT_SECRET"] = "secreto-de-pruebas"
        os.environ["APP_USERNAME"] = "admin"
        os.environ["APP_PASSWORD_HASH"] = bcrypt.hashpw(b"clave-uno", bcrypt.gensalt(4)).decode()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_roundtrip(self):
        info = auth.verify_token(auth.create_token("admin"))
        self.assertEqual(info, {"sub": "admin", "role": "admin"})

    def test_tampered_payload_rejected(self):
        header, _, signature = auth.create_token("admin").split(".")
        forged_payload = auth._b64url_encode(b'{"sub":"admin","exp":9999999999,"pwf":"x"}')
        self.assertIsNone(auth.verify_token(f"{header}.{forged_payload}.{signature}"))

    def test_other_secret_rejected(self):
        token = auth.create_token("admin")
        os.environ["JWT_SECRET"] = "otro-secreto"
        self.assertIsNone(auth.verify_token(token))

    def test_alg_none_rejected(self):
        _, payload, _ = auth.create_token("admin").split(".")
        header = auth._b64url_encode(b'{"alg":"none","typ":"JWT"}')
        self.assertIsNone(auth.verify_token(f"{header}.{payload}."))

    def test_password_change_revokes(self):
        token = auth.create_token("admin")
        os.environ["APP_PASSWORD_HASH"] = bcrypt.hashpw(b"clave-dos", bcrypt.gensalt(4)).decode()
        self.assertIsNone(auth.verify_token(token))

    def test_unknown_user_rejected(self):
        self.assertIsNone(auth.verify_token(auth.create_token("nadie")))

    def test_expired_rejected(self):
        original = auth.TOKEN_EXPIRE_HOURS
        auth.TOKEN_EXPIRE_HOURS = -1
        try:
            token = auth.create_token("admin")
        finally:
            auth.TOKEN_EXPIRE_HOURS = original
        self.assertIsNone(auth.verify_token(token))

    def test_garbage_rejected(self):
        for token in ["", "a.b", "a.b.c", "....", "x" * 50]:
            with self.subTest(token=token):
                self.assertIsNone(auth.verify_token(token))


class FirewallParseTest(unittest.TestCase):
    STATUS = (
        "Status: active\n\n"
        "To                         Action      From\n"
        "--                         ------      ----\n"
        "22/tcp                     ALLOW       Anywhere\n"
        "{rule}\n"
    )

    def test_public(self):
        out = self.STATUS.format(rule="25565                      ALLOW       Anywhere")
        self.assertEqual(parse_ufw_mode(out, [25565], "192.168.0.0/24"), "public")

    def test_lan_current_and_legacy_subnet(self):
        out = self.STATUS.format(rule="25565                      ALLOW       192.168.0.0/24")
        self.assertEqual(parse_ufw_mode(out, [25565], "192.168.0.0/24"), "lan")
        out = self.STATUS.format(rule="25565                      ALLOW       192.168.1.0/24")
        self.assertEqual(parse_ufw_mode(out, [25565], "192.168.0.0/24"), "lan")

    def test_other_ports_ignored(self):
        # El 22 abierto a todo el mundo no cuenta como "público" para Minecraft.
        out = self.STATUS.format(rule="")
        self.assertEqual(parse_ufw_mode(out, [25565], "192.168.0.0/24"), "unknown")

    def test_custom_port(self):
        out = self.STATUS.format(rule="25570/tcp                  ALLOW       Anywhere")
        self.assertEqual(parse_ufw_mode(out, [25570], "192.168.0.0/24"), "public")


if __name__ == "__main__":
    unittest.main()
