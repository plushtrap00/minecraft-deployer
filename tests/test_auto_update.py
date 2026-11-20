"""
Novedades de la actualización pendiente (services/auto_update.py): qué
entradas del historial de version.py y qué commits se enseñan en el panel
antes de pulsar "Actualizar ahora".
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import auto_update, i18n


def version_file(version: str, entries: list) -> str:
    history = "\n".join(entries)
    return f'"""\nversion.py - Versión de la app.\n\nHistorial resumido:\n{history}\n- 1.x: todo lo anterior (sin numerar).\n"""\nAPP_VERSION = "{version}"\n'


ENTRY_7 = "- 2.1.7 (2026-11-20): animaciones más fluidas (barras y\n  sol/luna con transform), «iconos» ocultos."
ENTRY_6 = "- 2.1.6 (2026-11-14): respuestas animadas al guardar («Guardado»), sin diálogo."
ENTRY_5 = "- 2.1.5 (2026-11-14): estado de carga en los botones."


class ParseVersionFileTests(unittest.TestCase):
    def test_reads_version_and_joins_wrapped_lines(self):
        version, entries = auto_update.parse_version_file(version_file("2.1.7", [ENTRY_7, ENTRY_6]))
        self.assertEqual(version, "2.1.7")
        self.assertEqual([e["version"] for e in entries], ["2.1.7", "2.1.6"])
        self.assertEqual(entries[0]["date"], "2026-11-20")
        self.assertEqual(entries[0]["text"], "animaciones más fluidas (barras y sol/luna con transform), «iconos» ocultos.")

    def test_real_version_file_parses(self):
        source = (Path(__file__).resolve().parent.parent / "version.py").read_text(encoding="utf-8")
        version, entries = auto_update.parse_version_file(source)
        self.assertEqual(version, entries[0]["version"])
        self.assertTrue(all(e["text"] for e in entries))


class PendingChangesTests(unittest.TestCase):
    def test_only_newer_entries_newest_first(self):
        source = version_file("2.1.7", [ENTRY_7, ENTRY_6, ENTRY_5])
        result = auto_update.pending_changes("2.1.5", source, [
            "style: smoother animations (v2.1.7)",
            "feat: animated feedback (v2.1.6)",
        ])
        self.assertEqual(result["remote_version"], "2.1.7")
        self.assertEqual([c["version"] for c in result["changes"]], ["2.1.7", "2.1.6"])
        self.assertEqual(result["other_commits"], [])

    def test_commits_without_entry_are_listed_by_subject(self):
        source = version_file("2.1.6", [ENTRY_6, ENTRY_5])
        result = auto_update.pending_changes("2.1.5", source, [
            "docs: typo",
            "feat: animated feedback (v2.1.6)",
            "fix: bumped but forgot the entry (v2.1.9)",
        ])
        self.assertEqual([c["version"] for c in result["changes"]], ["2.1.6"])
        self.assertEqual(result["other_commits"], ["docs: typo", "fix: bumped but forgot the entry (v2.1.9)"])

    def test_versions_compare_numerically(self):
        source = version_file("2.1.10", ["- 2.1.10 (2026-12-01): diez.", "- 2.1.9 (2026-11-30): nueve."])
        result = auto_update.pending_changes("2.1.9", source, [])
        self.assertEqual([c["version"] for c in result["changes"]], ["2.1.10"])

    def test_unreadable_remote_file_falls_back_to_subjects(self):
        for source in ("", "esto no es python ("):
            result = auto_update.pending_changes("2.1.5", source, ["feat: algo (v2.1.6)"])
            self.assertIsNone(result["remote_version"])
            self.assertEqual(result["changes"], [])
            self.assertEqual(result["other_commits"], ["feat: algo (v2.1.6)"])


class TranslatedChangelogTests(unittest.TestCase):
    def test_each_change_takes_its_language(self):
        source = version_file("2.1.7", [ENTRY_7, ENTRY_6, ENTRY_5])
        changelogs = {"en": auto_update.parse_changelog(json.dumps({
            "//": "comentario", "2.1.7": "smoother\n  animations.", "2.1.5": "loading state."}))}
        status = auto_update.pending_changes("2.1.5", source, [], changelogs)
        en = auto_update.localize_status(status, "en")
        self.assertEqual([c["text"] for c in en["changes"]],
                         ["smoother animations.", "respuestas animadas al guardar («Guardado»), sin diálogo."])
        es = auto_update.localize_status(status, "es")
        self.assertEqual(es["changes"][0]["text"], "animaciones más fluidas (barras y sol/luna con transform), «iconos» ocultos.")
        self.assertNotIn("texts", en["changes"][0])
        # localize_status no toca el estado guardado.
        self.assertIn("texts", status["changes"][0])

    def test_broken_changelog_is_ignored(self):
        for source in ("", "no es json", "[1, 2]", '{"2.1.7": 5}'):
            self.assertEqual(auto_update.parse_changelog(source), {})

    def test_every_history_entry_translated_in_every_language(self):
        root = Path(__file__).resolve().parent.parent
        _, entries = auto_update.parse_version_file((root / "version.py").read_text(encoding="utf-8"))
        versions = {e["version"] for e in entries}
        for lang in i18n.LANGS:
            if lang == i18n.DEFAULT_LANG:
                continue
            path = root / auto_update.CHANGELOG_DIR / f"{lang}.json"
            table = auto_update.parse_changelog(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(versions - set(table)), [], f"Entradas sin traducir en {path.name}")
            self.assertEqual(sorted(set(table) - versions), [], f"Versiones que no están en version.py: {path.name}")


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("git"), "hace falta git")
class FetchFromRealRepoTests(unittest.TestCase):
    """Un origin con dos commits más que el clon: lo que leería el panel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        origin = self.tmp / "origin"
        origin.mkdir()
        git(origin, "init", "-q", "-b", "main")
        git(origin, "config", "user.email", "test@example.invalid")
        git(origin, "config", "user.name", "test")
        (origin / "version.py").write_text(version_file("2.1.5", [ENTRY_5]), encoding="utf-8")
        git(origin, "add", ".")
        git(origin, "commit", "-q", "-m", "feat: botones (v2.1.5)")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(origin), str(self.clone))
        (origin / "version.py").write_text(version_file("2.1.6", [ENTRY_6, ENTRY_5]), encoding="utf-8")
        changelog = origin / auto_update.CHANGELOG_DIR / "en.json"
        changelog.parent.mkdir(parents=True)
        changelog.write_text(json.dumps({"2.1.6": "animated feedback when saving."}), encoding="utf-8")
        git(origin, "add", ".")
        git(origin, "commit", "-q", "-m", "feat: animated feedback (v2.1.6)")
        (origin / "README").write_text("x", encoding="utf-8")
        git(origin, "add", ".")
        git(origin, "commit", "-q", "-m", "docs: readme")

    def test_check_stores_changes_and_apply_clears_them(self):
        saved = dict(auto_update._status)
        self.addCleanup(auto_update._status.update, saved)
        with mock.patch.object(auto_update, "_REPO_DIR", self.clone), \
                mock.patch.object(auto_update, "APP_VERSION", "2.1.5"), \
                mock.patch.object(auto_update, "_server_running", return_value=False), \
                mock.patch.object(auto_update, "is_busy", return_value=False):
            status = auto_update.check_now()
            self.assertEqual(status["commits_behind"], 2)
            self.assertEqual(status["remote_version"], "2.1.6")
            self.assertEqual([c["version"] for c in status["changes"]], ["2.1.6"])
            self.assertEqual(status["changes"][0]["text"], "respuestas animadas al guardar («Guardado»), sin diálogo.")
            self.assertEqual(status["other_commits"], ["docs: readme"])
            # El historial en inglés sale del origin: el clon aún no lo tiene.
            self.assertFalse((self.clone / auto_update.CHANGELOG_DIR).exists())
            self.assertEqual(auto_update.localize_status(status, "en")["changes"][0]["text"],
                             "animated feedback when saving.")

            auto_update.apply_update()
            status = auto_update.get_status()
            self.assertEqual(status["commits_behind"], 0)
            self.assertEqual(status["changes"], [])
            self.assertIsNone(status["remote_version"])


if __name__ == "__main__":
    unittest.main()
