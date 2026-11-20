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

// Fechas y números: en inglés, formato británico (hora de 24 h, día antes
// que el mes), que es el que menos choca viniendo del español.
var APP_LOCALE = currentLang() === 'en' ? 'en-GB' : 'es-ES';

// «a, b y c» / «a, b and c»
function joinList(items) {
  if (items.length < 2) {
    return items.join('');
  }
  return items.slice(0, -1).join(', ') + t(' y ') + items[items.length - 1];
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
  // Con sesión iniciada se guarda en la cuenta, para que salga igual en
  // cualquier dispositivo; sin sesión basta con la cookie.
  if (typeof currentUser === 'string' && currentUser) {
    fetch('/api/auth/language', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lang: lang })
    }).finally(function() { location.reload(); });
    return;
  }
  location.reload();
}
