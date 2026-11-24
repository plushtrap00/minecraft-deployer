"""
Huella de CurseForge (services/mod_hashes.py): una sola implementación,
compartida por la búsqueda de actualizaciones y la de dependencias.
"""
import unittest

from services import mod_dependencies, mod_updates
from services.mod_hashes import curseforge_fingerprint


class CurseForgeFingerprintTests(unittest.TestCase):
    def test_known_values(self):
        # Valores fijados con las dos implementaciones que había antes (coincidían
        # en 1.500 entradas aleatorias y 40 jars reales, uno de ellos reconocido
        # por la API de CurseForge). Cubren 0-3 bytes sobrantes tras los bloques de 4.
        self.assertEqual(curseforge_fingerprint(b""), 1540447798)
        expected = {1: 2761424046, 2: 1466336775, 3: 1035797765, 4: 479736019, 7: 2620794179}
        for n, value in expected.items():
            with self.subTest(length=n):
                self.assertEqual(curseforge_fingerprint(bytes(range(65, 65 + n))), value)

    def test_ignores_whitespace_bytes(self):
        self.assertEqual(curseforge_fingerprint(b"ho la\tmu\r\nndo"), curseforge_fingerprint(b"holamundo"))

    def test_single_implementation(self):
        self.assertIs(mod_updates.curseforge_fingerprint, curseforge_fingerprint)
        self.assertIs(mod_dependencies.curseforge_fingerprint, curseforge_fingerprint)


if __name__ == "__main__":
    unittest.main()
