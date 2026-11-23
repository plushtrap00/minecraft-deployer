"""
Partidas de los jugadores (services/sessions.py) y el resumen semanal.
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from services import scheduler, sessions


def ts(*args):
    return datetime(*args).timestamp()


class SessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            mock.patch.object(sessions, "SESSIONS_FILE", Path(self.tmp.name) / "sessions.jsonl"),
            mock.patch.dict(sessions._open, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def play(self, player, start, end, modpack="pack"):
        sessions.joined(modpack, player, at=start)
        sessions.left(modpack, player, at=end)

    def test_join_leave_and_stop(self):
        self.play("Steve", ts(2026, 11, 16, 20, 0), ts(2026, 11, 16, 21, 0))
        self.play("Alex", ts(2026, 11, 16, 20, 0), ts(2026, 11, 16, 20, 0, 10))  # 10 s: no cuenta
        sessions.left("pack", "Nadie")                                             # sin entrar: nada
        sessions.joined("pack", "Alex", at=ts(2026, 11, 16, 22, 0))
        sessions.joined("otro", "Eva", at=ts(2026, 11, 16, 22, 0))
        sessions.server_stopped("pack", at=ts(2026, 11, 16, 23, 0))
        lines = [json.loads(l) for l in sessions.SESSIONS_FILE.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(l["p"], l["e"] - l["s"]) for l in lines], [("Steve", 3600), ("Alex", 3600)])
        self.assertEqual(list(sessions.online_since()), ["Eva"])   # la de otro servidor sigue abierta
        current = sessions.all_sessions(now=ts(2026, 11, 16, 23, 30))
        self.assertTrue(current[-1].get("open"))

    def test_heatmap_splits_hours(self):
        # Lunes de 20:30 a 22:15
        self.play("Steve", ts(2026, 11, 16, 20, 30), ts(2026, 11, 16, 22, 15))
        self.play("Alex", ts(2026, 11, 16, 21, 0), ts(2026, 11, 16, 21, 30))
        data = sessions.heatmap(days=7, now=ts(2026, 11, 20, 12, 0))
        monday = data["grid"][0]
        self.assertEqual((monday[20], monday[21], monday[22]), (30, 90, 15))
        self.assertEqual(data["max"], 90)
        self.assertEqual(sum(map(sum, data["grid"])), 135)
        # Fuera del periodo no cuenta
        self.assertEqual(sessions.heatmap(days=1, now=ts(2026, 11, 20, 12, 0))["max"], 0)
        self.assertEqual(sessions.heatmap(days=7, modpack="otro", now=ts(2026, 11, 20))["max"], 0)

    def test_streak(self):
        for day in (10, 11, 12, 13, 14, 18, 19, 20):
            self.play("Steve", ts(2026, 11, day, 20, 0), ts(2026, 11, day, 21, 0))
        today = sessions.streak(now=ts(2026, 11, 20, 23, 0))
        self.assertEqual(today, {"current": 3, "best": 5, "today": True})
        # Al día siguiente, antes de que juegue nadie, la racha sigue viva
        self.assertEqual(sessions.streak(now=ts(2026, 11, 21, 9, 0))["current"], 3)
        self.assertEqual(sessions.streak(now=ts(2026, 11, 22, 9, 0))["current"], 0)
        # Una partida que cruza la medianoche cuenta para los dos días
        self.play("Alex", ts(2026, 11, 21, 23, 30), ts(2026, 11, 22, 0, 30))
        self.assertEqual(sessions.streak(now=ts(2026, 11, 22, 9, 0))["current"], 5)

    def test_week_summary(self):
        self.play("Steve", ts(2026, 11, 1, 20, 0), ts(2026, 11, 1, 21, 0))       # semana anterior
        self.play("Steve", ts(2026, 11, 17, 20, 0), ts(2026, 11, 17, 23, 0))     # martes, 3 h
        self.play("Alex", ts(2026, 11, 18, 20, 0), ts(2026, 11, 18, 20, 30))
        week = sessions.week_summary(now=ts(2026, 11, 22, 12, 0))
        self.assertEqual((week["players"], week["sessions"], week["hours"]), (2, 2, 3.5))
        self.assertEqual(week["top"][0], {"player": "Steve", "minutes": 180})
        self.assertEqual(week["new_players"], ["Alex"])
        self.assertEqual(week["busiest_weekday"], 1)
        self.assertEqual(week["longest"], {"player": "Steve", "minutes": 180})
        empty = sessions.week_summary(now=ts(2027, 1, 1))
        self.assertEqual((empty["players"], empty["busiest_weekday"]), (0, None))

    def test_trim(self):
        self.play("Viejo", ts(2024, 1, 1, 20, 0), ts(2024, 1, 1, 21, 0))
        self.play("Steve", ts(2026, 11, 17, 20, 0), ts(2026, 11, 17, 21, 0))
        sessions.trim(now=ts(2026, 11, 20))
        self.assertEqual([r["p"] for r in sessions.all_sessions()], ["Steve"])


class WeeklySummaryTests(SessionsTests.__bases__[0]):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.sent = []
        self.settings = {"events": ["weekly"], "telegram_token": "x", "telegram_chat_id": "1",
                         "discord_webhook": "", "language": "es"}
        for patcher in (
            mock.patch.object(sessions, "SESSIONS_FILE", folder / "sessions.jsonl"),
            mock.patch.object(scheduler, "WEEKLY_STATE_FILE", folder / "weekly_summary.json"),
            mock.patch.dict(sessions._open, {}, clear=True),
            mock.patch.object(scheduler.notify_module, "load_settings", side_effect=lambda: self.settings),
            mock.patch.object(scheduler, "notify", side_effect=lambda event, text: self.sent.append(text)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        for day in (19, 20, 21, 22):
            sessions.joined("pack", "Steve", at=ts(2026, 11, day, 20, 0))
            sessions.left("pack", "Steve", at=ts(2026, 11, day, 21, 30))

    def test_message_in_both_languages(self):
        spanish = scheduler.weekly_message(ts(2026, 11, 23, 10, 0), "es")
        self.assertIn("Horas jugadas: 6", spanish)
        self.assertIn("Quien más ha jugado: Steve (6 h)", spanish)
        self.assertIn("🔥 Racha: 4 días seguidos", spanish)
        english = scheduler.weekly_message(ts(2026, 11, 23, 10, 0), "en")
        self.assertIn("Most active player: Steve (6 h)", english)
        self.assertIn("Busiest day: Thursday", english)
        self.assertNotIn("jugad", english)

    def test_player_names_are_not_translated(self):
        sessions.joined("pack", "Nuevo", at=ts(2026, 11, 22, 18, 0))
        sessions.left("pack", "Nuevo", at=ts(2026, 11, 22, 19, 0))
        english = scheduler.weekly_message(ts(2026, 11, 23, 10, 0), "en")
        self.assertIn("New faces: Nuevo, Steve", english)

    def test_sent_once_on_monday_morning(self):
        scheduler._maybe_weekly_summary(datetime(2026, 11, 23, 9, 59))    # lunes, aún no
        scheduler._maybe_weekly_summary(datetime(2026, 11, 24, 12, 0))    # martes
        self.assertEqual(self.sent, [])
        scheduler._maybe_weekly_summary(datetime(2026, 11, 23, 10, 0))
        scheduler._maybe_weekly_summary(datetime(2026, 11, 23, 18, 0))
        self.assertEqual(len(self.sent), 1)
        self.settings["events"] = []
        scheduler._maybe_weekly_summary(datetime(2026, 11, 30, 10, 0))    # desactivado
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
