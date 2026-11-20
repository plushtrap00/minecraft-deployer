"""
Secretos de solo escritura en Configuración (routes/config_admin.py): los GET
nunca devuelven JWT_SECRET, la API key de CurseForge, el token de Telegram ni
el webhook de Discord; al guardar, vacío conserva el que hay y `clear` lo quita.
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from dotenv import dotenv_values
from fastapi import HTTPException, Request

from routes import config_admin
from services import auto_update, notify

JWT = "a" * 64
CF_KEY = "cf-secret-key"
TG_TOKEN = "123:secret-token"
WEBHOOK = "https://discord.com/api/webhooks/1/secret"
# _require_admin va sustituido: la petición no se mira.
REQ = cast(Request, mock.Mock())


def body_json(response) -> dict:
    return json.loads(response.body)


class SecretsTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Path(tmp.name) / ".env"
        self.env.write_text(
            f"APP_USERNAME=admin\nJWT_SECRET={JWT}\nCURSEFORGE_API_KEY={CF_KEY}\n"
            f"MC_DOMAIN=mc.example.org\nTELEGRAM_BOT_TOKEN={TG_TOKEN}\nTELEGRAM_CHAT_ID=42\n"
            f"DISCORD_WEBHOOK_URL={WEBHOOK}\nNOTIFY_EVENTS=crash\n"
        )
        for target, attr, value in (
            (config_admin, "_ENV_PATH", self.env),
            (notify, "_ENV_PATH", self.env),
            (config_admin, "_require_admin", lambda _request: None),
            (auto_update, "mark_restart_pending", lambda: None),
        ):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {key: "" for key in notify.ENV_KEYS})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stored(self) -> dict:
        return dotenv_values(self.env)


class EnvSecretsTests(SecretsTestBase):
    def save(self, values: dict, clear=None):
        body = config_admin.EnvUpdateBody(values=values, clear=clear or [])
        return body_json(asyncio.run(config_admin.update_env(REQ, body)))

    def form_values(self, **overrides) -> dict:
        """Lo que manda el formulario: los secretos siempre vacíos."""
        values = {"APP_USERNAME": "admin", "JWT_SECRET": "", "CURSEFORGE_API_KEY": "", "MC_DOMAIN": "mc.example.org"}
        values.update(overrides)
        return values

    def test_get_never_returns_secrets(self):
        data = body_json(config_admin.get_env(REQ))
        raw = json.dumps(data)
        self.assertNotIn(JWT, raw)
        self.assertNotIn(CF_KEY, raw)
        self.assertNotIn("JWT_SECRET", data)
        self.assertEqual(data["secrets_set"], {"CURSEFORGE_API_KEY": True, "JWT_SECRET": True})
        self.assertEqual(data["MC_DOMAIN"], "mc.example.org")

    def test_empty_secret_keeps_current_and_is_no_change(self):
        self.assertEqual(self.save(self.form_values()), {"success": True, "changed": False})
        self.assertEqual(self.stored()["JWT_SECRET"], JWT)
        self.assertEqual(self.stored()["CURSEFORGE_API_KEY"], CF_KEY)

    def test_other_field_saved_without_touching_secrets(self):
        self.assertTrue(self.save(self.form_values(MC_DOMAIN="otro.example.org"))["changed"])
        self.assertEqual(self.stored()["MC_DOMAIN"], "otro.example.org")
        self.assertEqual(self.stored()["JWT_SECRET"], JWT)
        self.assertEqual(self.stored()["CURSEFORGE_API_KEY"], CF_KEY)

    def test_new_secret_replaces(self):
        self.assertTrue(self.save(self.form_values(CURSEFORGE_API_KEY="nueva"))["changed"])
        self.assertEqual(self.stored()["CURSEFORGE_API_KEY"], "nueva")

    def test_clear_removes_api_key_but_never_jwt(self):
        self.assertTrue(self.save(self.form_values(), clear=["CURSEFORGE_API_KEY", "JWT_SECRET"])["changed"])
        self.assertEqual(self.stored()["CURSEFORGE_API_KEY"], "")
        self.assertEqual(self.stored()["JWT_SECRET"], JWT)
        self.assertFalse(body_json(config_admin.get_env(REQ))["secrets_set"]["CURSEFORGE_API_KEY"])

    def test_newline_in_new_secret_rejected(self):
        with self.assertRaises(HTTPException):
            self.save(self.form_values(CURSEFORGE_API_KEY="a\nAPP_PASSWORD_HASH=x"))


class NotifySecretsTests(SecretsTestBase):
    def body(self, **fields):
        base = {"telegram_token": "", "telegram_chat_id": "42", "discord_webhook": "", "events": ["crash"]}
        base.update(fields)
        return config_admin.NotificationsBody(**base)

    def save(self, **fields):
        return asyncio.run(config_admin.save_notifications(REQ, self.body(**fields)))

    def test_get_never_returns_secrets(self):
        data = body_json(config_admin.get_notifications(REQ))
        raw = json.dumps(data)
        self.assertNotIn(TG_TOKEN, raw)
        self.assertNotIn(WEBHOOK, raw)
        self.assertEqual(data["secrets_set"], {"telegram_token": True, "discord_webhook": True})
        self.assertEqual(data["telegram_chat_id"], "42")

    def test_empty_keeps_and_clear_removes(self):
        self.save()
        self.assertEqual(self.stored()["TELEGRAM_BOT_TOKEN"], TG_TOKEN)
        self.assertEqual(self.stored()["DISCORD_WEBHOOK_URL"], WEBHOOK)

        self.save(clear=["discord_webhook"])
        self.assertEqual(self.stored()["DISCORD_WEBHOOK_URL"], "")
        self.assertEqual(self.stored()["TELEGRAM_BOT_TOKEN"], TG_TOKEN)

        self.save(telegram_chat_id="", clear=["telegram_token"])
        self.assertEqual(self.stored()["TELEGRAM_BOT_TOKEN"], "")
        self.assertEqual(self.stored()["TELEGRAM_CHAT_ID"], "")

    def test_clearing_token_but_keeping_chat_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.save(clear=["telegram_token"])
        self.assertEqual(self.stored()["TELEGRAM_BOT_TOKEN"], TG_TOKEN)

    def test_test_message_and_detect_use_stored_secrets(self):
        with mock.patch.object(notify, "send_now", return_value={"telegram": "ok", "discord": "ok"}) as send:
            asyncio.run(config_admin.test_notifications(REQ, self.body()))
        sent = send.call_args[0][0]
        self.assertEqual(sent["telegram_token"], TG_TOKEN)
        self.assertEqual(sent["discord_webhook"], WEBHOOK)

        with mock.patch.object(notify, "detect_telegram_chat", return_value={"chat_id": "42"}) as detect:
            asyncio.run(config_admin.detect_chat(REQ, config_admin.DetectChatBody()))
        detect.assert_called_once_with(TG_TOKEN)


if __name__ == "__main__":
    unittest.main()
