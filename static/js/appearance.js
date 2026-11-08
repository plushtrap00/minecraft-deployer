// -- Apariencia ----------------------------------------------------------------
// Tema, sonidos y los detalles que dan vida al panel: logos y cabezas (con
// un dibujo propio si no se pueden descargar), estados vacíos ilustrados,
// números que cuentan hasta su valor, partículas al terminar algo y logros.
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
});

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

// -- Sonidos ---------------------------------------------------------------------
// Sintetizados con WebAudio (nada que descargar). Apagados por defecto.
var audioCtx = null;
var SOUNDS = {
  click: { notes: [[660, 0]], length: .04, volume: .025 },
  levelup: { notes: [[523, 0], [659, .08], [784, .16], [1047, .26]], length: .18, volume: .05 },
  error: { notes: [[247, 0], [185, .11]], length: .14, volume: .04 }
};

function soundsOn() {
  return readPref('sounds', 'off') === 'on';
}

function playSound(kind) {
  var sound = SOUNDS[kind];
  if (!sound || !soundsOn()) {
    return;
  }
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  } catch (e) {
    return;
  }
  var start = audioCtx.currentTime;
  sound.notes.forEach(function(note) {
    var osc = audioCtx.createOscillator();
    var gain = audioCtx.createGain();
    var at = start + note[1];
    osc.type = 'square';
    osc.frequency.value = note[0];
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(sound.volume, at + .01);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + sound.length);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(at);
    osc.stop(at + sound.length + .02);
  });
}

function applySoundToggle() {
  var track = document.getElementById('sound-toggle');
  var on = soundsOn();
  track.classList.toggle('on', on);
  track.setAttribute('aria-checked', on ? 'true' : 'false');
}

function toggleSounds() {
  writePref('sounds', soundsOn() ? 'off' : 'on');
  applySoundToggle();
  playSound('click');
}

document.getElementById('sound-toggle').addEventListener('click', toggleSounds);
document.getElementById('sound-toggle').addEventListener('keydown', function(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleSounds();
  }
});

// Un clic suave en cada botón (si los sonidos están encendidos).
document.addEventListener('click', function(event) {
  var button = event.target.closest('button');
  if (button && !button.disabled && button.id !== 'sound-toggle') {
    playSound('click');
  }
}, true);

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

// -- Dibujos de píxeles ----------------------------------------------------------
function hashString(text) {
  var hash = 2166136261;
  for (var i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

// Generador pseudoaleatorio con semilla: el mismo nombre da siempre el mismo dibujo.
function seededRandom(seed) {
  var state = seed || 1;
  return function() {
    state = Math.imul(state ^ (state >>> 15), 1 | state);
    state ^= state + Math.imul(state ^ (state >>> 7), 61 | state);
    return ((state ^ (state >>> 14)) >>> 0) / 4294967296;
  };
}

function pixelSvg(rows, palette, cls) {
  var size = rows.length;
  var rects = '';
  rows.forEach(function(row, y) {
    for (var x = 0; x < row.length; x++) {
      var color = palette[row[x]];
      if (color) {
        rects += '<rect x="' + x + '" y="' + y + '" width="1" height="1" fill="' + color + '"/>';
      }
    }
  });
  return '<svg class="' + cls + '" viewBox="0 0 ' + size + ' ' + size + '" shape-rendering="crispEdges" aria-hidden="true">' + rects + '</svg>';
}

// Bloque de 8x8 con los colores del nombre: el logo de los modpacks que no
// tienen uno propio. Simétrico y con luz arriba a la izquierda, como un
// bloque de verdad.
function packBlockSvg(name) {
  var random = seededRandom(hashString(name || '?'));
  var hue = Math.floor(random() * 360);
  var sat = 35 + Math.floor(random() * 30);
  var shades = [
    'hsl(' + hue + ',' + sat + '%,30%)',
    'hsl(' + hue + ',' + sat + '%,40%)',
    'hsl(' + hue + ',' + sat + '%,50%)',
    'hsl(' + ((hue + 40) % 360) + ',' + (sat + 15) + '%,62%)'
  ];
  // Mitad de arriba al azar y la de abajo girada 180°: queda como una
  // textura de bloque (con simetría de espejo salían caras).
  var cells = [];
  for (var y = 0; y < 4; y++) {
    cells.push([]);
    for (var x = 0; x < 8; x++) {
      var r = random();
      cells[y].push(r < .14 ? '3' : r < .45 ? '2' : r < .8 ? '1' : '0');
    }
  }
  var rows = cells.map(function(row) { return row.join(''); });
  for (var y2 = 3; y2 >= 0; y2--) {
    rows.push(cells[y2].slice().reverse().join(''));
  }
  // Borde: claro arriba e izquierda, oscuro abajo y derecha.
  rows = rows.map(function(row, y) {
    return row.split('').map(function(cell, x) {
      if (y === 0 || x === 0) {
        return 'h';
      }
      if (y === 7 || x === 7) {
        return 'd';
      }
      return cell;
    }).join('');
  });
  return pixelSvg(rows, {
    0: shades[0], 1: shades[1], 2: shades[2], 3: shades[3],
    h: 'hsl(' + hue + ',' + sat + '%,58%)', d: 'hsl(' + hue + ',' + sat + '%,22%)'
  }, 'pixel-fallback');
}

// Cara genérica de 8x8 para un jugador sin cabeza descargada: tono de piel,
// pelo y ojos salen del nombre, así cada uno se distingue de los demás.
var SKIN_TONES = ['#f2c7a5', '#e0a77e', '#c68a5f', '#9c6644', '#6e4630'];
var HAIR_TONES = ['#2b1d14', '#5a3a1e', '#a0662c', '#d8b25a', '#7b3b2b', '#3a3a46'];
var EYE_TONES = ['#3a6fd0', '#4f8a3a', '#6b4a2e', '#5b4aa8'];

function playerFaceSvg(name) {
  var random = seededRandom(hashString((name || '?').toLowerCase()));
  var skin = SKIN_TONES[Math.floor(random() * SKIN_TONES.length)];
  var hair = HAIR_TONES[Math.floor(random() * HAIR_TONES.length)];
  var eye = EYE_TONES[Math.floor(random() * EYE_TONES.length)];
  var fringe = random() < .5;
  var rows = [
    'hhhhhhhh',
    'hhhhhhhh',
    fringe ? 'hssshhhs' : 'hssssssh',
    'ssssssss',
    'swessews',
    'ssssssss',
    'sssmmsss',
    'ssssssss'
  ];
  return pixelSvg(rows, { h: hair, s: skin, w: '#ffffff', e: eye, m: 'rgba(0,0,0,.28)' }, 'pixel-fallback');
}

// Logo del modpack (server-icon.png o el de la tienda) con el bloque generado
// detrás: si la imagen no existe o falla, se queda el bloque.
function packIconHtml(pack, cls) {
  var html = '<span class="pack-icon ' + (cls || '') + '" aria-hidden="true">' + packBlockSvg(pack.name);
  if (pack.has_icon) {
    html += '<img src="/api/modpacks/' + encodeURIComponent(pack.name) + '/icon" alt="" loading="lazy" decoding="async" data-pixel-img>';
  }
  return html + '</span>';
}

// Cabeza del jugador (proxy con caché en /api/players/head) con una cara
// generada detrás por si no se puede descargar.
function headHtml(name, uuid, cls) {
  var html = '<span class="player-head ' + (cls || '') + '" aria-hidden="true">' + playerFaceSvg(name || uuid);
  if (name && /^[A-Za-z0-9_]{1,16}$/.test(name)) {
    html += '<img src="/api/players/head/' + encodeURIComponent(name)
      + (uuid ? '?uuid=' + encodeURIComponent(uuid) : '') + '" alt="" loading="lazy" decoding="async" data-pixel-img>';
  }
  return html + '</span>';
}

// load/error no suben por el DOM, pero se pueden escuchar en captura: así
// vale para todas las imágenes que se pinten con innerHTML.
document.addEventListener('load', function(event) {
  if (event.target.hasAttribute && event.target.hasAttribute('data-pixel-img')) {
    event.target.parentNode.classList.add('img-ready');
  }
}, true);
document.addEventListener('error', function(event) {
  if (event.target.hasAttribute && event.target.hasAttribute('data-pixel-img')) {
    event.target.remove();
  }
}, true);

// -- Estados vacíos ilustrados ---------------------------------------------------
var EMPTY_ART = {
  chest: {
    rows: ['............', '.oooooooooo.', '.owwwwwwwwo.', '.owdwwwwdwo.', '.owwwwwwwwo.', '.ooooggoooo.',
      '.owwwggwwwo.', '.owdwwwwdwo.', '.owwwwwwwwo.', '.owwwwwwwwo.', '.oooooooooo.', '............'],
    palette: { o: '#2b1d12', w: '#9a6a3a', d: '#6e4826', g: '#e8c04a' }
  },
  sign: {
    rows: ['............', '.oooooooooo.', '.owwwwwwwwo.', '.owddddddwo.', '.owwwwwwwwo.', '.owdddddwwo.',
      '.owwwwwwwwo.', '.oooooooooo.', '.....ow.....', '.....ow.....', '.....ow.....', '....oooo....'],
    palette: { o: '#3a2716', w: '#b98a50', d: '#7a5530' }
  },
  sapling: {
    rows: ['............', '.....ll.....', '...llLll....', '..lLlllLl...', '...llsll....', '.....s......',
      '..ll.s......', '..lLls......', '...lls......', '.....s......', '..bbbbbbbb..', '..bdbbbdbb..'],
    palette: { l: '#6fbf4f', L: '#3d7a2c', s: '#7a5530', b: '#6b4a33', d: '#4a3222' }
  },
  map: {
    rows: ['............', '.oooooooooo.', '.opplppppPo.', '.olllpppppo.', '.opllpppPpo.', '.opplprprpo.',
      '.opPppprppo.', '.opllprprpo.', '.olllpppppo.', '.opplppPppo.', '.oooooooooo.', '............'],
    palette: { o: '#5a4a2a', p: '#e8dcb8', P: '#c9b98c', l: '#7fae5a', r: '#d0453d' }
  },
  spyglass: {
    rows: ['............', '..oooo......', '.oGgggo.....', '.oGgggo.....', '.oggggo.....', '.oggggo.....',
      '..oooo......', '......hh....', '.......hh...', '........hh..', '.........hh.', '............'],
    palette: { o: '#2a2a35', g: '#8fd0e8', G: '#d6f2fb', h: '#8a5a30' }
  },
  shield: {
    rows: ['............', '.oooooooooo.', '.oSssssssso.', '.osssggssso.', '.osssggssso.', '.oggggggggo.',
      '.osssggssso.', '..ossggsso..', '..ossggsso..', '...osggso...', '....oooo....', '............'],
    palette: { o: '#2a2f3a', s: '#9aa8bc', S: '#c9d4e2', g: '#6fbf4f' }
  }
};

// emptyArt('chest', 'Título', 'Texto', '<button>…</button>', true) — el
// último parámetro lo hace más pequeño (para listas dentro de tarjetas).
function emptyArt(kind, title, text, actionHtml, compact) {
  var art = EMPTY_ART[kind] || EMPTY_ART.chest;
  return '<div class="empty-art' + (compact ? ' compact' : '') + '">'
    + pixelSvg(art.rows, art.palette, 'empty-art-pic')
    + '<div><div class="empty-art-title">' + escHtml(title) + '</div>'
    + (text ? '<div class="empty-art-text">' + escHtml(text) + '</div>' : '')
    + (actionHtml ? '<div class="empty-art-action">' + actionHtml + '</div>' : '')
    + '</div></div>';
}

// -- Números que cuentan hasta su valor ---------------------------------------
// suffixHtml va detrás tal cual (p. ej. ' <small>de 20</small>').
function animateNumber(el, value, decimals, suffixHtml) {
  var to = Number(value);
  var from = parseFloat(el.dataset.num);
  el.dataset.num = String(to);
  var suffix = suffixHtml || '';
  if (isNaN(from) || from === to || prefersReducedMotion() || document.hidden) {
    el.innerHTML = to.toFixed(decimals) + suffix;
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
    el.innerHTML = (from + (to - from) * eased).toFixed(decimals) + suffix;
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

// -- Logros ------------------------------------------------------------------------
// Pequeños hitos que se celebran una sola vez por navegador.
var ACHIEVEMENTS = [
  { id: 'first-install', name: 'Primer modpack instalado', hint: 'Instala un modpack o crea un servidor.' },
  { id: 'first-start', name: 'El servidor cobra vida', hint: 'Arranca un servidor hasta que esté listo para jugar.' },
  { id: 'first-op', name: 'Con poderes de operador', hint: 'Haz op a un jugador.' },
  { id: 'full-house', name: 'Casa llena', hint: 'Ten 5 jugadores conectados a la vez.' },
  { id: 'smooth', name: '20 TPS clavados', hint: 'Que el servidor vaya a 20 TPS con alguien jugando.' },
  { id: 'night-shift', name: 'Turno de noche', hint: 'Arranca un servidor entre la 1 y las 5 de la madrugada.' }
];

function hasAchievement(id) {
  return !!readPref('ach-' + id, '');
}

function unlockAchievement(id) {
  var achievement = ACHIEVEMENTS.filter(function(item) { return item.id === id; })[0];
  if (!achievement || hasAchievement(id)) {
    return;
  }
  writePref('ach-' + id, String(Date.now()));
  // Si no se puede guardar, no se celebra: si no, saldría en cada visita.
  if (!hasAchievement(id)) {
    return;
  }
  var stack = document.getElementById('toast');
  var toastEl = document.createElement('div');
  toastEl.className = 'toast achievement';
  toastEl.innerHTML = '<span class="achievement-icon">' + icon('trophy') + '</span>'
    + '<span><span class="achievement-kicker">¡Logro conseguido!</span>'
    + '<span class="achievement-name">' + escHtml(achievement.name) + '</span></span>';
  stack.appendChild(toastEl);
  requestAnimationFrame(function() { toastEl.classList.add('show'); });
  playSound('levelup');
  setTimeout(function() {
    toastEl.classList.remove('show');
    setTimeout(function() { toastEl.remove(); }, 300);
  }, 5000);
}

function renderAchievementList() {
  var got = ACHIEVEMENTS.filter(function(item) { return hasAchievement(item.id); }).length;
  document.getElementById('achievement-count').textContent = got + ' de ' + ACHIEVEMENTS.length;
  document.getElementById('achievement-list').innerHTML = ACHIEVEMENTS.map(function(item) {
    var unlocked = hasAchievement(item.id);
    return '<li class="achievement-row' + (unlocked ? ' unlocked' : '') + '">'
      + '<span class="achievement-icon">' + icon(unlocked ? 'trophy' : 'lock') + '</span>'
      + '<span><span class="achievement-name">' + escHtml(item.name) + '</span>'
      + '<span class="achievement-hint">' + escHtml(unlocked ? 'Conseguido' : item.hint) + '</span></span></li>';
  }).join('');
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
