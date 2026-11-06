"""
Los scripts de static/js se cargan con <script> normales y comparten el ámbito
global: si dos archivos declaran la misma función o variable de primer nivel,
el que se carga después pisa al otro sin avisar. Este test lo detecta, y
comprueba que index.html carga todos los scripts.
"""
import re
import unittest
from collections import defaultdict
from pathlib import Path

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

    def test_index_loads_every_script(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        loaded = set(re.findall(r'<script src="/static/js/([\w.-]+\.js)"', html))
        on_disk = {p.name for p in (STATIC / "js").glob("*.js")}
        self.assertEqual(on_disk - loaded, set(), "Scripts sin cargar en index.html")
        self.assertEqual(loaded - on_disk, set(), "index.html carga scripts que no existen")


if __name__ == "__main__":
    unittest.main()
