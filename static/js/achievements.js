// -- Logros ------------------------------------------------------------------------
// Pequeños hitos que se celebran una sola vez por cuenta: se guardan en el
// servidor (GET/POST /api/auth/achievements), así que se ven igual en
// cualquier navegador o dispositivo con el que se entre.
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
  { id: 'time-capsule', name: 'Cápsula del tiempo', hint: 'Haz una copia completa de un servidor.' },
  { id: 'two-keys', name: 'Doble cerradura', hint: 'Activa la verificación en dos pasos.' },
  { id: 'new-season', name: 'Nueva temporada', hint: 'Actualiza un servidor a otra versión de su modpack.' },
  { id: 'tune-up', name: 'Puesta a punto', hint: 'Actualiza 10 mods o más de una vez.' },
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

// Estado de la cuenta: {id: fecha en ms} y {id: [valores vistos]}. Hasta
// que llega del servidor (o sin sesión, en la pantalla de entrada), lo que se
// consiga espera en deferredAchievements y se repasa al cargar: así no se
// celebra otra vez un logro que la cuenta ya tenía.
var accountAchievements = {};
var accountAchSeen = {};
var achievementsLoaded = false;
var deferredAchievements = [];
// Lo que no se pudo mandar (sin conexión) se reintenta en el siguiente envío.
var achievementRetry = { unlocked: {}, seen: {} };

function hasAchievement(id) {
  return !!accountAchievements[id];
}

function sendAchievements(payload) {
  Object.keys(achievementRetry.unlocked).forEach(function(id) {
    payload.unlocked[id] = payload.unlocked[id] || achievementRetry.unlocked[id];
  });
  Object.keys(achievementRetry.seen).forEach(function(id) {
    payload.seen[id] = (payload.seen[id] || []).concat(achievementRetry.seen[id]);
  });
  achievementRetry = { unlocked: {}, seen: {} };
  return apiFetch('/api/auth/achievements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).then(function(response) {
    if (!response.ok) {
      throw new Error('HTTP ' + response.status);
    }
    return response.json();
  }).then(applyAccountAchievements).catch(function(err) {
    Object.keys(payload.unlocked).forEach(function(id) { achievementRetry.unlocked[id] = payload.unlocked[id]; });
    Object.keys(payload.seen).forEach(function(id) {
      achievementRetry.seen[id] = (achievementRetry.seen[id] || []).concat(payload.seen[id]);
    });
    throw err;
  });
}

function applyAccountAchievements(data) {
  // Lo conseguido mientras volaba la petición se conserva.
  var unlocked = (data && data.unlocked) || {};
  var seen = (data && data.seen) || {};
  Object.keys(accountAchievements).forEach(function(id) {
    unlocked[id] = unlocked[id] || accountAchievements[id];
  });
  Object.keys(accountAchSeen).forEach(function(id) {
    seen[id] = (seen[id] || []).concat(accountAchSeen[id].filter(function(value) {
      return (seen[id] || []).indexOf(value) < 0;
    }));
  });
  accountAchievements = unlocked;
  accountAchSeen = seen;
  if (document.getElementById('achievement-list')) {
    renderAchievementList();
  }
}

// Logros que este navegador guardaba antes en localStorage (versiones
// anteriores a la 3.0.3): se suben una vez a la primera cuenta que entre y se
// borran de aquí, para que no se los quede también la siguiente.
function legacyBrowserAchievements() {
  var found = { unlocked: {}, seen: {}, keys: [] };
  try {
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (key && key.indexOf('mcd-ach-') === 0) {
        found.keys.push(key);
      }
    }
  } catch (err) {
    return found;
  }
  found.keys.forEach(function(key) {
    var value = readPref(key.slice('mcd-'.length), '');
    if (key.indexOf('mcd-ach-seen-') === 0) {
      try {
        var list = JSON.parse(value);
        if (Array.isArray(list)) {
          found.seen[key.slice('mcd-ach-seen-'.length)] = list;
        }
      } catch (err) {}
    } else if (Number(value) > 0) {
      found.unlocked[key.slice('mcd-ach-'.length)] = Number(value);
    }
  });
  return found;
}

// Se llama al entrar (onLoginSuccess): trae los logros de la cuenta (subiendo
// antes los antiguos del navegador, si los hay) y repasa los pendientes.
function loadAccountAchievements() {
  var legacy = legacyBrowserAchievements();
  var request;
  if (legacy.keys.length) {
    request = sendAchievements({ unlocked: legacy.unlocked, seen: legacy.seen });
  } else {
    request = apiFetch('/api/auth/achievements').then(function(response) {
      if (!response.ok) {
        throw new Error('HTTP ' + response.status);
      }
      return response.json();
    }).then(applyAccountAchievements);
  }
  return request.then(function() {
    legacy.keys.forEach(function(key) {
      try { localStorage.removeItem(key); } catch (err) {}
    });
    achievementsLoaded = true;
    var pending = deferredAchievements;
    deferredAchievements = [];
    pending.forEach(function(item) {
      if (item[0] === 'unlock') {
        unlockAchievement(item[1]);
      } else {
        collectForAchievement(item[1], item[2], item[3]);
      }
    });
    checkPlatinum();
  }).catch(function() {});
}

// Al salir, la siguiente cuenta no debe ver los logros de esta. Lo que quede
// pendiente (hecho en la pantalla de entrada) es de quien entre después.
function resetAccountAchievements() {
  accountAchievements = {};
  accountAchSeen = {};
  achievementsLoaded = false;
  achievementRetry = { unlocked: {}, seen: {} };
}

// Las métricas piden el mismo logro en cada sondeo: se apunta una sola vez.
function deferAchievement(item) {
  var key = item.slice(0, 3).join('|');
  var already = deferredAchievements.some(function(other) { return other.slice(0, 3).join('|') === key; });
  if (!already) {
    deferredAchievements.push(item);
  }
}

function checkPlatinum() {
  var rest = ACHIEVEMENTS.filter(function(item) { return item.id !== 'platinum'; });
  if (achievementsLoaded && !hasAchievement('platinum') && rest.every(function(item) { return hasAchievement(item.id); })) {
    setTimeout(function() { unlockAchievement('platinum'); }, 1200);
  }
}

function unlockAchievement(id) {
  var achievement = ACHIEVEMENTS.filter(function(item) { return item.id === id; })[0];
  if (!achievement) {
    return;
  }
  if (!achievementsLoaded) {
    deferAchievement(['unlock', id]);
    return;
  }
  if (hasAchievement(id)) {
    return;
  }
  var now = Date.now();
  accountAchievements[id] = now;
  var single = { unlocked: {}, seen: {} };
  single.unlocked[id] = now;
  sendAchievements(single).catch(function() {});
  // Si el diálogo de Apariencia está abierto (p. ej. al probar los temas),
  // la lista se actualiza en el momento.
  renderAchievementList();
  var stack = document.getElementById('toast');
  var toastEl = document.createElement('div');
  toastEl.className = 'toast achievement';
  toastEl.innerHTML = '<span class="achievement-icon">' + achievementIconHtml(achievement, true) + '</span>'
    + '<span><span class="achievement-kicker">' + t('¡Logro conseguido!') + '</span>'
    + '<span class="achievement-name">' + escHtml(t(achievement.name)) + '</span></span>';
  stack.appendChild(toastEl);
  requestAnimationFrame(function() { toastEl.classList.add('show'); });
  playSound('levelup');
  setTimeout(function() {
    toastEl.classList.remove('show');
    setTimeout(function() { toastEl.remove(); }, 300);
  }, 5000);
  if (id !== 'platinum') {
    checkPlatinum();
  }
}

// Logros de «haz todas las X»: se apunta cada una vista y se desbloquea al
// completar la lista.
function collectForAchievement(id, value, required) {
  if (!achievementsLoaded) {
    deferAchievement(['collect', id, value, required]);
    return;
  }
  var seen = accountAchSeen[id] || [];
  if (seen.indexOf(value) < 0) {
    seen = seen.concat(value);
    accountAchSeen[id] = seen;
    var single = { unlocked: {}, seen: {} };
    single.seen[id] = [value];
    sendAchievements(single).catch(function() {});
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
  document.getElementById('achievement-count').textContent = t('{got} de {total}', { got: got, total: ACHIEVEMENTS.length });
  document.getElementById('achievement-list').innerHTML = ACHIEVEMENTS.map(function(item) {
    var unlocked = hasAchievement(item.id);
    var hidden = item.secret && !unlocked;
    var when = Number(accountAchievements[item.id] || 0);
    var hint = !unlocked ? (hidden ? t('Logro secreto') : t(item.hint))
      : (when ? t('Conseguido el {date}', { date: new Date(when).toLocaleDateString(APP_LOCALE) }) : t('Conseguido'));
    return '<li class="achievement-row' + (unlocked ? ' unlocked' : '') + (hidden ? ' secret' : '') + '"'
      + (unlocked ? ' title="' + escHtml(t(item.hint)) + '"' : '') + '>'
      + '<span class="achievement-icon">' + achievementIconHtml(item, unlocked) + '</span>'
      + '<span><span class="achievement-name">' + escHtml(hidden ? '???' : t(item.name)) + '</span>'
      + '<span class="achievement-hint">' + escHtml(hint) + '</span></span></li>';
  }).join('');
}
