"""
Métricas de la página Servidor: el navegador las pide cada 10 s (y puede
haber varias pestañas abiertas además del planificador), así que el panel
reutiliza una lectura reciente y no deja que dos comandos RCON se mezclen.
"""
import threading
import time
import unittest
from unittest import mock

from services import process as proc_module
from services import rcon, server_control


class _FakeProc:
    pid = 1234

    def poll(self):
        return None


class RefreshThrottleTest(unittest.TestCase):
    def setUp(self):
        self.conn = mock.Mock()
        self.patches = [
            mock.patch.object(proc_module, "mc_process", _FakeProc()),
            mock.patch.object(proc_module, "mc_rcon_conn", self.conn),
            mock.patch.object(proc_module, "mc_modloader", "NeoForge"),
            mock.patch.object(server_control, "refresh_via_rcon"),
            mock.patch.object(server_control, "read_proc_ram"),
            mock.patch.object(server_control, "_last_metrics_refresh", 0.0),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def test_back_to_back_requests_reuse_the_reading(self):
        self.assertTrue(server_control.refresh_metrics())
        self.assertTrue(server_control.refresh_metrics())
        self.assertEqual(server_control.refresh_via_rcon.call_count, 1)

    def test_reads_again_after_the_interval(self):
        server_control.refresh_metrics()
        server_control._last_metrics_refresh -= server_control.METRICS_MIN_INTERVAL + 0.1
        server_control.refresh_metrics()
        self.assertEqual(server_control.refresh_via_rcon.call_count, 2)

    def test_no_server_running(self):
        with mock.patch.object(proc_module, "mc_process", None):
            self.assertFalse(server_control.refresh_metrics())
        server_control.refresh_via_rcon.assert_not_called()


class RconLockTest(unittest.TestCase):
    def test_commands_from_two_threads_do_not_interleave(self):
        conn = rcon.RconConnection("127.0.0.1", 25575, "x")
        conn._sock = object()
        inside = []
        overlaps = []

        def slow_exec(command):
            if inside:
                overlaps.append(command)
            inside.append(command)
            time.sleep(0.05)
            inside.pop()
            return "ok"

        with mock.patch.object(conn, "_exec", side_effect=slow_exec):
            threads = [threading.Thread(target=conn.command, args=("list",)) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(overlaps, [])


if __name__ == "__main__":
    unittest.main()
