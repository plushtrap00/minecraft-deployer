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
