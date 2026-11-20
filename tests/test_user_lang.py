"""
Idioma por cuenta (services/user_prefs.py y routes/auth.py).

Cada cuenta guarda su idioma: se aplica al entrar y tiene prioridad sobre la
cookie del navegador; al cerrar sesión la pantalla vuelve al idioma por
defecto. Una cuenta sin idioma elegido se queda con el de la pantalla de
entrada.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from fastapi import HTTPException, Request

from routes import auth
from services import i18n, user_prefs


def fake_request(cookies=None, user=None, accept="") -> Any:
    return SimpleNamespace(cookies=cookies or {}, headers={"accept-language": accept},
                           state=SimpleNamespace(user=user), client=SimpleNamespace(host="127.0.0.1"))


class UserLangTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefs = Path(self.tmp.name) / ".global" / "user_prefs.json"
        patcher = mock.patch.object(user_prefs, "PREFS_FILE", self.prefs)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("APP_LANGUAGE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_and_forget(self):
        self.assertIsNone(user_prefs.get_lang("ana"))
        user_prefs.set_lang("ana", "en")
        user_prefs.set_lang("luis", "es")
        self.assertEqual(user_prefs.get_lang("ana"), "en")
        self.assertEqual(json.loads(self.prefs.read_text(encoding="utf-8"))["luis"], {"lang": "es"})
        user_prefs.forget("ana")
        self.assertIsNone(user_prefs.get_lang("ana"))
        self.assertEqual(user_prefs.get_lang("luis"), "es")

    def test_account_beats_cookie(self):
        user_prefs.set_lang("ana", "en")
        request = fake_request(cookies={i18n.COOKIE_NAME: "es"}, user="ana")
        self.assertEqual(i18n.request_lang(request), "en")
        self.assertEqual(i18n.request_lang(request, use_account=False), "es")

    def test_account_without_choice_uses_cookie(self):
        request = fake_request(cookies={i18n.COOKIE_NAME: "en"}, user="nadie")
        self.assertEqual(i18n.request_lang(request), "en")

    def test_login_adopts_screen_language_then_keeps_own(self):
        request = fake_request(cookies={i18n.COOKIE_NAME: "en"})
        with mock.patch.object(auth, "authenticate", return_value="user"), \
             mock.patch.object(auth, "create_token", return_value="tok"):
            response = auth.login(cast(Request, request), username="ana", password="x")
            self.assertEqual(json.loads(bytes(response.body).decode())["lang"], "en")
            self.assertEqual(user_prefs.get_lang("ana"), "en")
            # Más tarde, otra persona deja la pantalla en español: ana sigue en inglés.
            request = fake_request(cookies={i18n.COOKIE_NAME: "es"})
            response = auth.login(cast(Request, request), username="ana", password="x")
        self.assertEqual(json.loads(bytes(response.body).decode())["lang"], "en")
        self.assertTrue(any(c.startswith("mcd-lang=en") for c in response.headers.getlist("set-cookie")))

    def test_set_own_language(self):
        response = auth.set_own_language(cast(Request, fake_request(user="ana")), auth.LanguageBody(lang="en"))
        self.assertEqual(user_prefs.get_lang("ana"), "en")
        self.assertTrue(any(c.startswith("mcd-lang=en") for c in response.headers.getlist("set-cookie")))
        with self.assertRaises(HTTPException):
            auth.set_own_language(cast(Request, fake_request(user="ana")), auth.LanguageBody(lang="fr"))
        with self.assertRaises(HTTPException):
            auth.set_own_language(cast(Request, fake_request()), auth.LanguageBody(lang="en"))

    def test_logout_returns_default_and_clears_cookie(self):
        os.environ["APP_LANGUAGE"] = "en"
        response = auth.logout(cast(Request, fake_request(cookies={i18n.COOKIE_NAME: "es"})))
        self.assertEqual(json.loads(bytes(response.body).decode())["lang"], "en")
        cookies = response.headers.getlist("set-cookie")
        self.assertTrue(any(c.startswith(i18n.COOKIE_NAME + '=""') or c.startswith(i18n.COOKIE_NAME + "=;") for c in cookies), cookies)


if __name__ == "__main__":
    unittest.main()
