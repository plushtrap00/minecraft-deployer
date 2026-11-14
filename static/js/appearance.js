// -- Apariencia ----------------------------------------------------------------
// Preferencias del navegador, temas, el diálogo de Apariencia, números que
// cuentan hasta su valor, partículas al terminar algo y la frase del login.
// Los sonidos están en sounds.js, los dibujos pixelados (logos, cabezas,
// estados vacíos) en pixel_art.js y los logros en achievements.js.
// Las preferencias se guardan en este navegador (localStorage) y, si no se
// puede, simplemente no se recuerdan.

function readPref(key, fallback) {
  try {
    var value = localStorage.getItem('mcd-' + key);
    return value === null ? fallback : value;
  } catch (e) {
    return fallback;
  }
}

function writePref(key, value) {
  try {
    localStorage.setItem('mcd-' + key, value);
  } catch (e) {}
}

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// -- Temas ---------------------------------------------------------------------
// Los colores de cada tema están en themes.css; aquí solo el nombre y las
// muestras del selector (fondo, tarjeta, acento).
var THEMES = [
  { id: 'amethyst', name: 'Amatista', swatch: ['#18161c', '#221f28', '#b792f4'] },
  { id: 'surface', name: 'Superficie', swatch: ['#151a17', '#5aa043', '#6cc3ee'] },
  { id: 'nether', name: 'Nether', swatch: ['#1a1111', '#a33a2c', '#52d6c8'] },
  { id: 'end', name: 'End', swatch: ['#110f17', '#d9d59a', '#e78bd9'] }
];

function applyTheme(id) {
  if (!THEMES.some(function(theme) { return theme.id === id; })) {
    id = 'amethyst';
  }
  if (id === 'amethyst') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', id);
  }
  document.querySelectorAll('.theme-option').forEach(function(option) {
    option.setAttribute('aria-checked', option.dataset.themeId === id ? 'true' : 'false');
  });
}

function renderThemeOptions() {
  var current = readPref('theme', 'amethyst');
  document.getElementById('theme-grid').innerHTML = THEMES.map(function(theme) {
    return '<button type="button" class="theme-option lift" role="radio" data-theme-id="' + theme.id + '"'
      + ' aria-checked="' + (theme.id === current ? 'true' : 'false') + '">'
      + '<span class="theme-swatch" aria-hidden="true">'
      + theme.swatch.map(function(color) { return '<span style="background:' + color + '"></span>'; }).join('')
      + '</span><span class="theme-name">' + theme.name + '</span></button>';
  }).join('');
}

document.getElementById('theme-grid').addEventListener('click', function(event) {
  var option = event.target.closest('.theme-option');
  if (!option) {
    return;
  }
  writePref('theme', option.dataset.themeId);
  applyTheme(option.dataset.themeId);
  collectForAchievement('tourist', option.dataset.themeId, THEMES.map(function(theme) { return theme.id; }));
  var now = Date.now();
  themeChanges = themeChanges.filter(function(at) { return now - at < 30000; }).concat(now);
  if (themeChanges.length >= 10) {
    unlockAchievement('dizzy');
  }
});
var themeChanges = [];

// Flechas para moverse entre temas, como en cualquier grupo de opciones.
document.getElementById('theme-grid').addEventListener('keydown', function(event) {
  var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  if (!keys[event.key]) {
    return;
  }
  event.preventDefault();
  var options = Array.prototype.slice.call(this.querySelectorAll('.theme-option'));
  var index = options.indexOf(document.activeElement);
  var next = options[(index + keys[event.key] + options.length) % options.length];
  next.focus();
  next.click();
});

// -- Diálogo de Apariencia -----------------------------------------------------
function openAppearance() {
  renderThemeOptions();
  applySoundToggle();
  renderAchievementList();
  document.getElementById('appearance-modal').classList.add('show');
}

document.getElementById('btn-appearance').addEventListener('click', openAppearance);
document.getElementById('appearance-close').addEventListener('click', function() {
  document.getElementById('appearance-modal').classList.remove('show');
});

// -- Números que cuentan hasta su valor ---------------------------------------
// suffixHtml va detrás tal cual (p. ej. ' <small>de 20</small>').
// Cada cifra en su caja de ancho fijo (.tnum-d): la fuente de bloque no
// tiene cifras tabulares y el número bailaba al contar.
function tabularDigits(text) {
  return String(text).replace(/\d/g, '<span class="tnum-d">$&</span>');
}

function animateNumber(el, value, decimals, suffixHtml) {
  var to = Number(value);
  var from = parseFloat(el.dataset.num);
  el.dataset.num = String(to);
  var suffix = suffixHtml || '';
  if (isNaN(from) || from === to || prefersReducedMotion() || document.hidden) {
    el.innerHTML = tabularDigits(to.toFixed(decimals)) + suffix;
    return;
  }
  var started = performance.now();
  var duration = 650;
  function frame(now) {
    if (el.dataset.num !== String(to)) {
      return;
    }
    var t = Math.min(1, (now - started) / duration);
    var eased = 1 - Math.pow(1 - t, 3);
    el.innerHTML = tabularDigits((from + (to - from) * eased).toFixed(decimals)) + suffix;
    if (t < 1) {
      requestAnimationFrame(frame);
    }
  }
  requestAnimationFrame(frame);
}

// -- Celebraciones ---------------------------------------------------------------
var FX_COLORS = ['#6fbf4f', '#e8b54a', '#b792f4', '#6cc3ee', '#c97b47', '#f0646a'];

// Una lluvia de bloquecitos que salen de `anchor` (o de arriba al centro).
function celebrate(anchor) {
  playSound('levelup');
  if (prefersReducedMotion() || document.hidden) {
    return;
  }
  var layer = document.getElementById('fx-layer');
  var rect = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
  var originX = rect && rect.width ? rect.left + rect.width / 2 : window.innerWidth / 2;
  var originY = rect && rect.height ? rect.top + rect.height / 2 : 120;
  for (var i = 0; i < 34; i++) {
    var block = document.createElement('span');
    block.className = 'fx-block';
    block.style.left = originX + 'px';
    block.style.top = originY + 'px';
    block.style.background = FX_COLORS[i % FX_COLORS.length];
    var size = 6 + Math.round(Math.random() * 5);
    block.style.width = size + 'px';
    block.style.height = size + 'px';
    layer.appendChild(block);
    var dx = (Math.random() - .5) * 420;
    var dy = -120 - Math.random() * 200;
    var spin = (Math.random() - .5) * 720;
    var animation = block.animate([
      { transform: 'translate(0, 0) rotate(0deg)', opacity: 1 },
      { transform: 'translate(' + dx * .6 + 'px,' + dy + 'px) rotate(' + spin / 2 + 'deg)', opacity: 1, offset: .4 },
      { transform: 'translate(' + dx + 'px,' + (dy + 360) + 'px) rotate(' + spin + 'deg)', opacity: 0 }
    ], { duration: 1300 + Math.random() * 600, easing: 'cubic-bezier(.25,.6,.45,1)' });
    animation.onfinish = (function(el) { return function() { el.remove(); }; })(block);
  }
}

// -- Frase del login ------------------------------------------------------------
var SPLASHES = [
  '¡Ahora con más bloques!', '¡Sin creepers en el panel!', '¡Hecho en casa!', '¡20 TPS o nada!',
  '¡Que no se te olvide la whitelist!', '¡La RAM nunca es suficiente!', '¡Con cariño y Java!',
  '¡El spawn ya casi está!', '¡Haz copia del mundo!', '¡Funciona en mi servidor!', '¡Mods compatibles, casi siempre!',
  '¡Recién salido del horno!', '¡Más estable que un bloque de obsidiana!', '¡Pon una antorcha!'
];

(function pickSplash() {
  var el = document.getElementById('login-splash');
  if (el) {
    el.textContent = SPLASHES[Math.floor(Math.random() * SPLASHES.length)];
  }
})();
