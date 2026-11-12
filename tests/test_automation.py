"""
Copias de seguridad, clonado, estadísticas de jugadores, historial, tareas
programadas, reinicio tras caída y avisos. Todo sin servidor de Minecraft ni
red: lo que haría falta de ellos se sustituye con mock.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from config import DEFAULT_SERVERS_PATH
from services import automation, backups, clone, history, notify, player_stats, scheduler, server_control


def make_modpack(name: str, world: str = "world") -> Path:
    server = DEFAULT_SERVERS_PATH / name
    shutil.rmtree(server, ignore_errors=True)
    (server / "mods").mkdir(parents=True)
    (server / "mods" / "a.jar").write_bytes(b"jar")
    (server / "logs").mkdir()
    (server / "logs" / "latest.log").write_text("log")
    (server / "server.properties").write_text(f"level-name={world}\nmotd=Hola\n")
    (server / "run.sh").write_text("#!/bin/bash\n")
    (server / world / "region").mkdir(parents=True)
    (server / world / "level.dat").write_bytes(b"level-1")
    (server / world / "region" / "r.0.0.mca").write_bytes(b"region-1")
    (server / world / "session.lock").write_bytes(b"lock")
    (server / (world + "_nether")).mkdir()
    (server / (world + "_nether") / "n.dat").write_bytes(b"nether")
    return server


class BackupsTest(unittest.TestCase):
    def setUp(self):
        self.name = "bk" + str(time.time_ns())
        self.server = make_modpack(self.name)
        self.addCleanup(shutil.rmtree, self.server, True)
        self.addCleanup(shutil.rmtree, backups.backup_dir(self.name), True)

    def test_backup_contains_world_and_dimensions_but_not_the_lock(self):
        result = backups.create_backup(self.name, "manual")
        with zipfile.ZipFile(backups.backup_dir(self.name) / result["name"]) as zf:
            names = set(zf.namelist())
        self.assertIn("world/level.dat", names)
        self.assertIn("world/region/r.0.0.mca", names)
        self.assertIn("world_nether/n.dat", names)
        self.assertNotIn("world/session.lock", names)
        self.assertFalse(any(n.startswith("mods") for n in names))
        listed = backups.list_backups(self.name)
        self.assertEqual([b["reason"] for b in listed], ["manual"])

    def test_only_automatic_backups_are_pruned(self):
        folder = backups.backup_dir(self.name)
        folder.mkdir(parents=True)
        for stamp, reason in (("20260101-000000", "manual"), ("20260102-000000", "auto"),
                              ("20260103-000000", "task"), ("20260104-000000", "auto"),
                              ("20260105-000000", "safety")):
            (folder / f"world__{stamp}__{reason}.zip").write_bytes(b"zip")
        self.assertEqual(backups.prune(self.name, keep=2), 1)
        left = sorted(p.name for p in folder.iterdir())
        self.assertNotIn("world__20260102-000000__auto.zip", left)
        self.assertEqual(len(left), 4)
        self.assertEqual(backups.last_backup_time(self.name, reasons=("auto",)),
                         datetime(2026, 1, 4).timestamp())

    def test_restore_replaces_the_world_and_keeps_a_safety_copy(self):
        first = backups.create_backup(self.name, "manual")["name"]
        (self.server / "world" / "level.dat").write_bytes(b"level-2")
        (self.server / "world" / "new.dat").write_bytes(b"new")
        result = backups.restore_backup(self.name, first)
        self.assertEqual((self.server / "world" / "level.dat").read_bytes(), b"level-1")
        self.assertFalse((self.server / "world" / "new.dat").exists())
        self.assertTrue(result["safety_backup"].endswith("__safety.zip"))
        self.assertFalse(any(p.name.startswith(".restore-") for p in self.server.iterdir()))

    def test_restore_refused_while_that_server_runs(self):
        name = backups.create_backup(self.name, "manual")["name"]
        with mock.patch.object(server_control, "running_modpack", return_value=self.name):
            with self.assertRaises(HTTPException) as ctx:
                backups.restore_backup(self.name, name)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_bad_backup_names_are_rejected(self):
        for bad in ("../x.zip", "world__2024__manual.zip", "nada.zip"):
            with self.assertRaises(HTTPException):
                backups.backup_file(self.name, bad)

    def test_running_server_world_is_frozen_while_copying(self):
        sent = []
        with mock.patch.object(server_control, "running_modpack", return_value=self.name), \
                mock.patch.object(server_control.proc_module, "mc_ready", True), \
                mock.patch.object(server_control, "send_command", side_effect=sent.append), \
                mock.patch.object(server_control.proc_module, "expect_line") as expect:
            expect.return_value.wait.return_value = True
            backups.create_backup(self.name, "manual")
        self.assertEqual(sent, ["save-off", "save-all flush", "save-on"])


class CloneTest(unittest.TestCase):
    def setUp(self):
        self.name = "cl" + str(time.time_ns())
        self.server = make_modpack(self.name)
        self.addCleanup(shutil.rmtree, self.server, True)

    def test_clone_without_world(self):
        clone.clone_modpack(self.name, self.name + "_b", include_world=False)
        target = DEFAULT_SERVERS_PATH / (self.name + "_b")
        self.addCleanup(shutil.rmtree, target, True)
        self.assertTrue((target / "mods" / "a.jar").exists())
        self.assertTrue((target / "server.properties").exists())
        self.assertFalse((target / "world").exists())
        self.assertFalse((target / "logs").exists())

    def test_clone_with_world_skips_the_lock(self):
        clone.clone_modpack(self.name, self.name + "_c", include_world=True)
        target = DEFAULT_SERVERS_PATH / (self.name + "_c")
        self.addCleanup(shutil.rmtree, target, True)
        self.assertTrue((target / "world" / "level.dat").exists())
        self.assertTrue((target / "world_nether" / "n.dat").exists())
        self.assertFalse((target / "world" / "session.lock").exists())

    def test_invalid_or_taken_names(self):
        for bad in ("con espacios", "../fuera", self.name):
            with self.assertRaises(HTTPException):
                clone.clone_modpack(self.name, bad, include_world=False)
        self.assertFalse(any(p.name.startswith(".clone-") for p in DEFAULT_SERVERS_PATH.iterdir()))


class PlayerStatsTest(unittest.TestCase):
    def test_reads_modern_stats_and_names(self):
        name = "ps" + str(time.time_ns())
        server = make_modpack(name)
        self.addCleanup(shutil.rmtree, server, True)
        uuid = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
        (server / "usercache.json").write_text(json.dumps([{"name": "Notch", "uuid": uuid}]))
        (server / "world" / "stats").mkdir()
        (server / "world" / "stats" / (uuid + ".json")).write_text(json.dumps({"stats": {
            "minecraft:custom": {
                "minecraft:play_time": 72000, "minecraft:deaths": 3, "minecraft:mob_kills": 10,
                "minecraft:walk_one_cm": 150000, "minecraft:sprint_one_cm": 50000, "minecraft:fall_one_cm": 999999,
            },
            "minecraft:mined": {"minecraft:stone": 40, "minecraft:dirt": 2},
        }}))
        data = player_stats.player_stats(name)
        self.assertEqual(len(data["players"]), 1)
        player = data["players"][0]
        self.assertEqual(player["name"], "Notch")
        self.assertEqual(player["play_seconds"], 3600)
        self.assertEqual(player["deaths"], 3)
        self.assertEqual(player["blocks_mined"], 42)
        self.assertEqual(player["distance_km"], 2.0)

    def test_old_format_and_no_stats(self):
        name = "po" + str(time.time_ns())
        server = make_modpack(name)
        self.addCleanup(shutil.rmtree, server, True)
        self.assertEqual(player_stats.player_stats(name)["players"], [])
        (server / "world" / "stats").mkdir()
        (server / "world" / "stats" / "abc.json").write_text(json.dumps({
            "stat.playOneMinute": 1200, "stat.deaths": 1, "stat.mineBlock.minecraft.stone": 5,
        }))
        player = player_stats.player_stats(name)["players"][0]
        self.assertEqual((player["play_seconds"], player["deaths"], player["blocks_mined"]), (60, 1, 5))

    def test_same_player_after_online_mode_change_is_merged(self):
        from services.players import offline_uuid
        name = "pm" + str(time.time_ns())
        server = make_modpack(name)
        self.addCleanup(shutil.rmtree, server, True)
        props = server / "server.properties"
        props.write_text(props.read_text(encoding="utf-8") + "\nonline-mode=false\n", encoding="utf-8")
        premium, offline = "0fd22dbf-6e4f-49fd-a555-15cb3a744c43", offline_uuid("plushyyy")
        (server / "usercache.json").write_text(json.dumps([
            {"name": "plushyyy", "uuid": offline}, {"name": "plushyyy", "uuid": premium},
        ]))
        (server / "world" / "stats").mkdir()
        for uuid, ticks, deaths in ((premium, 1200, 1), (offline, 72000, 2)):
            (server / "world" / "stats" / (uuid + ".json")).write_text(json.dumps({"stats": {
                "minecraft:custom": {"minecraft:play_time": ticks, "minecraft:deaths": deaths},
            }}))
        players = player_stats.player_stats(name)["players"]
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]["uuid"], offline)
        self.assertEqual((players[0]["play_seconds"], players[0]["deaths"]), (3660, 3))


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(history, "HISTORY_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_query_groups_and_prune_drops_old(self):
        now = 1_000_000_000
        for minute in range(120):
            history.append("p", {"t": now - minute * 60, "tps": 20 - (minute % 2), "players": minute % 5, "ram": 1000})
        history.append("p", {"t": now - 9 * 86400, "tps": 5})
        points = history.query("p", 1, now=now)
        self.assertTrue(0 < len(points) <= history.MAX_POINTS)
        self.assertTrue(all(19 <= p["tps"] <= 20 for p in points))
        history.prune("p", now=now)
        self.assertEqual(len(history._read("p", 0)), 120)


class AutomationSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(automation, "AUTOMATION_FILE", Path(self.tmp.name) / "automation.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_and_clamping(self):
        self.assertTrue(automation.load()["auto_restart"]["enabled"])
        saved = automation.save_settings(backups={"enabled": True, "interval_hours": 999, "keep": 0})
        self.assertEqual(saved["backups"], {"enabled": True, "interval_hours": 168, "keep": 1})

    def test_task_validation(self):
        task = automation.save_task({"kind": "restart", "time": "05:00", "days": [0, 6], "warn_minutes": 5})
        self.assertEqual(automation.load()["tasks"][0]["id"], task["id"])
        for bad in (
            {"kind": "restart", "time": "25:00", "days": [1]},
            {"kind": "restart", "time": "05:00", "days": []},
            {"kind": "command", "time": "05:00", "days": [1], "command": "say a\nop yo"},
            {"kind": "start", "time": "05:00", "days": [1], "modpack": "../x"},
            {"kind": "borrar-todo", "time": "05:00", "days": [1]},
        ):
            with self.assertRaises(ValueError):
                automation.save_task(bad)
        self.assertTrue(automation.delete_task(task["id"]))
        self.assertEqual(automation.load()["tasks"], [])


class SchedulerTest(unittest.TestCase):
    def test_warnings_then_action(self):
        task = {"id": "t", "enabled": True, "kind": "restart", "time": "05:00", "days": [0], "warn_minutes": 5}
        monday = datetime(2026, 11, 9)  # lunes
        self.assertEqual([m for m, _ in scheduler.due_phases(task, monday.replace(hour=4, minute=55))], [5])
        self.assertEqual([m for m, _ in scheduler.due_phases(task, monday.replace(hour=4, minute=59))], [1])
        self.assertEqual([m for m, _ in scheduler.due_phases(task, monday.replace(hour=5, minute=0))], [0])
        self.assertEqual(scheduler.due_phases(task, monday.replace(hour=5, minute=1)), [])
        tuesday = datetime(2026, 11, 10, 5, 0)
        self.assertEqual(scheduler.due_phases(task, tuesday), [])
        self.assertEqual(scheduler.due_phases({**task, "enabled": False}, monday.replace(hour=5)), [])

    def test_warning_crossing_midnight_uses_the_action_day(self):
        task = {"id": "t", "enabled": True, "kind": "stop", "time": "00:02", "days": [1], "warn_minutes": 5}
        monday_night = datetime(2026, 11, 9, 23, 57)  # el aviso es el lunes; la parada, el martes
        self.assertEqual([m for m, _ in scheduler.due_phases(task, monday_night)], [5])

    def test_each_phase_runs_once(self):
        task = {"id": "t2", "enabled": True, "kind": "command", "time": "05:00", "days": [0], "command": "say hola",
                "warn_minutes": 0, "modpack": ""}
        with mock.patch.object(scheduler.automation, "load", return_value={"tasks": [task]}), \
                mock.patch.object(scheduler, "run_task_in_background") as run:
            moment = datetime(2026, 11, 9, 5, 0, 10)
            scheduler._check_tasks(moment)
            scheduler._check_tasks(moment.replace(second=40))
        self.assertEqual(run.call_count, 1)


class CrashRestartTest(unittest.TestCase):
    def setUp(self):
        server_control._crash_history.clear()
        self.addCleanup(server_control._crash_history.clear)
        patcher = mock.patch.object(server_control, "notify")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(server_control, "deployer_line")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _settings(self, enabled=True, attempts=2):
        return {"auto_restart": {"enabled": enabled, "max_attempts": attempts, "window_minutes": 10},
                "backups": {}, "tasks": []}

    def test_restarts_until_the_limit(self):
        with mock.patch.object(automation, "load", return_value=self._settings()), \
                mock.patch.object(server_control, "_restart_later") as later:
            for _ in range(3):
                server_control.on_exit("pack", crashed=True, eula_accepted=False, was_ready=True, uptime_seconds=600)
        self.assertEqual(later.call_count, 2)
        self.assertIn("no lo vuelvo a arrancar", self.notify.call_args[0][1])

    def test_normal_stop_and_eula(self):
        with mock.patch.object(server_control, "_restart_later") as later:
            server_control.on_exit("pack", crashed=False, eula_accepted=False, was_ready=True, uptime_seconds=5)
            self.assertEqual(self.notify.call_args[0][0], "stopped")
            later.assert_not_called()
            server_control.on_exit("pack", crashed=False, eula_accepted=True, was_ready=False, uptime_seconds=5)
            later.assert_called_once()

    def test_disabled_does_not_restart(self):
        with mock.patch.object(automation, "load", return_value=self._settings(enabled=False)), \
                mock.patch.object(server_control, "_restart_later") as later:
            server_control.on_exit("pack", crashed=True, eula_accepted=False, was_ready=False, uptime_seconds=5)
        later.assert_not_called()
        self.assertEqual(self.notify.call_args[0][0], "crash")

    def test_join_and_leave_lines(self):
        server_control.on_line("pack", "[12:00:00] [Server thread/INFO]: Steve joined the game")
        self.assertEqual(self.notify.call_args[0][0], "join")
        server_control.on_line("pack", "[12:00:00] [Server thread/INFO]: <Steve> Steve joined the game")
        self.assertEqual(self.notify.call_count, 1)


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / ".env"
        patcher = mock.patch.object(notify, "_ENV_PATH", self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in notify.ENV_KEYS:
            patcher = mock.patch.dict(os.environ, {key: ""})
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_nothing_configured_sends_nothing(self):
        self.env.write_text("APP_USERNAME=admin\n")
        with mock.patch.object(notify, "_queue") as q:
            notify.notify("ready", "hola")
        q.put_nowait.assert_not_called()

    def test_events_filter_and_none(self):
        self.env.write_text("TELEGRAM_BOT_TOKEN=1:abc\nTELEGRAM_CHAT_ID=42\nNOTIFY_EVENTS=crash\n")
        with mock.patch.object(notify, "_queue") as q:
            notify.notify("ready", "no")
            notify.notify("crash", "sí")
        q.put_nowait.assert_called_once_with("sí")
        self.env.write_text("TELEGRAM_BOT_TOKEN=1:abc\nTELEGRAM_CHAT_ID=42\nNOTIFY_EVENTS=none\n")
        self.assertEqual(notify.load_settings()["events"], [])

    def test_send_now_reports_each_channel(self):
        settings = {"telegram_token": "1:abc", "telegram_chat_id": "42",
                    "discord_webhook": "https://discord.com/api/webhooks/1/x"}
        with mock.patch.object(notify, "_post_json") as post:
            self.assertEqual(notify.send_now(settings, "hola"), {"telegram": "ok", "discord": "ok"})
        self.assertIn("api.telegram.org/bot1:abc/sendMessage", post.call_args_list[0][0][0])
        self.assertEqual(post.call_args_list[0][0][1]["chat_id"], "42")

    def test_discord_webhook_must_be_discord(self):
        self.assertTrue(notify.valid_discord_webhook("https://discord.com/api/webhooks/1/abc"))
        for bad in ("http://discord.com/api/webhooks/1/a", "https://evil.example/api/webhooks/1/a",
                    "https://discord.com.evil.example/api/webhooks/1"):
            self.assertFalse(notify.valid_discord_webhook(bad))

    def test_detect_chat_uses_the_last_message(self):
        body = json.dumps({"ok": True, "result": [
            {"message": {"chat": {"id": 1, "first_name": "Viejo"}}},
            {"message": {"chat": {"id": 99, "first_name": "Pablo"}}},
        ]}).encode()
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = body
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=fake):
            self.assertEqual(notify.detect_telegram_chat("1:abc"), {"chat_id": "99", "name": "Pablo"})


class SetupEnvTest(unittest.TestCase):
    def test_rerunning_setup_keeps_keys_it_does_not_ask(self):
        import setup
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = Path(tmp.name) / ".env"
        env.write_text("APP_USERNAME=viejo\nJWT_SECRET=abc\nDISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1/x\n"
                       "NOTIFY_EVENTS=crash\n")
        with mock.patch.object(setup, "ENV_FILE", env):
            text = setup.generate_env("admin", None, "hash", "", "", False, 300, "1:abc", "42")
        self.assertIn("APP_USERNAME=admin\n", text)
        self.assertIn("JWT_SECRET=abc\n", text)
        self.assertIn("TELEGRAM_CHAT_ID=42\n", text)
        self.assertIn("DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1/x\n", text)
        self.assertIn("NOTIFY_EVENTS=crash\n", text)
        self.assertEqual(text.count("APP_USERNAME="), 1)


class InstallNotifyTest(unittest.TestCase):
    def test_only_final_event_notifies(self):
        with mock.patch.object(notify, "notify") as send:
            notify.notify_install_result({"type": "log", "message": "x"}, "ATM9")
            send.assert_not_called()
            notify.notify_install_result({"type": "done", "success": True}, "ATM9")
            notify.notify_install_result({"type": "done", "success": False, "detail": "sin red"}, "ATM9")
        self.assertEqual([c.args[0] for c in send.call_args_list], ["install", "install"])
        self.assertIn("ATM9", send.call_args_list[0].args[1])
        self.assertIn("sin red", send.call_args_list[1].args[1])


if __name__ == "__main__":
    unittest.main()
