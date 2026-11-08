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

// -- Sonidos ---------------------------------------------------------------------
// Sintetizados con WebAudio (nada que descargar). Apagados por defecto.
// Cada sonido es una lista de piezas que suenan a la vez o seguidas:
// - tone: una nota (wave, freq; «to» para que la nota se deslice hasta ahí).
// - noise: un golpe de ruido filtrado (freq del filtro, «to» para barrerlo):
//   es lo que hace que un clic suene a madera y no a pitido.
// at = cuándo empieza (s), dur = cuánto dura (s), vol = volumen.
var audioCtx = null;
var noiseBuffer = null;
var SOUNDS = {
  // Botón normal: un toque de madera, corto y seco.
  tap: [
    { type: 'noise', freq: 2200, q: 4, at: 0, dur: .03, vol: .18 },
    { type: 'tone', wave: 'triangle', freq: 1100, to: 700, at: 0, dur: .03, vol: .025 }
  ],
  // Cambiar de sección: como pasar una página.
  nav: [
    { type: 'noise', freq: 3200, to: 900, q: 1.2, at: 0, dur: .08, vol: .1 }
  ],
  // Cerrar una ventana: un soplido hacia abajo.
  close: [
    { type: 'noise', freq: 1600, to: 350, q: 1.5, at: 0, dur: .07, vol: .09 }
  ],
  // Iniciar, instalar: tres notas que suben, como algo que se enciende.
  go: [
    { type: 'tone', wave: 'triangle', freq: 392, at: 0, dur: .07, vol: .05 },
    { type: 'tone', wave: 'triangle', freq: 523, at: .06, dur: .07, vol: .05 },
    { type: 'tone', wave: 'triangle', freq: 784, at: .12, dur: .12, vol: .05 }
  ],
  // Parar, borrar, banear: dos notas graves que bajan.
  danger: [
    { type: 'tone', wave: 'square', freq: 330, at: 0, dur: .08, vol: .025 },
    { type: 'tone', wave: 'square', freq: 220, at: .08, dur: .14, vol: .025 }
  ],
  // Interruptores: un «blip» que sube al encender y baja al apagar.
  'toggle-on': [
    { type: 'tone', wave: 'triangle', freq: 600, to: 1000, at: 0, dur: .06, vol: .04 }
  ],
  'toggle-off': [
    { type: 'tone', wave: 'triangle', freq: 800, to: 450, at: 0, dur: .06, vol: .04 }
  ],
  // Elegir tema: un viaje entre dimensiones.
  warp: [
    { type: 'tone', wave: 'sine', freq: 220, to: 880, at: 0, dur: .28, vol: .045 },
    { type: 'tone', wave: 'sine', freq: 330, to: 1320, at: .03, dur: .28, vol: .025 },
    { type: 'noise', freq: 800, to: 4000, q: 2, at: 0, dur: .25, vol: .04 }
  ],
  // Algo salió bien: un «pling» como al recoger experiencia.
  success: [
    { type: 'tone', wave: 'sine', freq: 1046, at: 0, dur: .12, vol: .05 },
    { type: 'tone', wave: 'sine', freq: 1568, at: .07, dur: .18, vol: .04 }
  ],
  // Algo falló: un zumbido grave.
  error: [
    { type: 'tone', wave: 'square', freq: 247, at: 0, dur: .12, vol: .03 },
    { type: 'tone', wave: 'square', freq: 185, at: .11, dur: .16, vol: .03 }
  ],
  // Logro y fin de una instalación: la fanfarria.
  levelup: [
    { type: 'tone', wave: 'square', freq: 523, at: 0, dur: .14, vol: .035 },
    { type: 'tone', wave: 'square', freq: 659, at: .08, dur: .14, vol: .035 },
    { type: 'tone', wave: 'square', freq: 784, at: .16, dur: .14, vol: .035 },
    { type: 'tone', wave: 'triangle', freq: 1047, at: .26, dur: .3, vol: .05 }
  ]
};

function soundsOn() {
  return readPref('sounds', 'off') === 'on';
}

function getNoiseBuffer() {
  if (!noiseBuffer) {
    noiseBuffer = audioCtx.createBuffer(1, Math.floor(audioCtx.sampleRate * .5), audioCtx.sampleRate);
    var data = noiseBuffer.getChannelData(0);
    for (var i = 0; i < data.length; i++) {
      data[i] = Math.random() * 2 - 1;
    }
  }
  return noiseBuffer;
}

function playSoundPart(part, start) {
  var at = start + part.at;
  var end = at + part.dur;
  var gain = audioCtx.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(part.vol, at + Math.min(.008, part.dur / 3));
  gain.gain.exponentialRampToValueAtTime(0.0001, end);
  gain.connect(audioCtx.destination);
  var source;
  if (part.type === 'noise') {
    source = audioCtx.createBufferSource();
    source.buffer = getNoiseBuffer();
    var filter = audioCtx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.Q.value = part.q || 1;
    filter.frequency.setValueAtTime(part.freq, at);
    if (part.to) {
      filter.frequency.exponentialRampToValueAtTime(part.to, end);
    }
    source.connect(filter);
    filter.connect(gain);
  } else {
    source = audioCtx.createOscillator();
    source.type = part.wave || 'square';
    source.frequency.setValueAtTime(part.freq, at);
    if (part.to) {
      source.frequency.exponentialRampToValueAtTime(part.to, end);
    }
    source.connect(gain);
  }
  source.start(at);
  source.stop(end + .02);
}

function playSound(kind) {
  var sound = SOUNDS[kind];
  if (!sound || !soundsOn()) {
    return;
  }
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    var start = audioCtx.currentTime + .005;
    sound.forEach(function(part) { playSoundPart(part, start); });
  } catch (e) {}
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
  playSound('toggle-on');
}

document.getElementById('sound-toggle').addEventListener('click', toggleSounds);
document.getElementById('sound-toggle').addEventListener('keydown', function(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleSounds();
  }
});

// Qué suena al pulsar algo, según lo que hace. Un botón puede elegir el suyo
// con data-sound="..." (una clave de SOUNDS).
function soundForControl(el) {
  if (el.dataset.sound) {
    return el.dataset.sound;
  }
  if (el.classList.contains('theme-option')) {
    return 'warp';
  }
  if (el.classList.contains('nav-tab') || el.classList.contains('nav-action')) {
    return 'nav';
  }
  if (el.classList.contains('modal-close') || /^(cerrar|cancelar)$/i.test((el.getAttribute('aria-label') || el.textContent).trim())) {
    return 'close';
  }
  if (el.classList.contains('btn-go')) {
    return 'go';
  }
  if (el.classList.contains('btn-danger')) {
    return 'danger';
  }
  return 'tap';
}

document.addEventListener('click', function(event) {
  var toggle = event.target.closest('.toggle-track');
  if (toggle) {
    if (toggle.id !== 'sound-toggle') {
      // Se mira después del clic, cuando el interruptor ya ha cambiado.
      setTimeout(function() {
        playSound(toggle.classList.contains('on') ? 'toggle-on' : 'toggle-off');
      }, 0);
    }
    return;
  }
  var button = event.target.closest('button');
  if (button && !button.disabled) {
    playSound(soundForControl(button));
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
  { id: 'night-shift', name: 'Turno de noche', hint: 'Arranca un servidor entre la 1 y las 5 de la madrugada.' },
  { id: 'early-bird', name: 'Madrugador', hint: 'Arranca un servidor entre las 6 y las 8 de la mañana.' },
  { id: 'collector', name: 'Coleccionista', hint: 'Ten 5 modpacks instalados.' },
  { id: 'handyman', name: 'Manitas', hint: 'Instala un mod desde el buscador.' },
  { id: 'tidy', name: 'Limpieza a fondo', hint: 'Borra mods que sobran: de solo cliente o desactivados.' },
  { id: 'new-world', name: 'Nuevo horizonte', hint: 'Crea o sube un mundo.' },
  { id: 'backup', name: 'A buen recaudo', hint: 'Descarga una copia de un mundo.' },
  { id: 'herald', name: 'Pregonero', hint: 'Habla a los jugadores con el comando say.' },
  { id: 'sold-out', name: 'No cabe ni un alfiler', hint: 'Llena todas las plazas del servidor.' },
  { id: 'marathon', name: 'Maratón', hint: 'Ten un servidor encendido 24 horas seguidas.' },
  { id: 'tourist', name: 'Turista interdimensional', hint: 'Prueba todos los temas.' },
  { id: 'explorer', name: 'Explorador', hint: 'Visita todas las secciones del panel.' },
  { id: 'safe-keeper', name: 'Precavido', hint: 'Haz una copia de seguridad de un mundo desde Copias.' },
  { id: 'clockwork', name: 'Como un reloj', hint: 'Programa una tarea en Automatización.' },
  { id: 'messenger', name: 'Paloma mensajera', hint: 'Recibe un aviso de prueba por Telegram o Discord.' },
  { id: 'twins', name: 'Gemelos', hint: 'Clona un servidor.' },
  { id: 'iron-fist', name: 'Mano dura', hint: 'Banea a alguien.', secret: true },
  { id: 'mercy', name: 'Segundas oportunidades', hint: 'Levanta un baneo.', secret: true },
  { id: 'konami', name: 'Vidas infinitas', hint: 'Arriba, arriba, abajo, abajo…', secret: true },
  { id: 'herobrine', name: 'Él te observa', hint: 'Escribe su nombre en cualquier parte.', secret: true },
  { id: 'hard-stop', name: 'Por las malas', hint: 'Para el servidor con stop desde la consola.', secret: true },
  { id: 'weatherman', name: 'Hombre del tiempo', hint: 'Cambia el tiempo o la hora desde la consola.', secret: true },
  { id: 'dizzy', name: 'Mareo interdimensional', hint: 'Cambia de tema 10 veces en medio minuto.', secret: true },
  { id: 'touch-sky', name: 'Tocar el cielo', hint: 'Pulsa 5 veces el sol o la luna.', secret: true },
  { id: 'tnt', name: 'Borrón y cuenta nueva', hint: 'Borra un mundo.', secret: true },
  { id: 'phoenix', name: 'Ave fénix', hint: 'Que el servidor se levante solo tras una caída.', secret: true },
  { id: 'platinum', name: 'Platino', hint: 'Consigue todos los demás logros.' }
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
  // Si el diálogo de Apariencia está abierto (p. ej. al probar los temas),
  // la lista se actualiza en el momento.
  renderAchievementList();
  var stack = document.getElementById('toast');
  var toastEl = document.createElement('div');
  toastEl.className = 'toast achievement';
  toastEl.innerHTML = '<span class="achievement-icon">' + achievementIconHtml(achievement, true) + '</span>'
    + '<span><span class="achievement-kicker">¡Logro conseguido!</span>'
    + '<span class="achievement-name">' + escHtml(achievement.name) + '</span></span>';
  stack.appendChild(toastEl);
  requestAnimationFrame(function() { toastEl.classList.add('show'); });
  playSound('levelup');
  setTimeout(function() {
    toastEl.classList.remove('show');
    setTimeout(function() { toastEl.remove(); }, 300);
  }, 5000);
  var rest = ACHIEVEMENTS.filter(function(item) { return item.id !== 'platinum'; });
  if (id !== 'platinum' && rest.every(function(item) { return hasAchievement(item.id); })) {
    setTimeout(function() { unlockAchievement('platinum'); }, 1200);
  }
}

// Logros de «haz todas las X»: se apunta cada una vista y se desbloquea al
// completar la lista.
function collectForAchievement(id, value, required) {
  var seen = [];
  try {
    seen = JSON.parse(readPref('ach-seen-' + id, '[]'));
  } catch (err) {
    seen = [];
  }
  if (!Array.isArray(seen)) {
    seen = [];
  }
  if (seen.indexOf(value) < 0) {
    seen.push(value);
    writePref('ach-seen-' + id, JSON.stringify(seen));
  }
  if (required.length && required.every(function(item) { return seen.indexOf(item) >= 0; })) {
    unlockAchievement(id);
  }
}

// Escribir «Herobrine» en cualquier campo (menos en las contraseñas).
document.addEventListener('input', function(event) {
  var field = event.target;
  if (field.type !== 'password' && typeof field.value === 'string' && /herobrine/i.test(field.value)) {
    unlockAchievement('herobrine');
  }
});

// Pulsar el sol o la luna de la escena. La escena no recibe clics (está
// detrás del contenido), así que se mira si el clic cae encima del astro.
var skyClicks = [];
document.addEventListener('click', function(event) {
  var orbs = document.querySelectorAll('.scene-orb');
  for (var i = 0; i < orbs.length; i++) {
    var rect = orbs[i].getBoundingClientRect();
    if (rect.width && event.clientX >= rect.left - 4 && event.clientX <= rect.right + 4
        && event.clientY >= rect.top - 4 && event.clientY <= rect.bottom + 4) {
      var now = Date.now();
      skyClicks = skyClicks.filter(function(at) { return now - at < 4000; }).concat(now);
      if (skyClicks.length >= 5) {
        skyClicks = [];
        unlockAchievement('touch-sky');
      }
      return;
    }
  }
});

// Código Konami en cualquier parte del panel (salvo escribiendo en un campo).
var KONAMI = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
var konamiPos = 0;
document.addEventListener('keydown', function(event) {
  if (event.target.closest && event.target.closest('input, textarea, select, [contenteditable="true"]')) {
    return;
  }
  var key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  konamiPos = key === KONAMI[konamiPos] ? konamiPos + 1 : (key === KONAMI[0] ? 1 : 0);
  if (konamiPos === KONAMI.length) {
    konamiPos = 0;
    unlockAchievement('konami');
  }
});

function renderAchievementList() {
  var got = ACHIEVEMENTS.filter(function(item) { return hasAchievement(item.id); }).length;
  document.getElementById('achievement-count').textContent = got + ' de ' + ACHIEVEMENTS.length;
  document.getElementById('achievement-list').innerHTML = ACHIEVEMENTS.map(function(item) {
    var unlocked = hasAchievement(item.id);
    var hidden = item.secret && !unlocked;
    var when = Number(readPref('ach-' + item.id, ''));
    var hint = !unlocked ? (hidden ? 'Logro secreto' : item.hint)
      : (when ? 'Conseguido el ' + new Date(when).toLocaleDateString('es-ES') : 'Conseguido');
    return '<li class="achievement-row' + (unlocked ? ' unlocked' : '') + (hidden ? ' secret' : '') + '"'
      + (unlocked ? ' title="' + escHtml(item.hint) + '"' : '') + '>'
      + '<span class="achievement-icon">' + achievementIconHtml(item, unlocked) + '</span>'
      + '<span><span class="achievement-name">' + escHtml(hidden ? '???' : item.name) + '</span>'
      + '<span class="achievement-hint">' + escHtml(hint) + '</span></span></li>';
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
