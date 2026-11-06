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
    .then(function(data) { applyServerState(data.running, data.modpack); })
    .catch(function() { applyServerState(false, null); });
}

// -- Cabecera de estado --------------------------------------------------------
// state: 'stopped' | 'starting' | 'running'. Es lo único que decide colores
// y botones de la cabecera (vía data-state en el CSS).
function setHeroState(state, statusText, name) {
  var hero = document.getElementById('server-hero');
  hero.dataset.state = state;
  document.getElementById('status-text').textContent = statusText;
  document.getElementById('status-modpack').textContent = name || 'Ningún servidor en marcha';
  var running = state === 'running';
  document.getElementById('clean-stop-btn').style.display = running ? '' : 'none';
  document.getElementById('stop-btn').style.display = running ? '' : 'none';
  hero.classList.toggle('has-metrics', running);
  if (state !== 'running') {
    document.getElementById('server-hero-meta').innerHTML = '';
  }
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
    parts.push('<span id="hero-uptime">' + icon('clock') + 'Encendido hace ' + formatUptime(currentUptime()) + '</span>');
  }
  if (mcDomain && netPublic) {
    parts.push('<span>' + icon('globe') + escHtml(mcDomain) + '</span>');
  }
  meta.innerHTML = parts.join('');
}

function formatUptime(seconds) {
  if (seconds < 60) {
    return 'menos de un minuto';
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

// uptime_seconds llega con cada /metrics (cada minuto); entre medias se
// cuenta en el navegador a partir del último valor recibido.
var uptimeBase = null;

function currentUptime() {
  return uptimeBase.seconds + Math.floor((Date.now() - uptimeBase.at) / 1000);
}

function applyServerState(running, modpack) {
  serverRunning = running;
  document.getElementById('server-picker').style.display = running ? 'none' : 'block';
  document.getElementById('console-card').style.display = running ? 'block' : 'none';
  document.getElementById('metrics-card').style.display = running ? '' : 'none';
  if (running) {
    setHeroState('running', 'En marcha', modpack);
    document.getElementById('console-modpack').textContent = modpack || '';
    if (!serverPackInfo[modpack]) {
      refreshServerPackInfo().then(function() { renderHeroMeta(modpack); });
    }
    renderHeroMeta(modpack);
    if (!sseSource) {
      startSSE();
    }
    startMetricsPolling();
  } else {
    setHeroState('stopped', 'Parado', null);
    if (sseSource) {
      sseSource.close();
      sseSource = null;
    }
    stopMetricsPolling();
    resetMetrics();
    loadServerPickList();
  }
}

function refreshServerPackInfo() {
  return apiFetch('/api/modpacks')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      serverPackInfo = {};
      (data.modpacks || []).forEach(function(pack) {
        serverPackInfo[pack.name] = pack;
      });
      return data.modpacks || [];
    });
}

function loadServerPickList() {
  var list = document.getElementById('server-pick-list');
  list.innerHTML = '<div class="skeleton-rows"><div></div><div></div></div>';
  refreshServerPackInfo()
    .then(function(packs) {
      if (!packs.length) {
        list.innerHTML = '<div class="empty-state">'
          + '<p>Aún no hay ningún servidor instalado.</p>'
          + '<button id="pick-empty-install">' + icon('package-plus') + 'Instalar un modpack</button>'
          + '</div>';
        document.getElementById('pick-empty-install').addEventListener('click', function() {
          document.getElementById('tab-deploy').click();
        });
        return;
      }
      list.innerHTML = '';
      packs.forEach(function(pack) {
        var element = document.createElement('div');
        element.className = 'server-pick-item' + (pack.start_script ? '' : ' no-script');
        var sub = [loaderTag(pack.modloader)];
        if (pack.mc_version) {
          sub.push('<span>Minecraft ' + escHtml(pack.mc_version) + '</span>');
        }
        if (pack.start_script) {
          sub.push('<span>' + escHtml(pack.start_script) + '</span>');
        } else {
          sub.push('<span class="server-pick-warn">No tiene script de arranque</span>');
        }
        if (pack.pending_mods && pack.pending_mods.length) {
          sub.push('<span class="server-pick-pending" title="' + escHtml(pack.pending_mods.join(', ')) + '">'
            + pack.pending_mods.length + (pack.pending_mods.length === 1 ? ' mod pendiente' : ' mods pendientes') + '</span>');
        }
        var startDisabled = pack.start_script ? '' : ' disabled';
        element.innerHTML = '<div>'
          + '<div class="server-pick-name">' + escHtml(pack.name) + '</div>'
          + '<div class="server-pick-sub">' + sub.join('') + '</div>'
          + '</div>'
          + '<button class="btn-secondary btn-sm"' + startDisabled + '>' + icon('play') + 'Iniciar</button>';
        if (pack.start_script) {
          element.querySelector('button').addEventListener('click', function() { startServer(pack.name); });
        }
        list.appendChild(element);
      });
    })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg error-msg">No se pudo cargar la lista de servidores. Recarga la página para reintentarlo.</p>';
    });
}


// ── Toggle público/LAN ────────────────────────────────────────────────────────
var netPublic = false;

function applyNetToggleUI(isPublic) {
  var track = document.getElementById('net-toggle-track');
  var label = document.getElementById('net-toggle-label');
  var desc = document.getElementById('net-toggle-desc');
  track.setAttribute('aria-checked', isPublic ? 'true' : 'false');
  if (isPublic) {
    track.classList.add('on');
    label.textContent = 'Abierto a internet';
    if (mcDomain) {
      desc.textContent = 'Se puede entrar desde fuera de casa en ' + mcDomain + ':25565';
    } else {
      desc.textContent = 'Se puede entrar desde fuera de casa';
    }
  } else {
    track.classList.remove('on');
    label.textContent = 'Solo red local';
    desc.textContent = 'Solo se puede entrar desde tu red de casa (192.168.1.x)';
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
        label.textContent = 'Acceso desde fuera: no disponible aquí';
        desc.textContent = 'En Docker, el acceso público o solo LAN se controla desde el mapeo de puertos de docker-compose.yml.';
        return;
      }
      track.classList.remove('disabled');
      track.style.pointerEvents = '';
      track.removeAttribute('aria-disabled');
      netPublic = (data.mode === 'public');
      applyNetToggleUI(netPublic);
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
        applyNetToggleUI(netPublic);
        if (netPublic) {
          showToast('Servidor abierto a internet', 'success');
        } else {
          showToast('Servidor limitado a la red local', 'success');
        }
      } else {
        showToast('No se pudo cambiar el firewall: ' + (result.data.detail || 'error desconocido'), 'error');
      }
    })
    .catch(function(error) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      showToast('Error de red: ' + error.message, 'error');
    });
}

document.getElementById('net-toggle-track').addEventListener('click', toggleNetMode);
document.getElementById('net-toggle-track').addEventListener('keydown', function(event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleNetMode();
  }
});

// Antes de arrancar se hace un chequeo rápido (GET /pending-mods, solo lee un
// JSON) de si queda algo pendiente. Si no hay nada, se arranca directo sin
// más — pero si SÍ hay algo, puede que ya se haya resuelto por una vía que la
// app no ve sola (un mod copiado a mano por SFTP en vez de subido desde el
// panel), así que se dispara un re-chequeo completo con progreso (SSE: abre
// cada mod instalado para comparar su mod_id/versión real) antes de decidir
// si de verdad hay que bloquear el arranque. Por eso la ruedita de "Comprobando
// mods pendientes..." solo aparece cuando hacía falta — el caso normal (sin
// nada pendiente) arranca sin ningún paso extra.
function startServer(modpack) {
  setHeroState('starting', 'Preparando…', modpack);
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
      // Si el chequeo rápido falla por lo que sea, no se deja bloqueado el
      // arranque: se intenta igual, apoyándose en el chequeo síncrono que
      // hace /api/server/start de todas formas.
      _launchServer(modpack);
    });
}

function recheckPendingModsThenStart(modpack) {
  document.getElementById('status-text').textContent = 'Comprobando mods pendientes…';

  var streamUrl = '/api/modpacks/' + encodeURIComponent(modpack) + '/pending-mods/stream?token=' + encodeURIComponent(authToken);
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
        'Faltan estos mods porque su descarga automática falló: ' + pendingMods.join(', ')
          + '. Puedes instalarlos a mano en Gestión de modpacks → Mods.'
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
        'Comprobando mods pendientes… (' + data.index + ' de ' + data.total + ')';
    } else if (data.type === 'done') {
      finishCheck(data.pending_mods);
    }
  };
  checkSource.onerror = function() {
    // No se deja bloqueado el arranque por un stream caído: se sigue igual,
    // apoyándose en el chequeo síncrono que hace /api/server/start de todas formas.
    finishCheck([]);
  };
}

// El aviso de mods pendientes nunca desaparece del todo (vuelve a salir en
// cada intento de arranque hasta que se instalen de verdad), pero no todo
// mod pendiente hace falta para jugar — puede ser opcional, o el admin ya
// sabe que no lo necesita. "Iniciar de todas formas" manda force=1 a
// /api/server/start, que se salta ESE chequeo puntual sin dejar de avisar
// la próxima vez.
function offerForceStart(modpack, message) {
  applyServerState(false, null);
  showConfirm(
    'Mods pendientes de instalar',
    message + ' ¿Quieres iniciar el servidor de todas formas?',
    function() { _launchServer(modpack, true); },
    { icon: '⏳', confirmLabel: 'Iniciar de todas formas', cancelLabel: 'Cancelar', confirmColor: 'var(--yellow)' }
  );
}

function _launchServer(modpack, force) {
  setHeroState('starting', 'Arrancando…', modpack);

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
        if (result.data.pending_mods && result.data.pending_mods.length) {
          offerForceStart(modpack, result.data.detail);
        } else {
          showToast(result.data.detail || 'No se pudo iniciar el servidor', 'error');
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
  var msg = 'Se guardará el mundo y se cerrará el servidor.';
  if (players > 0) {
    msg += ' Ahora mismo hay ' + players + (players === 1 ? ' jugador conectado.' : ' jugadores conectados.');
  }
  showConfirm('¿Detener el servidor?', msg, function() {
    sendServerCommand('stop').then(function(ok) {
      if (ok) {
        document.getElementById('server-hero').dataset.state = 'starting';
        document.getElementById('status-text').textContent = 'Deteniendo…';
      }
    });
  }, { icon: '⏹', confirmLabel: 'Detener' });
});

document.getElementById('stop-btn').addEventListener('click', function() {
  showConfirm(
    '¿Forzar la parada?',
    'Mata el proceso como Ctrl+C, sin esperar a que se guarde el mundo. Úsalo solo si «Detener» no responde.',
    function() { apiFetch('/api/server/stop', { method: 'POST' }).catch(function() {}); },
    { confirmLabel: 'Forzar parada' }
  );
});

// -- Consola ---------------------------------------------------------------------
var cmdHistory = [];
var cmdHistoryPos = 0;

document.getElementById('cmd-send-btn').addEventListener('click', sendCommand);
document.getElementById('cmd-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    sendCommand();
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    // Historial de comandos como en una terminal: ↑ el anterior, ↓ el siguiente.
    if (!cmdHistory.length) {
      return;
    }
    event.preventDefault();
    cmdHistoryPos += event.key === 'ArrowUp' ? -1 : 1;
    cmdHistoryPos = Math.max(0, Math.min(cmdHistory.length, cmdHistoryPos));
    this.value = cmdHistory[cmdHistoryPos] || '';
  }
});

function sendCommand() {
  var input = document.getElementById('cmd-input');
  var cmd = input.value.trim();
  if (!cmd) {
    return;
  }
  input.value = '';
  if (cmdHistory[cmdHistory.length - 1] !== cmd) {
    cmdHistory.push(cmd);
    if (cmdHistory.length > 50) {
      cmdHistory.shift();
    }
  }
  cmdHistoryPos = cmdHistory.length;
  sendServerCommand(cmd);
}

function sendServerCommand(cmd) {
  var form = new FormData();
  form.append('cmd', cmd);
  appendConsoleNode('> ' + cmd, 'log-cmd');
  return apiFetch('/api/server/command', { method: 'POST', body: form })
    .then(function(response) {
      if (!response.ok) {
        showToast('El servidor no aceptó el comando', 'error');
      }
      return response.ok;
    })
    .catch(function() {
      showToast('No se pudo enviar el comando', 'error');
      return false;
    });
}

function startSSE() {
  sseSource = new EventSource('/api/server/logs?token=' + encodeURIComponent(authToken));
  sseSource.onmessage = function(event) {
    if (event.data === '__STOPPED__') {
      applyServerState(false, null);
      return;
    }
    appendLine(event.data);
  };
  sseSource.onerror = function() {
    setTimeout(function() {
      if (serverRunning && !sseSource) {
        startSSE();
      }
    }, 3000);
  };
}

// Formato típico de Forge/NeoForge/Fabric/vanilla:
//   [14:02:15] [Server thread/INFO] [net.minecraft.server.Main/]: mensaje
// La hora y el origen se atenúan para que destaque el mensaje; el nivel
// decide el color de toda la línea.
var LOG_LINE_RE = /^(\[[0-9:.]+\])(\s*\[[^\]]*\/(INFO|WARN|ERROR|FATAL|DEBUG)\](?:\s*\[[^\]]*\])?:?)?(.*)$/;

function appendLine(line) {
  // Restos de colores ANSI: con el ESC delante, o ya sin él pero siempre con
  // al menos un número ("[0m", "[32;1m"). Sin exigir el número, "[m" se
  // comía el principio de "[main/INFO]" o "[mixin/]".
  var clean = line.replace(/\x1b\[[0-9;]*m|\[[0-9;]+m/g, '');
  var lineLower = clean.toLowerCase();
  var match = clean.match(LOG_LINE_RE);
  var level = match && match[3];
  var cls = '';
  if (level === 'ERROR' || level === 'FATAL' || (!level && (lineLower.indexOf('error') !== -1 || lineLower.indexOf('exception') !== -1))) {
    cls = 'log-error';
  } else if (level === 'WARN' || (!level && lineLower.indexOf('warn') !== -1)) {
    cls = 'log-warn';
  } else if (/done \(|joined the game|left the game/.test(lineLower)) {
    cls = 'log-done';
  }
  var div = appendConsoleNode(null, cls);
  if (match && match[2]) {
    var ts = document.createElement('span');
    ts.className = 'ts';
    ts.textContent = match[1];
    var src = document.createElement('span');
    src.className = 'src';
    src.textContent = match[2];
    div.appendChild(ts);
    div.appendChild(src);
    div.appendChild(document.createTextNode(match[4]));
  } else {
    div.textContent = clean;
  }
  scrollConsoleIfFollowing();
}

function appendConsoleNode(text, cls) {
  var consoleEl = document.getElementById('console');
  var div = document.createElement('div');
  if (cls) {
    div.className = cls;
  }
  if (text !== null) {
    div.textContent = text;
  }
  consoleEl.appendChild(div);
  var excess = consoleEl.children.length - 800;
  for (var i = 0; i < excess; i++) {
    consoleEl.removeChild(consoleEl.firstChild);
  }
  if (text !== null) {
    scrollConsoleIfFollowing();
  }
  return div;
}

function scrollConsoleIfFollowing() {
  if (document.getElementById('console-follow').checked) {
    var consoleEl = document.getElementById('console');
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}


// -- Metrics ------------------------------------------------------------------
var metricsTimer = null;
// Últimas muestras de TPS/MSPT para las líneas de evolución (una por
// consulta, cada minuto: 30 muestras = la última media hora).
var metricsHistory = { tps: [], mspt: [] };

function startMetricsPolling() {
  fetchMetrics();
  if (!metricsTimer) {
    metricsTimer = setInterval(fetchMetrics, 60000);
  }
  _startRelativeTicker();
}

function stopMetricsPolling() {
  if (metricsTimer) {
    clearInterval(metricsTimer);
    metricsTimer = null;
  }
  _stopRelativeTicker();
}

function fetchMetrics() {
  apiFetch('/api/server/metrics')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      updateMetricsUI(data);
      apiFetch('/api/server/metrics/refresh', { method: 'POST' }).catch(function() {});
    })
    .catch(function() {});
}

function resetMetrics() {
  ['mv-tps', 'mv-mspt', 'mv-players', 'mv-ram'].forEach(function(id) {
    document.getElementById(id).textContent = '—';
  });
  ['mvd-tps', 'mvd-mspt', 'metrics-updated'].forEach(function(id) {
    document.getElementById(id).textContent = '';
  });
  document.getElementById('metrics-players-list').innerHTML = '';
  document.getElementById('mb-ram').style.width = '0';
  document.getElementById('spark-tps').innerHTML = '';
  document.getElementById('spark-mspt').innerHTML = '';
  window._metricsLastFetch = null;
  window._lastPlayersOnline = 0;
  uptimeBase = null;
  metricsHistory = { tps: [], mspt: [] };
  ['mc-tps', 'mc-mspt'].forEach(function(id) {
    document.getElementById(id).className = 'metric';
  });
}

// Umbrales: TPS 20 es perfecto, por debajo de 15 se nota el lag; MSPT por
// encima de 50 ms ya no da tiempo a 20 ticks por segundo.
function rateMetric(kind, value) {
  if (kind === 'tps') {
    if (value >= 19) {
      return ['good', 'fluido'];
    }
    return value >= 15 ? ['warn', 'algo de lag'] : ['bad', 'mucho lag'];
  }
  if (value <= 50) {
    return ['good', 'con margen'];
  }
  return value <= 100 ? ['warn', 'justo'] : ['bad', 'sobrecargado'];
}

function renderMetric(kind, value) {
  var card = document.getElementById('mc-' + kind);
  var valueEl = document.getElementById('mv-' + kind);
  var verdictEl = document.getElementById('mvd-' + kind);
  if (value === null || value === undefined) {
    valueEl.textContent = '—';
    verdictEl.textContent = '';
    card.className = 'metric';
    return;
  }
  var rating = rateMetric(kind, value);
  valueEl.textContent = value.toFixed(1);
  verdictEl.textContent = rating[1];
  card.className = 'metric ' + rating[0];
  var history = metricsHistory[kind];
  history.push(value);
  if (history.length > 30) {
    history.shift();
  }
  renderSpark(document.getElementById('spark-' + kind), history, kind === 'tps' ? [0, 20] : null);
}

function renderSpark(svg, values, range) {
  if (values.length < 2) {
    svg.innerHTML = '';
    return;
  }
  var min = range ? range[0] : Math.min.apply(null, values);
  var max = range ? range[1] : Math.max.apply(null, values);
  if (max - min < 1) {
    max = min + 1;
  }
  var step = 100 / (values.length - 1);
  var points = values.map(function(v, i) {
    var y = 22 - ((Math.min(Math.max(v, min), max) - min) / (max - min)) * 20;
    return (i * step).toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  svg.innerHTML = '<polyline points="' + points + '"/>';
}

function updateMetricsUI(data) {
  var players = data.players_online || [];
  window._lastPlayersOnline = players.length;
  document.getElementById('mv-players').innerHTML = players.length
    + ' <small>de ' + (data.players_max || '?') + '</small>';
  document.getElementById('metrics-players-list').innerHTML = players.map(function(playerName) {
    return '<span class="player-chip">' + escHtml(playerName) + '</span>';
  }).join('');

  renderMetric('tps', data.tps);
  renderMetric('mspt', data.mspt);

  var ramEl = document.getElementById('mv-ram');
  var ramBar = document.getElementById('mb-ram');
  if (data.ram_used_mb && data.ram_max_mb) {
    var pct = Math.min(100, (data.ram_used_mb / data.ram_max_mb) * 100);
    ramEl.innerHTML = (data.ram_used_mb / 1024).toFixed(1)
      + ' <small>de ' + (data.ram_max_mb / 1024).toFixed(1) + ' GB</small>';
    ramBar.style.width = pct.toFixed(0) + '%';
    ramBar.classList.toggle('high', pct >= 90);
  } else {
    ramEl.textContent = '—';
    ramBar.style.width = '0';
  }

  if (data.uptime_seconds !== null && data.uptime_seconds !== undefined) {
    uptimeBase = { seconds: data.uptime_seconds, at: Date.now() };
  }
  renderHeroMeta(document.getElementById('status-modpack').textContent);

  var rconWarning = document.getElementById('rcon-warning');
  if (data.rcon_status && data.rcon_status !== 'ok') {
    rconWarning.textContent = 'No se pueden leer TPS y MSPT (RCON: ' + data.rcon_status + ').';
    rconWarning.style.display = 'block';
  } else {
    rconWarning.style.display = 'none';
  }

  window._metricsLastFetch = Date.now();
}

function _startRelativeTicker() {
  if (window._relativeTickerTimer) {
    return;
  }
  window._relativeTickerTimer = setInterval(function() {
    var uptimeEl = document.getElementById('hero-uptime');
    if (uptimeEl && uptimeBase) {
      uptimeEl.innerHTML = icon('clock') + 'Encendido hace ' + formatUptime(currentUptime());
    }
    var el = document.getElementById('metrics-updated');
    if (!el || !window._metricsLastFetch) {
      return;
    }
    var sec = Math.floor((Date.now() - window._metricsLastFetch) / 1000);
    var timeText;
    if (sec < 5) {
      timeText = 'ahora mismo';
    } else if (sec < 60) {
      timeText = 'hace ' + sec + ' s';
    } else if (sec < 3600) {
      timeText = 'hace ' + Math.floor(sec / 60) + ' min';
    } else {
      timeText = 'hace ' + Math.floor(sec / 3600) + ' h';
    }
    el.textContent = 'Actualizado ' + timeText;
  }, 1000);
}

function _stopRelativeTicker() {
  if (window._relativeTickerTimer) {
    clearInterval(window._relativeTickerTimer);
    window._relativeTickerTimer = null;
  }
}

document.getElementById('btn-refresh-metrics').addEventListener('click', function() {
  fetchMetrics();
  apiFetch('/api/server/metrics/refresh', { method: 'POST' }).catch(function() {});
});
