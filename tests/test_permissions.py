"""
Roles de las cuentas (services/permissions.py y services/users.py).
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bcrypt

from services import permissions, users


class LimitedRoleTests(unittest.TestCase):
    def allowed(self, method, path):
        return permissions.allowed("limited", method, path)

    def test_other_roles_are_not_filtered_here(self):
        self.assertTrue(permissions.allowed("user", "DELETE", "/api/modpacks/pack"))
        self.assertTrue(permissions.allowed("admin", "POST", "/api/server/command"))

    def test_what_a_limited_account_can_do(self):
        for method, path in (
            ("GET", "/api/modpacks"),
            ("GET", "/api/modpacks/pack/mods"),
            ("GET", "/api/server/status"),
            ("POST", "/api/server/start"),
            ("POST", "/api/server/stop"),
            ("POST", "/api/server/restart"),
            ("POST", "/api/players/whitelist"),
            ("DELETE", "/api/players/whitelist/Steve"),
            ("POST", "/api/auth/password"),
            ("POST", "/api/auth/logout"),
            ("POST", "/api/auth/achievements"),
            # Paquete para jugadores: prepararlo y bajarlo (es lo que necesita para entrar)
            ("GET", "/api/modpacks/pack/client-pack"),
            ("POST", "/api/modpacks/pack/client-pack"),
            ("GET", "/api/modpacks/pack/client-pack/download"),
        ):
            self.assertTrue(self.allowed(method, path), (method, path))

    def test_what_a_limited_account_cannot_do(self):
        for method, path in (
            ("POST", "/api/server/command"),
            ("POST", "/api/players/op"),
            ("POST", "/api/players/ban"),
            ("DELETE", "/api/modpacks/pack"),
            ("DELETE", "/api/modpacks/pack/mods/x.jar"),
            ("POST", "/api/modpacks/pack/backups"),
            ("POST", "/api/automation/settings"),
            ("POST", "/api/modpacks/pack/mods/updates/check"),
            ("POST", "/api/modpacks/pack/mods/upload-bulk/confirm"),
            # GET que instalan cosas
            ("GET", "/api/create-server/stream"),
            ("GET", "/api/modpack-install/stream"),
            ("GET", "/api/modpacks/pack/mods/dependencies/install/stream"),
            # Descargas
            ("GET", "/api/modpacks/pack/worlds/world/download"),
            ("GET", "/api/modpacks/pack/backups/copia.zip/download"),
            ("GET", "/api/modpacks/pack/mods/download"),
            ("GET", "/api/modpacks/pack/kubejs/download"),
            ("GET", "/api/modpacks/pack/logs/latest.log/download"),
            # Algo que todavía no existe: cerrado por defecto
            ("POST", "/api/algo/nuevo"),
        ):
            self.assertFalse(self.allowed(method, path), (method, path))

    def test_allowed_routes_exist(self):
        import main
        real = {(method.upper(), path) for path, ops in main.app.openapi()["paths"].items() for method in ops}
        self.assertEqual([r for r in permissions.LIMITED_SAFE if r not in real], [])
        from services import activity
        self.assertTrue(permissions.LIMITED_ACTIONS <= set(activity.ACTIONS))

    def test_rcon_password_is_masked(self):
        props = "motd=Hola\nrcon.password=s3creto\nenable-rcon=true\n"
        masked = permissions.mask_secrets(props)
        self.assertNotIn("s3creto", masked)
        self.assertIn("rcon.password=********\n", masked)
        self.assertIn("motd=Hola\n", masked)


class StoredRoleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (
            mock.patch.object(users, "_USERS_PATH", Path(tmp.name) / "users.json"),
            mock.patch.dict("os.environ", {"APP_USERNAME": "admin",
                                           "APP_PASSWORD_HASH": bcrypt.hashpw(b"x", bcrypt.gensalt(4)).decode()}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_roles(self):
        users.create_user("ana", "contraseña1")
        users.create_user("luis", "contraseña2", role="limited")
        self.assertEqual(users.role_of("admin"), "admin")
        self.assertEqual(users.role_of("ana"), "user")
        self.assertEqual(users.role_of("luis"), "limited")
        self.assertEqual(users.authenticate("luis", "contraseña2"), "limited")
        self.assertEqual({u["username"]: u["role"] for u in users.list_users()},
                         {"admin": "admin", "ana": "user", "luis": "limited"})

        users.set_role("luis", "user")
        self.assertEqual(users.role_of("luis"), "user")
        with self.assertRaises(ValueError):
            users.set_role("ana", "admin")
        with self.assertRaises(ValueError):
            users.set_role("admin", "limited")
        with self.assertRaises(KeyError):
            users.set_role("nadie", "limited")
        with self.assertRaises(ValueError):
            users.create_user("eva", "contraseña3", role="admin")


if __name__ == "__main__":
    unittest.main()
