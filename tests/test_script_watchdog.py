"""Script de arranque que se queda esperando una tecla tras cerrarse Minecraft."""
import io
import threading
import time
import unittest
from unittest import mock

from services import process
from services.server_control import patch_sourced_variables


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


if __name__ == "__main__":
    unittest.main()
