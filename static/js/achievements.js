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
