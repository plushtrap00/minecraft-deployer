// Métricas del servidor en marcha (página Servidor): TPS, MSPT, jugadores y
// RAM, con sus líneas de evolución. Las gráficas de 24 h / 7 días están en
// history_charts.js.

// -- Métricas ------------------------------------------------------------------
var metricsTimer = null;
// Últimas muestras de TPS/MSPT para las líneas de evolución (una por
// consulta, cada minuto: 30 muestras = la última media hora).
var metricsHistory = { tps: [], mspt: [] };

// Si el servidor está en marcha se quieren métricas, pero mientras la
// pestaña del navegador no se ve se pausan los temporizadores (no tiene
// sentido pedir datos ni repintar nada que nadie mira) y al volver se pide
// una medida nueva al momento.
var metricsWanted = false;

function startMetricsPolling() {
  metricsWanted = true;
  if (document.hidden) {
    return;
  }
  fetchMetrics();
  if (!metricsTimer) {
    metricsTimer = setInterval(fetchMetrics, 60000);
  }
  _startRelativeTicker();
}

function pauseMetricsPolling() {
  if (metricsTimer) {
    clearInterval(metricsTimer);
    metricsTimer = null;
  }
  _stopRelativeTicker();
}

function stopMetricsPolling() {
  metricsWanted = false;
  pauseMetricsPolling();
}

document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    pauseMetricsPolling();
  } else if (metricsWanted) {
    startMetricsPolling();
  }
});

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
    var el = document.getElementById(id);
    el.textContent = '—';
    delete el.dataset.num;
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
    delete valueEl.dataset.num;
    verdictEl.textContent = '';
    card.className = 'metric';
    return;
  }
  var rating = rateMetric(kind, value);
  animateNumber(valueEl, value, 1);
  verdictEl.textContent = rating[1];
  card.className = 'metric ' + rating[0];
  var history = metricsHistory[kind];
  history.push(value);
  if (history.length > 30) {
    history.shift();
  }
  renderSpark(document.getElementById('spark-' + kind), history, kind === 'tps' ? [0, 20] : null);
}

// Línea de evolución con el área de debajo rellena (ver .metric-spark).
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
  svg.innerHTML = '<polygon points="0,24 ' + points + ' 100,24"/><polyline points="' + points + '"/>';
}

function updateMetricsUI(data) {
  var players = data.players_online || [];
  window._lastPlayersOnline = players.length;
  animateNumber(document.getElementById('mv-players'), players.length, 0, ' <small>de ' + (data.players_max || '?') + '</small>');
  document.getElementById('metrics-players-list').innerHTML = players.map(function(playerName) {
    return '<span class="player-chip">' + headHtml(playerName, null, 'sm') + escHtml(playerName) + '</span>';
  }).join('');
  if (players.length >= 5) {
    unlockAchievement('full-house');
  }
  if (players.length && Number(data.players_max) > 0 && players.length >= Number(data.players_max)) {
    unlockAchievement('sold-out');
  }
  if (data.uptime_seconds >= 86400) {
    unlockAchievement('marathon');
  }
  if (players.length && data.tps !== null && data.tps !== undefined && data.tps >= 19.95) {
    unlockAchievement('smooth');
  }
  // TPS solo se puede leer con el servidor ya listo: si se llegó a perder
  // el «Done» de la consola, esto lo corrige.
  if (startupTracking && ((data.tps !== null && data.tps !== undefined) || players.length)) {
    markServerReady(false);
  }

  renderMetric('tps', data.tps);
  renderMetric('mspt', data.mspt);

  var ramEl = document.getElementById('mv-ram');
  var ramBar = document.getElementById('mb-ram');
  if (data.ram_used_mb && data.ram_max_mb) {
    var pct = Math.min(100, (data.ram_used_mb / data.ram_max_mb) * 100);
    animateNumber(ramEl, data.ram_used_mb / 1024, 1, ' <small>de ' + (data.ram_max_mb / 1024).toFixed(1) + ' GB</small>');
    ramBar.style.width = pct.toFixed(0) + '%';
    ramBar.classList.toggle('high', pct >= 90);
  } else {
    ramEl.textContent = '—';
    delete ramEl.dataset.num;
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
