"""
Verificación en dos pasos (services/two_factor.py, services/qr.py y el login
en dos pasos de routes/auth.py) y el bloqueo de intentos guardado en disco.
"""
import base64
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from fastapi import HTTPException

from routes import auth
from services import qr, two_factor


def fake_request(user=None, ip="10.0.0.5") -> Any:
    return SimpleNamespace(cookies={}, headers={}, state=SimpleNamespace(user=user, role="admin"),
                           client=SimpleNamespace(host=ip))


class TotpTests(unittest.TestCase):
    # RFC 6238, apéndice B (SHA1, secreto "12345678901234567890").
    SECRET = base64.b32encode(b"12345678901234567890").decode()

    def test_rfc6238_vectors(self):
        key = two_factor._key(self.SECRET)
        for at, expected in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                             (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")):
            self.assertEqual(two_factor.hotp(key, at // 30, digits=8), expected, at)
        self.assertEqual(two_factor.totp(self.SECRET, 59), "287082")

    def test_window_accepts_neighbours_only(self):
        now = 1_800_000_000
        code = two_factor.totp(self.SECRET, now)
        self.assertIsNotNone(two_factor._match_step(self.SECRET, code, now + 30))
        self.assertIsNotNone(two_factor._match_step(self.SECRET, code, now - 30))
        self.assertIsNone(two_factor._match_step(self.SECRET, code, now + 90))

    def test_uri(self):
        uri = two_factor.otpauth_uri("ana", "ABC")
        self.assertEqual(uri, "otpauth://totp/Server%20Deployer%3Aana?secret=ABC&issuer=Server%20Deployer")


class QrTests(unittest.TestCase):
    # Huellas de las matrices de la librería de referencia «qrcode» 8.2 (modo
    # byte, nivel M, versión y máscara fijas): el generador propio tiene que
    # dar exactamente lo mismo.
    GOLDEN = [
        ("HOLA", 1, 0, "70e4446d491c68a62860dcfacad91450839cfed985a72381db9b9e597959d1f9"),
        ("otpauth://totp/MC:admin?secret=ABC", 3, 5, "1d8a6332af8fe002c6b326ba8ecee757639fba5301523df13d8f9414318eb27f"),
        ("x" * 100, 6, 2, "c4e995e60adf6c352ad27d5b24c631d286e2b4e7728c5606733996109139917c"),
        ("otpauth://totp/MC%20Deployer:pablo?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=MC%20Deployer", 8, 7,
         "cd321b6a82d41734545d2288228100ee87c68e60d3543dca1abadc7cd1188f5e"),
        ("ñandú" * 30, 10, 3, "d745f169ce2c3fa5b82e2afde0b501450520e0a93974f1337aa2048a217f0a69"),
    ]

    def test_matches_reference(self):
        for text, version, mask, digest in self.GOLDEN:
            modules = qr.matrix(text, mask=mask, version=version)
            flat = "\n".join("".join("1" if c else "0" for c in row) for row in modules)
            self.assertEqual(hashlib.sha256(flat.encode()).hexdigest(), digest, (version, mask))

    def test_svg_and_limits(self):
        svg = qr.svg(two_factor.otpauth_uri("pablo", two_factor.new_secret()))
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertNotIn("<script", svg)
        with self.assertRaises(ValueError):
            qr.matrix("x" * 300)


class AccountTwoFactorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            mock.patch.object(two_factor, "STORE_FILE", Path(self.tmp.name) / "two_factor.json"),
            mock.patch.object(auth, "ATTEMPTS_FILE", Path(self.tmp.name) / "login_attempts.json"),
            mock.patch.dict(auth._failed_attempts, {}, clear=True),
            mock.patch.object(auth, "authenticate", side_effect=lambda u, p: "admin" if p == "buena" else None),
            mock.patch.object(auth, "password_fingerprint", return_value="huella"),
            mock.patch.object(auth, "role_of", return_value="admin"),
            mock.patch.object(auth, "get_jwt_secret", return_value="secreto-de-prueba"),
            mock.patch.object(auth.user_prefs, "get_lang", return_value="es"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def enable(self, user="ana") -> tuple:
        setup = two_factor.begin_setup(user)
        codes = two_factor.confirm_setup(user, two_factor.totp(setup["secret"]))
        return setup["secret"], codes

    def test_setup_needs_a_valid_code(self):
        setup = two_factor.begin_setup("ana")
        self.assertFalse(two_factor.is_enabled("ana"))
        with self.assertRaises(ValueError):
            two_factor.confirm_setup("ana", "000000" if two_factor.totp(setup["secret"]) != "000000" else "111111")
        codes = two_factor.confirm_setup("ana", two_factor.totp(setup["secret"]))
        self.assertEqual(len(codes), 8)
        self.assertTrue(two_factor.is_enabled("ana"))
        stored = json.loads(two_factor.STORE_FILE.read_text())["ana"]
        self.assertNotIn(codes[0], json.dumps(stored))  # solo se guardan los hashes
        with self.assertRaises(ValueError):
            two_factor.begin_setup("ana")

    def test_codes_cannot_be_reused(self):
        secret, _ = self.enable()
        # El mismo código con el que se activó no vale otra vez para entrar.
        self.assertIsNone(two_factor.verify("ana", two_factor.totp(secret)))
        later = time.time() + 30
        with mock.patch.object(two_factor.time, "time", return_value=later):
            code = two_factor.totp(secret)
            self.assertEqual(two_factor.verify("ana", code), "totp")
            self.assertIsNone(two_factor.verify("ana", code))

    def test_recovery_codes_work_once(self):
        _, codes = self.enable()
        self.assertEqual(two_factor.verify("ana", codes[3].upper().replace("-", " ")), "recovery")
        self.assertIsNone(two_factor.verify("ana", codes[3]))
        self.assertEqual(two_factor.status("ana")["recovery_left"], 7)
        fresh = two_factor.regenerate_recovery("ana")
        self.assertIsNone(two_factor.verify("ana", codes[0]))
        self.assertEqual(two_factor.verify("ana", fresh[0]), "recovery")

    def test_login_in_two_steps(self):
        secret, codes = self.enable()
        first = auth.login(fake_request(), username="ana", password="buena")
        body = json.loads(bytes(first.body))
        self.assertTrue(body["two_factor"])
        self.assertNotIn("set-cookie", first.headers)  # sin sesión todavía
        ticket = body["ticket"]
        # El ticket no sirve como sesión.
        self.assertIsNone(auth.verify_token(ticket))
        self.assertIsNotNone(auth.verify_token(ticket, use="2fa"))
        with self.assertRaises(HTTPException) as ctx:
            auth.login_second_step(fake_request(), ticket=ticket, code="123")
        self.assertEqual(ctx.exception.status_code, 401)
        later = time.time() + 30
        with mock.patch.object(two_factor.time, "time", return_value=later):
            done = auth.login_second_step(fake_request(), ticket=ticket, code=two_factor.totp(secret))
        self.assertIn(auth.SESSION_COOKIE, done.headers["set-cookie"])
        self.assertEqual(json.loads(bytes(done.body))["user"], "ana")
        # Con un código de recuperación, se dice cuántos quedan.
        again = auth.login_second_step(fake_request(), ticket=ticket, code=codes[0])
        self.assertEqual(json.loads(bytes(again.body))["recovery_left"], 7)
        # Una sesión no vale como ticket.
        session = auth.create_token("ana")
        with self.assertRaises(HTTPException):
            auth.login_second_step(fake_request(), ticket=session, code=codes[1])

    def test_expired_ticket(self):
        self.enable()
        ticket = auth.create_token("ana", use="2fa", seconds=-1)
        with self.assertRaises(HTTPException) as ctx:
            auth.login_second_step(fake_request(), ticket=ticket, code="123456")
        self.assertIn("tiempo", ctx.exception.detail)

    def test_wrong_codes_lock_out(self):
        self.enable()
        ticket = json.loads(bytes(auth.login(fake_request(), username="ana", password="buena").body))["ticket"]
        for _ in range(auth._MAX_FAILED_ATTEMPTS):
            with self.assertRaises(HTTPException):
                auth.login_second_step(fake_request(), ticket=ticket, code="000000")
        with self.assertRaises(HTTPException) as ctx:
            auth.login_second_step(fake_request(), ticket=ticket, code="000000")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_lockout_survives_restart(self):
        for _ in range(auth._MAX_FAILED_ATTEMPTS):
            with self.assertRaises(HTTPException):
                auth.login(fake_request(), username="luis", password="mala")
        self.assertTrue(auth.ATTEMPTS_FILE.is_file())
        # «Reinicio»: la memoria se vacía y se vuelve a leer del disco.
        auth._failed_attempts.clear()
        auth._failed_attempts.update(auth._load_failed_attempts())
        with self.assertRaises(HTTPException) as ctx:
            auth.login(fake_request(), username="luis", password="buena")
        self.assertEqual(ctx.exception.status_code, 429)
        # Los fallos viejos (fuera de la ventana) no se cargan.
        old = time.time() - auth._ATTEMPT_WINDOW_SECONDS - 5
        auth.ATTEMPTS_FILE.write_text(json.dumps({"ip:1.2.3.4": [old]}))
        self.assertEqual(auth._load_failed_attempts(), {"ip:1.2.3.4": []})

    def test_disable_needs_password(self):
        self.enable()
        with mock.patch.object(auth, "verify_password", return_value=False):
            with self.assertRaises(HTTPException):
                auth.disable_own_two_factor(fake_request("ana"), auth.TwoFactorCodeBody(password="mala"))
        self.assertTrue(two_factor.is_enabled("ana"))
        with mock.patch.object(auth, "verify_password", return_value=True):
            auth.disable_own_two_factor(fake_request("ana"), auth.TwoFactorCodeBody(password="buena"))
        self.assertFalse(two_factor.is_enabled("ana"))


if __name__ == "__main__":
    unittest.main()
