"""
Registro de actividad (services/activity.py).
"""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import activity

ROOT = Path(__file__).resolve().parent.parent


def fake_request(method, path, user="ana", query=None, **state):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), query_params=query or {},
                           state=SimpleNamespace(user=user, **state), client=SimpleNamespace(host="10.0.0.9"))


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(activity, "ACTIVITY_FILE", Path(self.tmp.name) / "activity.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_match(self):
        self.assertEqual(activity.match("DELETE", "/api/modpacks/pack/mods/x.jar"),
                         ("mods.delete", {"modpack": "pack", "filename": "x.jar"}))
        self.assertEqual(activity.match("DELETE", "/api/modpacks/pack"), ("modpack.delete", {"modpack": "pack"}))
        self.assertIsNone(activity.match("GET", "/api/modpacks/pack/mods"))
        self.assertIsNone(activity.match("POST", "/api/auth/achievements"))

    def test_record_request(self):
        activity.record_request(fake_request("POST", "/api/server/command", activity_detail="say hola"), 200)
        activity.record_request(fake_request("POST", "/api/server/start", activity_params={"modpack": "pack"}), 200)
        activity.record_request(fake_request("POST", "/api/server/stop"), 409)  # falló: no se apunta
        activity.record_request(fake_request("GET", "/api/create-server/stream", query={"name": "nuevo"}), 200)
        activity.record_request(fake_request("GET", "/api/modpacks/p/pack-update/stream", activity_skip=True), 200)
        items = activity.read()["items"]
        self.assertEqual([i["action"] for i in items], ["modpack.create", "server.start", "server.command"])
        self.assertEqual(items[0]["params"], {"name": "nuevo"})
        self.assertEqual(items[2]["detail"], "say hola")
        self.assertEqual(items[2]["ip"], "10.0.0.9")

    def test_filters_and_paging(self):
        for i in range(5):
            activity.record("server.start", "ana", {"modpack": f"p{i}"})
            time.sleep(0.002)
        activity.record("backups.auto", params={"modpack": "p"})
        activity.record("no.existe", "ana")
        data = activity.read(limit=3)
        self.assertEqual(len(data["items"]), 3)
        self.assertTrue(data["more"])
        self.assertEqual(data["users"], ["", "ana"])
        rest = activity.read(limit=10, before=data["items"][-1]["ts"])
        self.assertEqual(len(rest["items"]), 3)
        self.assertEqual([i["action"] for i in activity.read(user="")["items"]], ["backups.auto"])
        self.assertEqual(len(activity.read(category="backups")["items"]), 1)

    def test_trim(self):
        with mock.patch.object(activity, "MAX_ENTRIES", 10):
            for i in range(25):
                activity.record("server.start", "ana", {"modpack": str(i)})
            activity._trim()
        lines = activity.ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 10)
        self.assertEqual(json.loads(lines[-1])["params"]["modpack"], "24")

    def test_never_raises(self):
        with mock.patch("builtins.open", side_effect=OSError("disco lleno")):
            activity.record("server.start", "ana")


class ActivityCatalogTests(unittest.TestCase):
    def test_routes_exist_in_the_app(self):
        import main
        real = {(method.upper(), path) for path, ops in main.app.openapi()["paths"].items() for method in ops}
        missing = [(m, p) for m, p, _ in activity.ROUTES if (m, p) not in real]
        self.assertEqual(missing, [])
        self.assertTrue(all(action in activity.ACTIONS for _, _, action in activity.ROUTES))

    def test_labels_translated(self):
        en = json.loads((ROOT / "static/i18n/en.json").read_text(encoding="utf-8"))
        missing = [label for _, label in activity.ACTIONS.values() if label not in en]
        self.assertEqual(missing, [])
        for category, label in activity.ACTIONS.values():
            self.assertIn(category, activity.CATEGORIES)
            # Los mismos {parámetros} en las dos lenguas.
            if label in en:
                self.assertEqual(sorted(re.findall(r"\{\w+\}", label)), sorted(re.findall(r"\{\w+\}", en[label])), label)


if __name__ == "__main__":
    unittest.main()
