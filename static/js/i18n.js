// -- Idiomas -------------------------------------------------------------------
// El panel está escrito en español; el inglés es un mapa de frases enteras
// (static/i18n/en.json) que el servidor manda como /i18n/en.js antes que este
// archivo. El HTML ya llega traducido (services/i18n.py); los textos que monta
// el JavaScript pasan por t():
//
//   showToast(t('Avisos guardados'), 'success');
//   t('Mira tu {canal}', { canal: 'Telegram' });
//
// Una frase que no está en el mapa sale en español: nunca se rompe nada.

var I18N_LANGS = [
  { id: 'es', name: 'Español (España)' },
  { id: 'en', name: 'English' }
];

function metaContent(name, fallback) {
  var meta = document.querySelector('meta[name="' + name + '"]');
  return meta ? meta.getAttribute('content') : fallback;
}

function currentLang() {
  return metaContent('app-lang', 'es');
}

function t(text, params) {
  var dict = window.I18N_DICT || {};
  var key = String(text).replace(/\s+/g, ' ').trim();
  var result = Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : text;
  if (params) {
    result = result.replace(/\{(\w+)\}/g, function(match, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match;
    });
  }
  return result;
}

// El idioma se guarda en una cookie (no en localStorage) porque es el servidor
// el que monta la página ya traducida; cambiarlo recarga.
function setLanguage(lang) {
  if (lang === currentLang()) {
    return;
  }
  document.cookie = 'mcd-lang=' + encodeURIComponent(lang) + '; path=/; max-age=31536000; SameSite=Lax';
  location.reload();
}
