"""
Idiomas del panel (services/i18n.py, static/i18n/en.json, static/js/i18n.js).

Además de probar la traducción, vigila el mapa: que sea JSON válido sin
claves repetidas, que cada traducción tenga los mismos huecos {x} y etiquetas
que su frase, que todo t('…') del JavaScript tenga traducción y que no quede
ninguna frase del HTML sin traducir.
"""
import json
import os
import re
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from services import i18n
from services.frontend import STATIC_DIR, _expand, render_index

EN_JSON = STATIC_DIR / "i18n" / "en.json"

# Desde la fase 2 todo el HTML está traducido: una frase nueva sin su
# traducción en en.json hace fallar test_whole_page_translated.

TABLE = {
    "Guardar": "Save",
    "Usuario": "Username",
    "Buscar mod": "Search mod",
    "Los cambios <strong>no se aplican</strong> al momento.": "Changes <strong>don't apply</strong> right away.",
    "Mira tu {canal}": "Check your {canal}",
}


def fake_request(cookie=None, accept="") -> Any:
    return SimpleNamespace(
        cookies={i18n.COOKIE_NAME: cookie} if cookie else {},
        headers={"accept-language": accept},
    )


class TranslateHtmlTests(unittest.TestCase):
    def translate(self, html, missing=None):
        table = {i18n.normalize(k): v for k, v in TABLE.items()}
        return i18n.translate_html(html, "en", missing=missing, table=table)

    def test_text_and_attributes(self):
        html = '<label>  Usuario </label><input placeholder="Buscar mod" title="Guardar" value="Guardar">'
        self.assertEqual(
            self.translate(html),
            '<label>  Username </label><input placeholder="Search mod" title="Save" value="Guardar">',
        )

    def test_phrase_with_tags_across_lines(self):
        html = "<div>Los cambios <strong>no se\n      aplican</strong> al momento.</div>"
        missing = []
        self.assertEqual(self.translate(html, missing), "<div>Changes <strong>don't apply</strong> right away.</div>")
        self.assertEqual(missing, [])

    def test_missing_stays_in_spanish_and_is_reported(self):
        missing = []
        html = "<p>Frase nueva</p><span>42 %</span><button>Guardar</button>"
        self.assertEqual(self.translate(html, missing), "<p>Frase nueva</p><span>42 %</span><button>Save</button>")
        self.assertEqual(missing, ["Frase nueva"])

    def test_comments_and_scripts_untouched(self):
        html = '<!-- Guardar --><script src="x.js">Guardar</script><style>/* Guardar */</style>'
        self.assertEqual(self.translate(html), html)

    def test_spanish_is_untouched(self):
        html = "<button>Guardar</button>"
        self.assertEqual(i18n.translate_html(html, "es"), html)


class TFunctionAndLangTests(unittest.TestCase):
    def test_t_fills_params_and_falls_back(self):
        with mock.patch.object(i18n, "load", return_value={"Mira tu {canal}": "Check your {canal}"}):
            self.assertEqual(i18n.t("Mira tu {canal}", "en", canal="Telegram"), "Check your Telegram")
            self.assertEqual(i18n.t("Sin traducir", "en"), "Sin traducir")

    def test_request_lang_precedence(self):
        with mock.patch.dict(os.environ, {"APP_LANGUAGE": ""}):
            self.assertEqual(i18n.request_lang(fake_request()), "es")
            self.assertEqual(i18n.request_lang(fake_request(accept="en-GB,en;q=0.9")), "en")
            self.assertEqual(i18n.request_lang(fake_request(accept="fr-FR,en;q=0.5,es;q=0.8")), "es")
            self.assertEqual(i18n.request_lang(fake_request(cookie="es", accept="en")), "es")
            self.assertEqual(i18n.request_lang(fake_request(cookie="xx", accept="en")), "en")
        with mock.patch.dict(os.environ, {"APP_LANGUAGE": "en"}):
            self.assertEqual(i18n.request_lang(fake_request(accept="es-ES")), "en")
            self.assertEqual(i18n.request_lang(fake_request(cookie="es")), "es")


class EnJsonTests(unittest.TestCase):
    def setUp(self):
        def no_duplicates(pairs):
            keys = [k for k, _ in pairs]
            dupes = {k for k in keys if keys.count(k) > 1}
            self.assertFalse(dupes, f"Claves repetidas en en.json: {dupes}")
            return dict(pairs)

        self.raw = json.loads(EN_JSON.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
        self.phrases = {k: v for k, v in self.raw.items() if not k.startswith("//")}

    def test_values_and_placeholders(self):
        for key, value in self.phrases.items():
            self.assertIsInstance(value, str, key)
            self.assertTrue(value.strip(), f"Traducción vacía: {key}")
            self.assertEqual(
                sorted(re.findall(r"\{(\w+)\}", key)), sorted(re.findall(r"\{(\w+)\}", value)),
                f"Huecos distintos en: {key}",
            )
            self.assertEqual(
                re.findall(r"</?\w+", key), re.findall(r"</?\w+", value), f"Etiquetas distintas en: {key}"
            )

    def test_every_js_literal_has_translation(self):
        table = i18n.load("en")
        missing = []
        for path in sorted((STATIC_DIR / "js").glob("*.js")):
            # Sin las líneas de comentario (los ejemplos de i18n.js).
            source = "\n".join(
                line for line in path.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("//")
            )
            for match in re.finditer(r"\bt\('((?:[^'\\]|\\.)+)'", source):
                phrase = i18n.normalize(match.group(1).replace("\\'", "'"))
                if phrase not in table:
                    missing.append(f"{path.name}: {phrase}")
        self.assertEqual(missing, [])

    def test_constants_texts_translated(self):
        # Configuración → Constantes: las descripciones y categorías vienen de
        # app_constants.py y el panel las pasa por t() al pintarlas.
        import app_constants
        table = i18n.load("en")
        texts = set(app_constants.DESCRIPTIONS.values()) | set(app_constants.CATEGORIES.values())
        missing = sorted(t for t in texts if i18n.normalize(t) not in table)
        self.assertEqual(missing, [])

    def test_whole_page_translated(self):
        self.assertEqual(i18n.untranslated(render_index(), "en"), [])

    def test_every_partial_translated(self):
        # También los trozos con parámetros {{x}} (se rellenan con algo neutro).
        for path in sorted((STATIC_DIR / "partials").rglob("*.html")):
            source = path.read_text(encoding="utf-8")
            source = re.sub(r"\{\{[\w-]+\}\}", "x", source)
            html = _expand(source, 0)
            self.assertEqual(i18n.untranslated(html, "en"), [], path.name)


class IndexRouteTests(unittest.TestCase):
    def render(self, **kwargs):
        from routes import system
        with mock.patch.dict(os.environ, {"APP_LANGUAGE": ""}):
            return bytes(system.index(fake_request(**kwargs)).body).decode("utf-8")

    def test_english_page(self):
        html = self.render(cookie="en")
        self.assertIn('<html lang="en">', html)
        self.assertIn('<meta name="app-lang" content="en">', html)
        self.assertIn(">Sign in<", html)
        self.assertLess(html.index('src="/i18n/en.js?v='), html.index('src="/static/js/i18n.js?v='))
        self.assertLess(html.index('src="/static/js/i18n.js?v='), html.index('src="/static/js/utils.js?v='))

    def test_spanish_page_has_no_dictionary(self):
        html = self.render(cookie="es")
        self.assertIn('<html lang="es">', html)
        self.assertIn(">Entrar<", html)
        self.assertNotIn("/i18n/", html)

    def test_dictionary_script(self):
        from routes import system
        body = bytes(system.i18n_script("en").body).decode("utf-8")
        self.assertTrue(body.startswith("window.I18N_DICT = {"))
        self.assertIn('"Entrar": "Sign in"', body)
        self.assertNotIn('"//', body)


if __name__ == "__main__":
    unittest.main()
