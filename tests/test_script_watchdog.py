"""Script de arranque que se queda esperando una tecla tras cerrarse Minecraft."""
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from services import process
from services.server_control import disable_script_restart_loop, patch_sourced_variables


class FakeProc:
    pid = 4242

    def __init__(self, exit_on_newline=False):
        self.returncode = None
        self.killed = False
        self.exit_on_newline = exit_on_newline
        proc = self

        class Stdin(io.BytesIO):
            def flush(self):
                if proc.exit_on_newline and b"\n" in self.getvalue():
                    proc.returncode = 0

        self.stdin = Stdin()

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class ScriptWatchdogTest(unittest.TestCase):
    def setUp(self):
        self.broadcast = mock.patch.object(process, "_broadcast").start()
        mock.patch.object(process, "_kill_process_group", side_effect=lambda p: p.kill()).start()
        self.java_alive = True
        mock.patch.object(process, "find_java_descendant_pid",
                          side_effect=lambda pid: 99 if self.java_alive else None).start()
        process.mc_stop_requested = False

    def tearDown(self):
        mock.patch.stopall()
        process.mc_stop_requested = False

    def _run(self, proc):
        t = threading.Thread(target=process._script_watchdog, args=(proc, 0.01, 0.05, 0.4), daemon=True)
        t.start()
        return t

    def test_sends_enter_when_java_is_gone(self):
        proc = FakeProc(exit_on_newline=True)
        t = self._run(proc)
        time.sleep(0.05)
        self.java_alive = False  # Minecraft se cierra; el script pide una tecla
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(proc.stdin.getvalue(), b"\n")
        self.assertFalse(proc.killed)

    def test_kills_script_that_ignores_enter(self):
        proc = FakeProc()
        t = self._run(proc)
        time.sleep(0.05)
        self.java_alive = False
        t.join(3)
        self.assertTrue(proc.killed)
        self.assertEqual(proc.stdin.getvalue(), b"\n\n\n")  # como mucho 3 Intros

    def test_does_nothing_before_java_starts(self):
        # Descargas / instalador antes del primer java: no se toca.
        self.java_alive = False
        proc = FakeProc()
        t = self._run(proc)
        time.sleep(0.6)
        proc.returncode = 0
        t.join(1)
        self.assertEqual(proc.stdin.getvalue(), b"")
        self.assertFalse(proc.killed)

    def test_java_coming_back_resets(self):
        # Un script que relanza java en pocos segundos no se cierra.
        proc = FakeProc()
        t = self._run(proc)
        time.sleep(0.05)
        self.java_alive = False
        time.sleep(0.2)
        self.java_alive = True
        time.sleep(0.5)
        proc.returncode = 0
        t.join(1)
        self.assertFalse(proc.killed)

    def test_leaves_requested_stops_alone(self):
        proc = FakeProc()
        t = self._run(proc)
        time.sleep(0.05)
        process.mc_stop_requested = True
        self.java_alive = False
        time.sleep(0.6)
        proc.returncode = 0
        t.join(1)
        self.assertEqual(proc.stdin.getvalue(), b"")
        self.assertFalse(proc.killed)


class PatchSourcedVariablesTest(unittest.TestCase):
    def test_forces_both_after_source(self):
        script = b'#!/bin/bash\nsource "./variables.txt"\necho "$WAIT_FOR_USER_INPUT"\n'
        out = patch_sourced_variables(script)
        self.assertEqual(
            out,
            b'#!/bin/bash\nsource "./variables.txt"\nRESTART=false\nWAIT_FOR_USER_INPUT=false\necho "$WAIT_FOR_USER_INPUT"\n',
        )

    def test_dot_form_and_crlf(self):
        out = patch_sourced_variables(b". variables.txt\r\nrun\r\n")
        self.assertEqual(out, b". variables.txt\r\nRESTART=false\r\nWAIT_FOR_USER_INPUT=false\r\nrun\r\n")

    def test_other_scripts_untouched(self):
        script = b'#!/bin/bash\njava @user_jvm_args.txt -jar server.jar\n# source ./variables.txt en un comentario\n'
        self.assertEqual(patch_sourced_variables(script), script)


class StuckShutdownTest(unittest.TestCase):
    """«stop» desde la consola o el juego con Minecraft atascado al cerrarse."""

    def setUp(self):
        self.broadcast = mock.patch.object(process, "_broadcast").start()
        mock.patch.object(process, "_kill_process_group", side_effect=lambda p: p.kill()).start()
        mock.patch.object(process, "find_java_descendant_pid", return_value=99).start()
        self.java_alive = True
        mock.patch.object(process, "_pid_running", side_effect=lambda pid: self.java_alive).start()

    def tearDown(self):
        mock.patch.stopall()
        process.mc_stopping = False

    def test_forces_stuck_java(self):
        proc = FakeProc()
        process._force_stop_after(proc, timeout=0.3)
        self.assertTrue(proc.killed)
        self.assertIn("se fuerza el cierre", self.broadcast.call_args[0][0])

    def test_leaves_clean_shutdown_alone(self):
        proc = FakeProc()
        threading.Timer(0.1, lambda: setattr(self, "java_alive", False)).start()
        process._force_stop_after(proc, timeout=2)
        self.assertFalse(proc.killed)
        self.broadcast.assert_not_called()

    def test_mark_stopping_closes_rcon_and_metrics_skip_it(self):
        from services import server_control
        conn = mock.Mock()
        proc = FakeProc()
        with mock.patch.object(process, "mc_process", proc), mock.patch.object(process, "mc_rcon_conn", conn), \
                mock.patch.object(server_control, "read_proc_ram"), \
                mock.patch.object(server_control, "refresh_via_rcon") as via_rcon, \
                mock.patch.object(server_control, "_last_metrics_refresh", 0.0):
            process.mark_stopping()
            conn.close.assert_called_once()
            self.assertTrue(server_control.refresh_metrics())
            via_rcon.assert_not_called()


class DisableScriptRestartLoopTest(unittest.TestCase):
    # Bucle del startserver.sh de All the Mods 10 (igual en ATM9 con ATM9_RESTART).
    ATM_LOOP = (
        b'while true\ndo\n'
        b'    "${ATM10_JAVA:-java}" @user_jvm_args.txt nogui || EXIT_CODE=$?\n\n'
        b'    if [ "${ATM10_RESTART:-true}" = "false" ]; then\n        exit 0\n    fi\n\n'
        b'    echo "Restarting automatically in 10 seconds (press Ctrl + C to cancel)"\n'
        b'    sleep 10\ndone\n'
    )

    def test_atm_default_variable(self):
        out = disable_script_restart_loop(self.ATM_LOOP)
        self.assertIn(b'if [ "${ATM10_RESTART:-false}" = "false" ]; then', out)
        self.assertNotIn(b'RESTART:-true', out)

    def test_other_default_forms(self):
        self.assertEqual(disable_script_restart_loop(b'R=${ATM9_RESTART:=true}\n'), b'R=${ATM9_RESTART:=false}\n')
        self.assertEqual(disable_script_restart_loop(b'R=${RESTART-"true"}\n'), b'R=${RESTART-"false"}\n')

    def test_plain_assignment_still_patched(self):
        self.assertEqual(disable_script_restart_loop(b'RESTART="true"\n'), b'RESTART=false\n')

    def test_unrelated_defaults_untouched(self):
        script = b'J=${ATM10_JAVA:-java}\nI=${ATM10_INSTALL_ONLY:-false}\nX=${DEBUG:-true}\n'
        self.assertEqual(disable_script_restart_loop(script), script)

    @unittest.skipUnless(shutil.which("bash"), "sin bash")
    def test_patched_loop_runs_java_once(self):
        # El script parcheado de verdad: con un «java» falso que sale al
        # momento, tiene que terminar en vez de esperar 10 s y relanzarlo.
        with tempfile.TemporaryDirectory() as d:
            fake_java = os.path.join(d, "java.sh")
            with open(fake_java, "w", newline="\n") as f:
                f.write('#!/bin/sh\necho ran >> "$(dirname "$0")/runs"\n')
            os.chmod(fake_java, 0o755)
            script = os.path.join(d, "start.sh")
            with open(script, "wb") as f:
                f.write(b"#!/bin/sh\nset -eu\n" + disable_script_restart_loop(self.ATM_LOOP))
            env = {k: v for k, v in os.environ.items() if k != "ATM10_RESTART"}
            env["ATM10_JAVA"] = fake_java.replace("\\", "/")
            result = subprocess.run(["bash", script], cwd=d, env=env, capture_output=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(b"Restarting automatically", result.stdout)
            with open(os.path.join(d, "runs")) as f:
                self.assertEqual(f.read().split(), ["ran"])


if __name__ == "__main__":
    unittest.main()
