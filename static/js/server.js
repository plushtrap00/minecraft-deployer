// -- Servidor -----------------------------------------------------------------
var sseSource = null;
var serverRunning = false;
var mcDomain = '';
// Datos del último /api/modpacks, por nombre: la cabecera los usa para
// mostrar modloader y versión del servidor que está en marcha.
var serverPackInfo = {};

function loadMcDomain() {
  apiFetch('/api/system-info')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      mcDomain = data.mc_domain || '';
    })
    .catch(function() {});
}

function checkServerStatus() {
  apiFetch('/api/server/status')
    .then(function(response) { return response.json(); })
    .then(function(data) { applyServerState(data.running, data.modpack, data.ready); })
    .catch(function() { applyServerState(false, null); });
}

// -- Cabecera de estado --------------------------------------------------------
// state: 'stopped' | 'starting' | 'running'. Es lo único que decide colores,
// cielo de la escena y botones de la cabecera (vía data-state en el CSS).
// También se copia a <html data-server>, que tiñe el fondo de toda la app.
function setHeroState(state, statusText, name) {
  var hero = document.getElementById('server-hero');
  hero.dataset.state = state;
  document.documentElement.dataset.server = state;
  document.getElementById('status-text').textContent = statusText;
  document.getElementById('status-modpack').textContent = name || t('Ningún servidor en marcha');
  // Con el proceso en marcha se puede parar aunque aún esté cargando.
  var stoppable = serverRunning && state !== 'stopped';
  document.getElementById('clean-stop-btn').style.display = stoppable ? '' : 'none';
  document.getElementById('stop-btn').style.display = stoppable ? '' : 'none';
  document.getElementById('hero-client-pack-btn').style.display = state === 'stopped' ? 'none' : '';
  renderHeroIcon(state === 'stopped' ? null : name);
  if (state !== 'starting') {
    document.getElementById('startup-progress').hidden = true;
  }
  if (state === 'stopped') {
    document.getElementById('server-hero-meta').innerHTML = '';
  }
}

function renderHeroIcon(name) {
  var holder = document.getElementById('server-hero-icon');
  if (!name) {
    holder.innerHTML = '';
    delete holder.dataset.pack;
    return;
  }
  var info = serverPackInfo[name] || { name: name };
  var key = name + (info.has_icon ? '+icon' : '');
  if (holder.dataset.pack !== key) {
    holder.dataset.pack = key;
    holder.innerHTML = packIconHtml(info);
  }
}

// -- Progreso del arranque -------------------------------------------------------
// Mientras arranca, las líneas de la consola dicen por dónde va: se traducen a
// una fase legible y a un porcentaje aproximado (nunca retrocede). Cuando sale
// «Done (…)!» el servidor ya acepta jugadores.
var startupTracking = false;
var startupPercent = 0;
var STARTUP_PHASES = [
  { re: /ModLauncher running|Launching target|Loading Minecraft .* with Fabric|Loading \d+ mods|Found \d+ mods|Loading mods/i, text: t('Cargando mods…'), pct: 12 },
  { re: /Starting minecraft server version|Starting Minecraft server/i, text: t('Arrancando Minecraft…'), pct: 42 },
  { re: /Loading properties/i, text: t('Leyendo la configuración…'), pct: 46 },
  { re: /Preparing level/i, text: t('Preparando el mundo…'), pct: 58 },
  { re: /Preparing start region/i, text: t('Preparando el spawn…'), pct: 62 }
];
var SPAWN_PROGRESS_RE = /Preparing spawn area:\s*(\d+)\s*%/i;
var DONE_LINE_RE = /\]: Done \(\d/;

function setStartupProgress(percent, text) {
  startupPercent = Math.max(startupPercent, Math.min(100, percent));
  document.getElementById('startup-progress').hidden = false;
  setFill(document.getElementById('startup-fill'), startupPercent);
  document.getElementById('startup-bar').setAttribute('aria-valuenow', String(Math.round(startupPercent)));
  if (text) {
    document.getElementById('startup-phase').textContent = text;
  }
}

function beginStartupTracking() {
  startupTracking = true;
  startupPercent = 0;
  setStartupProgress(4, t('Lanzando Java…'));
}

function trackStartupLine(line) {
  if (!startupTracking) {
    return;
  }
  if (DONE_LINE_RE.test(line)) {
    markServerReady(true);
    return;
  }
  var spawn = line.match(SPAWN_PROGRESS_RE);
  if (spawn) {
    var spawnPct = parseInt(spawn[1], 10);
    setStartupProgress(62 + spawnPct * .36, t('Preparando el spawn {pct} %', { pct: spawnPct }));
    return;
  }
  for (var i = 0; i < STARTUP_PHASES.length; i++) {
    if (STARTUP_PHASES[i].re.test(line)) {
      setStartupProgress(STARTUP_PHASES[i].pct, STARTUP_PHASES[i].text);
      return;
    }
  }
  // Cargar cientos de mods escribe miles de líneas: cada una empuja un
  // poquito la barra para que se vea que avanza, sin pasar de la fase siguiente.
  if (startupPercent < 40) {
    setStartupProgress(startupPercent + .12);
  } else if (startupPercent >= 58 && startupPercent < 62) {
    setStartupProgress(startupPercent + .05);
  }
}

// El servidor ya acepta jugadores. celebrateIt: se acaba de ver el «Done» en
// directo (no al recargar la página con el servidor ya encendido).
function markServerReady(celebrateIt) {
  var wasTracking = startupTracking;
  startupTracking = false;
  if (!serverRunning) {
    return;
  }
  var name = document.getElementById('status-modpack').textContent;
  var finish = function() {
    setHeroState('running', t('Listo para jugar'), name);
    renderHeroMeta(name);
  };
  if (!celebrateIt || !wasTracking) {
    finish();
    return;
  }
  setStartupProgress(100, t('¡Listo!'));
  setTimeout(function() {
    finish();
    celebrate(document.getElementById('server-hero-icon').firstChild || document.getElementById('status-modpack'));
    unlockAchievement('first-start');
    var hour = new Date().getHours();
    if (hour >= 1 && hour < 5) {
      unlockAchievement('night-shift');
    }
    if (hour >= 6 && hour < 8) {
      unlockAchievement('early-bird');
    }
  }, 500);
}

function renderHeroMeta(modpack) {
  var meta = document.getElementById('server-hero-meta');
  if (!serverRunning) {
    meta.innerHTML = '';
    return;
  }
  var info = serverPackInfo[modpack] || {};
  var parts = [];
  if (info.modloader !== undefined) {
    parts.push('<span>' + loaderTag(info.modloader) + (info.mc_version ? ' Minecraft ' + escHtml(info.mc_version) : '') + '</span>');
  }
  if (uptimeBase) {
    parts.push('<span id="hero-uptime">' + icon('clock') + escHtml(t('Encendido hace {time}', { time: formatUptime(currentUptime()) })) + '</span>');
  }
  if (mcDomain && netPublic) {
    parts.push('<span>' + icon('globe') + escHtml(mcDomain) + '</span>');
  }
  meta.innerHTML = parts.join('');
}

function formatUptime(seconds) {
  if (seconds < 60) {
    return t('menos de un minuto');
  }
  var minutes = Math.floor(seconds / 60);
  var hours = Math.floor(minutes / 60);
  var days = Math.floor(hours / 24);
  if (days > 0) {
    return days + ' d ' + (hours % 24) + ' h';
  }
  if (hours > 0) {
    return hours + ' h ' + (minutes % 60) + ' min';
  }
  return minutes + ' min';
}

// uptime_seconds llega con cada /metrics (cada 10 s); entre medias se
// cuenta en el navegador a partir del último valor recibido.
var uptimeBase = null;

function currentUptime() {
  return uptimeBase.seconds + Math.floor((Date.now() - uptimeBase.at) / 1000);
}

// ready: el servidor ya escribió «Done» (acepta jugadores). Si no, está
// cargando y la cabecera sigue en «arrancando» con su barra de progreso.
function applyServerState(running, modpack, ready) {
  serverRunning = running;
  document.getElementById('server-picker').style.display = running ? 'none' : 'block';
  document.getElementById('console-card').style.display = running ? 'block' : 'none';
  document.getElementById('metrics-card').style.display = running ? '' : 'none';
  if (running) {
    var heroState = document.getElementById('server-hero').dataset.state;
    if (ready) {
      startupTracking = false;
      setHeroState('running', t('Listo para jugar'), modpack);
    } else if (!startupTracking || heroState !== 'starting') {
      setHeroState('starting', t('Arrancando…'), modpack);
      beginStartupTracking();
    }
    document.getElementById('console-modpack').textContent = modpack || '';
    if (!serverPackInfo[modpack]) {
      refreshServerPackInfo().then(function() {
        renderHeroIcon(modpack);
        renderHeroMeta(modpack);
      });
    }
    renderHeroMeta(modpack);
    if (!sseSource) {
      startSSE();
    }
    startMetricsPolling();
  } else {
    startupTracking = false;
    setHeroState('stopped', t('Parado'), null);
    if (sseSource) {
      sseSource.close();
      sseSource = null;
    }
    stopMetricsPolling();
    resetMetrics();
    loadServerPickList();
  }
}

// Lo piden a la vez varias partes (lista para arrancar, Rendimiento,
// Estadísticas): mientras hay una petición en curso se comparte, porque
// apiFetch cancela un GET si sale otro igual y el primero no llegaría nunca.
var packInfoRequest = null;

function refreshServerPackInfo() {
  if (packInfoRequest) {
    return packInfoRequest;
  }
  packInfoRequest = apiFetch('/api/modpacks')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      packInfoRequest = null;
      serverPackInfo = {};
      (data.modpacks || []).forEach(function(pack) {
        serverPackInfo[pack.name] = pack;
      });
      return data.modpacks || [];
    }, function(error) {
      packInfoRequest = null;
      throw error;
    });
  return packInfoRequest;
}

function loadServerPickList() {
  var list = document.getElementById('server-pick-list');
  list.innerHTML = '<div class="skeleton-rows"><div></div><div></div></div>';
  refreshServerPackInfo()
    .then(function(packs) {
      if (!packs.length) {
        list.innerHTML = emptyArt('chest', t('Todavía no hay servidores'),
          t('Instala un modpack o crea un servidor vanilla y aparecerá aquí, listo para arrancar.'),
          '<button class="btn-go" id="pick-empty-install">' + icon('package-plus') + t('Instalar un modpack') + '</button>');
        document.getElementById('pick-empty-install').addEventListener('click', function() {
          document.getElementById('tab-deploy').click();
        });
        return;
      }
      list.innerHTML = '';
      packs.forEach(function(pack) {
        list.appendChild(serverCard(pack));
      });
    })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg error-msg">' + t('No se pudo cargar la lista de servidores. Recarga la página para reintentarlo.') + '</p>';
    });
}

// Tarjeta de un servidor para arrancar: logo, versión, cuándo se usó y un
// botón grande de Iniciar. El borde de arriba es del color del modloader.
function serverCard(pack) {
  var card = document.createElement('article');
  card.className = 'server-card' + (pack.start_script ? '' : ' no-script');
  if (pack.modloader) {
    card.dataset.loader = pack.modloader.toLowerCase();
  }
  var facts = ['<span>' + icon('clock') + escHtml(pack.last_played ? t('Arrancado {when}', { when: formatRelativeDate(pack.last_played) }) : t('Sin estrenar')) + '</span>'];
  if (pack.mods_count) {
    facts.push('<span>' + icon('puzzle') + pack.mods_count + ' ' + (pack.mods_count === 1 ? t('mod') : t('mods')) + '</span>');
  }
  if (!pack.start_script) {
    facts.push('<span class="server-card-warn">' + icon('triangle-alert') + t('No tiene script de arranque') + '</span>');
  }
  if (pack.pending_mods && pack.pending_mods.length) {
    facts.push('<span class="server-card-pending" title="' + escHtml(pack.pending_mods.join(', ')) + '">' + icon('timer')
      + (pack.pending_mods.length === 1 ? t('1 mod pendiente') : t('{n} mods pendientes', { n: pack.pending_mods.length })) + '</span>');
  }
  card.innerHTML = '<div class="server-card-head">' + packIconHtml(pack)
    + '<div class="server-card-title"><h3 class="server-card-name">' + escHtml(pack.name) + '</h3>'
    + '<div class="server-card-sub">' + loaderTag(pack.modloader)
    + (pack.mc_version ? '<span>Minecraft ' + escHtml(pack.mc_version) + '</span>' : '') + '</div></div></div>'
    + '<div class="server-card-facts">' + facts.join('') + '</div>'
    + '<button class="btn-go"' + (pack.start_script ? '' : ' disabled') + ' aria-label="' + escHtml(t('Iniciar {name}', { name: pack.name })) + '">'
    + icon('play') + t('Iniciar') + '</button>';
  if (pack.start_script) {
    card.querySelector('button').addEventListener('click', function() { startServer(pack.name); });
  }
  return card;
}


// ── Toggle público/LAN ────────────────────────────────────────────────────────
var netPublic = false;
// Red local y puertos reales, tal y como los devuelve /api/firewall/status.
var netSubnet = '';
var netPorts = [];

function applyNetToggleUI(isPublic) {
  var track = document.getElementById('net-toggle-track');
  var label = document.getElementById('net-toggle-label');
  var desc = document.getElementById('net-toggle-desc');
  track.setAttribute('aria-checked', isPublic ? 'true' : 'false');
  if (isPublic) {
    track.classList.add('on');
    label.textContent = t('Abierto a internet');
    if (mcDomain) {
      desc.textContent = t('Se puede entrar desde fuera de casa en {address}', { address: mcDomain + ':' + (netPorts[0] || 25565) });
    } else {
      desc.textContent = t('Se puede entrar desde fuera de casa');
    }
  } else {
    track.classList.remove('on');
    label.textContent = t('Solo red local');
    desc.textContent = t('Solo se puede entrar desde tu red de casa') + (netSubnet ? ' (' + netSubnet + ')' : '');
  }
}

function loadFirewallStatus() {
  apiFetch('/api/firewall/status')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var track = document.getElementById('net-toggle-track');
      var label = document.getElementById('net-toggle-label');
      var desc = document.getElementById('net-toggle-desc');
      if (data.mode === 'unavailable') {
        // ufw no existe en este entorno (típico dentro de un contenedor Docker,
        // donde además no tendría efecto real sobre el host) — no tiene sentido
        // dejar el interruptor en un estado ambiguo, se explica y se bloquea.
        track.classList.add('disabled');
        track.style.pointerEvents = 'none';
        track.setAttribute('aria-disabled', 'true');
        label.textContent = t('Acceso desde fuera: no disponible aquí');
        desc.textContent = t('En Docker, el acceso público o solo LAN se controla desde el mapeo de puertos de docker-compose.yml.');
        return;
      }
      netSubnet = data.subnet || '';
      netPorts = data.ports || [];
      track.classList.remove('disabled');
      track.style.pointerEvents = '';
      track.removeAttribute('aria-disabled');
      netPublic = (data.mode === 'public');
      applyNetToggleUI(netPublic);
      if (currentRole !== 'admin') {
        // Se ve cómo está, pero solo el administrador lo cambia.
        track.classList.add('disabled');
        track.style.pointerEvents = 'none';
        track.setAttribute('aria-disabled', 'true');
        desc.textContent += ' · ' + t('Solo el administrador puede cambiarlo');
      }
    })
    .catch(function() {});
}

function toggleNetMode() {
  var track = document.getElementById('net-toggle-track');
  if (track.classList.contains('disabled')) {
    return;
  }
  var newMode = netPublic ? 'lan' : 'public';
  track.style.opacity = '0.5';
  track.style.pointerEvents = 'none';
  var form = new FormData();
  form.append('mode', newMode);
  apiFetch('/api/firewall/set', { method: 'POST', body: form })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      if (result.ok) {
        netPublic = (result.data.mode === 'public');
        netSubnet = result.data.subnet || netSubnet;
        netPorts = result.data.ports || netPorts;
        applyNetToggleUI(netPublic);
        if (netPublic) {
          showToast(t('Servidor abierto a internet'), 'success');
        } else {
          showToast(t('Servidor limitado a la red local'), 'success');
        }
      } else {
        showToast(t('No se pudo cambiar el firewall: {error}', { error: result.data.detail || t('error desconocido') }), 'error');
      }
    })
    .catch(function(error) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      showToast(t('No se pudo conectar con el panel: {error}', { error: error.message }), 'error');
    });
}

document.getElementById('net-toggle-track').addEventListener('click', toggleNetMode);
document.getElementById('net-toggle-track').addEventListener('keydown', function(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleNetMode();
  }
});

// Antes de arrancar se hace una comprobación rápida (GET /pending-mods, solo lee un
// JSON) de si queda algo pendiente. Si no hay nada, se arranca directo sin
// más — pero si SÍ hay algo, puede que ya se haya resuelto por una vía que la
// app no ve sola (un mod copiado a mano por SFTP en vez de subido desde el
// panel), así que se dispara una comprobación completa con progreso (SSE: abre
// cada mod instalado para comparar su mod_id/versión real) antes de decidir
// si de verdad hay que bloquear el arranque. Por eso la ruedita de "Comprobando
// mods pendientes…" solo aparece cuando hacía falta — el caso normal (sin
// nada pendiente) arranca sin ningún paso extra.
function startServer(modpack) {
  setHeroState('starting', t('Preparando…'), modpack);
  document.getElementById('server-picker').style.display = 'none';

  apiFetch('/api/modpacks/' + encodeURIComponent(modpack) + '/pending-mods')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.pending_mods && data.pending_mods.length) {
        recheckPendingModsThenStart(modpack);
      } else {
        _launchServer(modpack);
      }
    })
    .catch(function() {
      // Si la comprobación rápida falla por lo que sea, no se deja bloqueado el
      // arranque: se intenta de todas formas, apoyándose en la comprobación síncrona que
      // hace /api/server/start de todas formas.
      _launchServer(modpack);
    });
}

function recheckPendingModsThenStart(modpack) {
  document.getElementById('status-text').textContent = t('Comprobando mods pendientes…');

  var streamUrl = '/api/modpacks/' + encodeURIComponent(modpack) + '/pending-mods/stream';
  var checkSource = new EventSource(streamUrl);
  var settled = false;

  function finishCheck(pendingMods) {
    if (settled) {
      return;
    }
    settled = true;
    checkSource.close();
    if (pendingMods && pendingMods.length) {
      offerForceStart(
        modpack,
        t('Faltan estos mods porque su descarga automática falló: {mods}. Puedes instalarlos a mano en Modpacks → Mods.', { mods: pendingMods.join(', ') })
      );
      return;
    }
    _launchServer(modpack);
  }

  checkSource.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === 'progress') {
      document.getElementById('status-text').textContent =
        t('Comprobando mods pendientes… ({index} de {total})', { index: data.index, total: data.total });
    } else if (data.type === 'done') {
      finishCheck(data.pending_mods);
    }
  };
  checkSource.onerror = function() {
    // No se deja bloqueado el arranque por un stream caído: se sigue adelante,
    // apoyándose en la comprobación síncrona que hace /api/server/start de todas formas.
    finishCheck([]);
  };
}

// El aviso de mods pendientes nunca desaparece del todo (vuelve a salir en
// cada intento de arranque hasta que se instalen de verdad), pero no todo
// mod pendiente hace falta para jugar — puede ser opcional, o el admin ya
// sabe que no lo necesita. "Iniciar de todas formas" manda force=1 a
// /api/server/start, que se salta ESA comprobación puntual sin dejar de avisar
// la próxima vez.
function offerForceStart(modpack, message) {
  applyServerState(false, null);
  showConfirm(
    t('Mods pendientes de instalar'),
    message + ' ' + t('¿Quieres iniciar el servidor de todas formas?'),
    function() { _launchServer(modpack, true); },
    { icon: '⏳', confirmLabel: t('Iniciar de todas formas'), cancelLabel: t('Cancelar'), tone: 'yellow' }
  );
}

// La EULA de Minecraft la acepta una persona, nunca el panel por su cuenta
// (services/eula.py): si el servidor no la tiene, se enseña y se pide aceptarla.
function offerEula(modpack, force, url) {
  applyServerState(false, null);
  showConfirm(
    t('EULA de Minecraft'),
    t('Para arrancar un servidor de Minecraft hay que aceptar su EULA (el acuerdo de licencia de Mojang). Léela antes: al aceptarla, la aceptas tú como responsable de este servidor.'),
    function() {
      var form = new FormData();
      form.append('modpack', modpack);
      apiJson('/api/server/eula', { method: 'POST', body: form }).then(function(result) {
        if (result.ok) {
          _launchServer(modpack, force);
        } else {
          showToast(result.data.detail || t('No se pudo aceptar la EULA'), 'error');
        }
      });
    },
    { icon: '📜', confirmLabel: t('La he leído y la acepto'), cancelLabel: t('Cancelar'), tone: 'accent',
      link: { href: url, label: t('Leer la EULA de Minecraft') } }
  );
}

function _launchServer(modpack, force) {
  setHeroState('starting', t('Arrancando…'), modpack);

  var form = new FormData();
  form.append('modpack', modpack);
  if (force) {
    form.append('force', '1');
  }
  apiFetch('/api/server/start', { method: 'POST', body: form })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      if (result.ok) {
        document.getElementById('console').innerHTML = '';
        applyServerState(true, modpack);
      } else {
        applyServerState(false, null);
        if (result.data.eula_required) {
          offerEula(modpack, force, result.data.eula_url);
        } else if (result.data.pending_mods && result.data.pending_mods.length) {
          offerForceStart(modpack, result.data.detail);
        } else {
          showToast(result.data.detail || t('No se pudo iniciar el servidor'), 'error');
        }
      }
    })
    .catch(function(error) {
      showToast(error.message, 'error');
      applyServerState(false, null);
    });
}

// "Detener" manda el comando stop de Minecraft: guarda el mundo y echa a los
// jugadores con normalidad. La parada forzada (matar el proceso) queda como
// botón secundario para cuando el servidor no responde.
document.getElementById('clean-stop-btn').addEventListener('click', function() {
  var players = window._lastPlayersOnline || 0;
  var msg = t('Se guardará el mundo y se cerrará el servidor.');
  if (players > 0) {
    msg += ' ' + (players === 1 ? t('Ahora mismo hay 1 jugador conectado.') : t('Ahora mismo hay {n} jugadores conectados.', { n: players }));
  }
  showConfirm(t('¿Detener el servidor?'), msg, function() {
    sendServerCommand('stop').then(function(ok) {
      if (ok) {
        startupTracking = false;
        setHeroState('starting', t('Deteniendo…'), document.getElementById('status-modpack').textContent);
      }
    });
  }, { icon: '⏹', confirmLabel: t('Detener') });
});

document.getElementById('stop-btn').addEventListener('click', function() {
  showConfirm(
    t('¿Forzar la parada?'),
    t('Mata el proceso como Ctrl+C, sin esperar a que se guarde el mundo. Úsalo solo si «Detener» no responde.'),
    function() {
      busyWhile(document.getElementById('stop-btn'), function() {
        return apiFetch('/api/server/stop', { method: 'POST' }).catch(function() {});
      });
    },
    { confirmLabel: t('Forzar parada') }
  );
});

// Con el servidor parado no hay consola abierta que avise de que arranca: si
// lo enciende una tarea programada, el reinicio tras una caída u otra
// persona, se nota mirando el estado de vez en cuando.
setInterval(function() {
  if (serverRunning || document.hidden || !document.getElementById('login-screen').classList.contains('hidden')) {
    return;
  }
  apiFetch('/api/server/status')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.running && !serverRunning) {
        applyServerState(true, data.modpack, data.ready);
      }
    })
    .catch(function() {});
}, 15000);
