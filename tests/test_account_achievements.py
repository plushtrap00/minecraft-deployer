"""
Logros por cuenta (services/user_prefs.py y /api/auth/achievements).

Antes vivían en el localStorage de cada navegador y desaparecían al entrar
desde otro dispositivo; ahora se guardan con la cuenta. La mezcla nunca quita
nada y, si un logro llega dos veces, se queda con la fecha más antigua.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from fastapi import HTTPException

from routes import auth
from services import user_prefs


def fake_request(user=None) -> Any:
    return SimpleNamespace(cookies={}, headers={}, state=SimpleNamespace(user=user),
                           client=SimpleNamespace(host="127.0.0.1"))


class AccountAchievementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(user_prefs, "PREFS_FILE", Path(self.tmp.name) / ".global" / "user_prefs.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_merge_keeps_oldest_and_never_removes(self):
        user_prefs.merge_achievements("ana", {"first-start": 2000, "konami": 5000})
        state = user_prefs.merge_achievements("ana", {"first-start": 1000, "konami": 9000, "tnt": 3000})
        self.assertEqual(state["unlocked"], {"first-start": 1000, "konami": 5000, "tnt": 3000})
        state = user_prefs.merge_achievements("ana", {})
        self.assertEqual(len(state["unlocked"]), 3)

    def test_seen_values_are_unique(self):
        user_prefs.merge_achievements("ana", seen={"tourist": ["nether", "end"]})
        state = user_prefs.merge_achievements("ana", seen={"tourist": ["end", "surface"]})
        self.assertEqual(state["seen"]["tourist"], ["nether", "end", "surface"])

    def test_accounts_are_separate_and_keep_language(self):
        user_prefs.set_lang("ana", "en")
        user_prefs.merge_achievements("ana", {"tnt": 1})
        self.assertEqual(user_prefs.get_achievements("luis"), {"unlocked": {}, "seen": {}})
        self.assertEqual(user_prefs.get_lang("ana"), "en")
        user_prefs.forget("ana")
        self.assertEqual(user_prefs.get_achievements("ana")["unlocked"], {})

    def test_garbage_is_ignored(self):
        state = user_prefs.merge_achievements("ana", {
            "../evil": 1, "ok": "texto", "neg": -5, "bool": True, "x" * 41: 1, "bien": 7,
        }, {"tourist": [1, "", "y" * 61, "vale"], "../no": ["a"], "notlist": "a"})
        self.assertEqual(state["unlocked"], {"bien": 7})
        self.assertEqual(state["seen"], {"tourist": ["vale"]})

    def test_limits(self):
        many = {f"a{i}": i + 1 for i in range(300)}
        state = user_prefs.merge_achievements("ana", many)
        self.assertEqual(len(state["unlocked"]), 200)

    def test_routes_need_session(self):
        with self.assertRaises(HTTPException) as ctx:
            auth.get_own_achievements(fake_request())
        self.assertEqual(ctx.exception.status_code, 401)
        body = auth.AchievementsBody(unlocked={"tnt": 10}, seen={})
        self.assertEqual(auth.add_own_achievements(fake_request("ana"), body)["unlocked"], {"tnt": 10})
        self.assertEqual(auth.get_own_achievements(fake_request("ana"))["unlocked"], {"tnt": 10})


if __name__ == "__main__":
    unittest.main()
