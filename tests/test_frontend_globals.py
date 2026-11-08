"""
Los scripts de static/js se cargan con <script> normales y comparten el ámbito
global: si dos archivos declaran la misma función o variable de primer nivel,
el que se carga después pisa al otro sin avisar. Este test lo detecta, y
comprueba que index.html carga todos los scripts. También que la página
montada a partir de static/partials/ sale completa y coherente.
"""
import re
import unittest
from collections import defaultdict
from pathlib import Path

from services.frontend import render_index

STATIC = Path(__file__).resolve().parent.parent / "static"
# Solo declaraciones en la columna 0: lo que está dentro de funciones va sangrado.
TOP_LEVEL_RE = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^(?:var|let|const)\s+([A-Za-z_$][\w$]*)", re.M)


class FrontendGlobalsTest(unittest.TestCase):
    def test_no_duplicate_top_level_names(self):
        seen = defaultdict(list)
        for path in sorted((STATIC / "js").glob("*.js")):
            for match in TOP_LEVEL_RE.finditer(path.read_text(encoding="utf-8")):
                seen[match.group(1) or match.group(2)].append(path.name)
        duplicates = {name: files for name, files in seen.items() if len(files) > 1}
        self.assertEqual(duplicates, {}, "Nombres globales declarados más de una vez")

    def test_no_local_shadows_global_function(self):
        # Un "var icon = ..." dentro de una función tapa la función global
        # icon() en toda esa función (hoisting), y cualquier icon('x') de ahí
        # revienta con "icon is not a function".
        sources = {p.name: p.read_text(encoding="utf-8") for p in (STATIC / "js").glob("*.js")}
        functions = {m.group(1) for text in sources.values()
                     for m in re.finditer(r"^function\s+([A-Za-z_$][\w$]*)", text, re.M)}
        local_re = re.compile(r"^\s+(?:var|let|const)\s+([A-Za-z_$][\w$]*)", re.M)
        shadows = sorted(f"{name}: {m.group(1)}" for name, text in sources.items()
                         for m in local_re.finditer(text) if m.group(1) in functions)
        self.assertEqual(shadows, [], "Variables locales que tapan una función global")

    def test_index_loads_every_script(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        loaded = set(re.findall(r'<script src="/static/js/([\w.-]+\.js)"', html))
        on_disk = {p.name for p in (STATIC / "js").glob("*.js")}
        self.assertEqual(on_disk - loaded, set(), "Scripts sin cargar en index.html")
        self.assertEqual(loaded - on_disk, set(), "index.html carga scripts que no existen")


    def test_rendered_page_is_complete(self):
        html = render_index()
        self.assertNotIn("<!-- include:", html)
        self.assertNotIn("{{", html)

    def test_rendered_ids_are_unique(self):
        ids = re.findall(r'\sid="([^"]+)"', render_index())
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(repeated, [], "ids repetidos en la página")

    def test_get_element_by_id_targets_exist(self):
        # Cada getElementById('x') literal tiene que apuntar a un id de la
        # página o a uno que el propio JS genera (id="x" dentro de un string).
        html_ids = set(re.findall(r'\sid="([^"]+)"', render_index()))
        js = "\n".join(p.read_text(encoding="utf-8") for p in (STATIC / "js").glob("*.js"))
        js_ids = set(re.findall(r'id="([\w-]+)"', js))
        wanted = set(re.findall(r"getElementById\('([\w-]+)'\)", js))
        missing = sorted(wanted - html_ids - js_ids)
        self.assertEqual(missing, [], "getElementById a ids que no existen")

    def test_assets_are_versioned_by_their_own_file(self):
        # La versión de cada CSS/JS sale de la fecha de su archivo: un git
        # pull sin reiniciar el panel tiene que cambiar la URL de lo cambiado.
        from routes.system import index, _asset_version
        html = index().body.decode("utf-8")
        refs = re.findall(r'(?:href|src)="/static/([^"?]+)(\?v=(\d+))?"', html)
        self.assertTrue(refs)
        for rel_path, _, version in refs:
            self.assertEqual(version, _asset_version(rel_path), rel_path)


class AchievementIconsTest(unittest.TestCase):
    def test_every_achievement_has_a_10x10_icon(self):
        appearance = (STATIC / "js" / "achievements.js").read_text(encoding="utf-8")
        block = appearance[appearance.index("var ACHIEVEMENTS = ["):]
        block = block[:block.index("];")]
        ids = re.findall(r"\{ id: '([a-z-]+)'", block)
        icons = (STATIC / "js" / "achievement_icons.js").read_text(encoding="utf-8")
        self.assertGreater(len(ids), 10)
        for achievement_id in ids:
            with self.subTest(achievement_id):
                start = icons.index("'" + achievement_id + "': {")
                art = icons[start:icons.index("palette", start)]
                rows = re.findall(r"'([^']{2,})'", art.split("rows:", 1)[1])
                self.assertEqual(len(rows), 10)
                self.assertTrue(all(len(row) == 10 for row in rows), rows)


if __name__ == "__main__":
    unittest.main()
