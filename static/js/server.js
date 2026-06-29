// -- Servidor -----------------------------------------------------------------
var sseSource = null;
var serverRunning = false;

function checkServerStatus() {
  apiFetch('/api/server/status')
    .then(function(r) { return r.json(); })
    .then(function(d) { applyServerState(d.running, d.modpack); })
    .catch(function() { applyServerState(false, null); });
}

function applyServerState(running, modpack) {
  serverRunning = running;
  var dot = document.getElementById('status-dot');
  document.getElementById('status-modpack').textContent = running && modpack ? '— ' + modpack : '';
  document.getElementById('stop-btn').style.display = running ? '' : 'none';
  document.getElementById('server-picker').style.display = running ? 'none' : 'block';
  document.getElementById('console-card').style.display = running ? 'block' : 'none';
  document.getElementById('metrics-card').style.display = running ? 'block' : 'none';
  if (running) {
    dot.className = 'status-dot running';
    document.getElementById('status-text').textContent = 'Servidor en marcha';
    document.getElementById('console-modpack').textContent = modpack || '';
    if (!sseSource) startSSE();
    startMetricsPolling();
  } else {
    dot.className = 'status-dot';
    document.getElementById('status-text').textContent = 'Sin servidor activo';
    if (sseSource) {
      sseSource.close();
      sseSource = null;
    }
    stopMetricsPolling();
    resetMetrics();
    loadServerPickList();
  }
}

function loadServerPickList() {
  var list = document.getElementById('server-pick-list');
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var packs = d.modpacks;
      if (!packs || !packs.length) {
        list.innerHTML = '<p class="empty-msg">No hay modpacks instalados</p>';
        return;
      }
      list.innerHTML = '';
      packs.forEach(function(p) {
        var el = document.createElement('div');
        el.className = 'server-pick-item' + (p.start_script ? '' : ' no-script');
        var scriptLabel = p.start_script
          ? '<span style="font-size:.72rem;color:var(--muted)">' + p.start_script + '</span>'
          : '<span style="font-size:.72rem;color:var(--red)">sin script de arranque</span>';
        var verLabel = (p.mc_version || p.modloader)
          ? '<span style="font-size:.72rem;color:var(--accent);margin-left:6px">'
            + (p.mc_version ? 'MC ' + p.mc_version : '')
            + (p.mc_version && p.modloader ? ' · ' : '')
            + (p.modloader || '') + '</span>'
          : '';
        el.innerHTML = '<span style="font-size:1.3rem">🗂️</span>'
          + '<div style="flex:1">'
          + '<div style="font-weight:600">' + p.name + '</div>'
          + '<div style="margin-top:2px">' + scriptLabel + verLabel + '</div>'
          + '</div>'
          + '<button style="padding:6px 14px;font-size:.82rem"' + (p.start_script ? '' : ' disabled') + '>▶ Iniciar</button>';
        if (p.start_script) {
          el.querySelector('button').addEventListener('click', function() { startServer(p.name); });
        }
        list.appendChild(el);
      });
    })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg" style="color:var(--red)">Error</p>';
    });
}


// ── Toggle público/LAN ────────────────────────────────────────────────────────
var netPublic = false;

function applyNetToggleUI(isPublic) {
  var track = document.getElementById('net-toggle-track');
  var label = document.getElementById('net-toggle-label');
  var desc  = document.getElementById('net-toggle-desc');
  if (isPublic) {
    track.classList.add('on');
    label.textContent = '🌐 Público';
    desc.textContent  = 'Accesible desde internet · mc.pabloesteban.org:25565';
  } else {
    track.classList.remove('on');
    label.textContent = '🏠 Solo LAN';
    desc.textContent  = 'Solo accesible desde tu red local (192.168.1.x)';
  }
}

function loadFirewallStatus() {
  apiFetch('/api/firewall/status')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      netPublic = (d.mode === 'public');
      applyNetToggleUI(netPublic);
    })
    .catch(function() {});
}

document.getElementById('net-toggle-track').addEventListener('click', function() {
  var newMode = netPublic ? 'lan' : 'public';
  var track = document.getElementById('net-toggle-track');
  track.style.opacity = '0.5';
  track.style.pointerEvents = 'none';
  var form = new FormData();
  form.append('mode', newMode);
  apiFetch('/api/firewall/set', { method: 'POST', body: form })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      if (res.ok) {
        netPublic = (res.d.mode === 'public');
        applyNetToggleUI(netPublic);
        showToast(netPublic ? '🌐 Firewall: acceso público activado' : '🏠 Firewall: solo LAN', 'success');
      } else {
        showToast('Error: ' + (res.d.detail || 'no se pudo cambiar el firewall'), 'error');
      }
    })
    .catch(function(e) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      showToast('Error de red: ' + e.message, 'error');
    });
});

function startServer(modpack) {
  var dot = document.getElementById('status-dot');
  dot.className = 'status-dot starting';
  document.getElementById('status-text').textContent = 'Iniciando ' + modpack + '...';
  document.getElementById('server-picker').style.display = 'none';

  var form = new FormData();
  form.append('modpack', modpack);
  apiFetch('/api/server/start', { method: 'POST', body: form })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      if (res.ok) {
        document.getElementById('console').innerHTML = '';
        applyServerState(true, modpack);
      } else {
        showToast(res.d.detail || 'Error al iniciar', 'error');
        applyServerState(false, null);
      }
    })
    .catch(function(e) {
      showToast(e.message, 'error');
      applyServerState(false, null);
    });
}

document.getElementById('stop-btn').addEventListener('click', function() {
  showConfirm(
    'Forzar parada del servidor',
    'Esto equivale a Ctrl+C. Usa "stop" en la consola para un cierre limpio.',
    function() { apiFetch('/api/server/stop', { method: 'POST' }).catch(function() {}); }
  );
});

document.getElementById('cmd-send-btn').addEventListener('click', sendCommand);
document.getElementById('cmd-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') sendCommand();
});

function sendCommand() {
  var input = document.getElementById('cmd-input');
  var cmd = input.value.trim();
  if (!cmd) return;
  input.value = '';
  var form = new FormData();
  form.append('cmd', cmd);
  apiFetch('/api/server/command', { method: 'POST', body: form })
    .catch(function() { showToast('Error al enviar comando', 'error'); });
}

function startSSE() {
  sseSource = new EventSource('/api/server/logs?token=' + encodeURIComponent(authToken));
  sseSource.onmessage = function(e) {
    if (e.data === '__STOPPED__') {
      applyServerState(false, null);
      return;
    }
    appendLine(e.data);
  };
  sseSource.onerror = function() {
    setTimeout(function() {
      if (serverRunning && !sseSource) startSSE();
    }, 3000);
  };
}

function appendLine(line) {
  var el = document.getElementById('console');
  if (!el) return;
  var div = document.createElement('div');
  var clean = line.replace(/\[[0-9;]*m/g, '');
  var low = clean.toLowerCase();
  if (low.indexOf('error') !== -1 || low.indexOf('exception') !== -1) {
    div.className = 'log-error';
  } else if (low.indexOf('warn') !== -1) {
    div.className = 'log-warn';
  } else if (low.indexOf('done') !== -1 || low.indexOf('joined') !== -1 || low.indexOf('left') !== -1) {
    div.className = 'log-done';
  } else if (low.indexOf('loading') !== -1 || low.indexOf('starting') !== -1) {
    div.className = 'log-info';
  }
  div.textContent = clean;
  el.appendChild(div);
  while (el.children.length > 800) el.removeChild(el.firstChild);
  el.scrollTop = el.scrollHeight;
}


// -- Metrics ------------------------------------------------------------------
var metricsTimer = null;

function startMetricsPolling() {
  fetchMetrics();
  if (!metricsTimer) metricsTimer = setInterval(fetchMetrics, 60000);
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
    .then(function(r) { return r.json(); })
    .then(function(d) {
      updateMetricsUI(d);
      if (d.spark_available) {
        apiFetch('/api/server/metrics/refresh', { method: 'POST' }).catch(function() {});
      }
    })
    .catch(function() {});
}

function resetMetrics() {
  ['mv-tps', 'mv-mspt', 'mv-cpu-proc', 'mv-cpu-sys'].forEach(function(id) {
    document.getElementById(id).textContent = '—';
  });
  document.getElementById('metrics-updated').textContent = '';
  window._metricsLastFetch = null;
  document.getElementById('metrics-players-row').style.display = 'none';
  document.getElementById('metrics-grid-spark').style.display = 'none';
  document.getElementById('spark-badge').style.display = 'none';
  ['mc-tps', 'mc-mspt', 'mc-cpu-proc', 'mc-cpu-sys'].forEach(function(id) {
    document.getElementById(id).className = 'metric-card';
  });
}

function updateMetricsUI(d) {
  var players = d.players_online || [];
  var playersRow = document.getElementById('metrics-players-row');
  if (players.length) {
    playersRow.style.display = 'block';
    document.getElementById('metrics-players-list').innerHTML = players.map(function(p) {
      return '<span class="player-chip">👤 ' + escHtml(p) + '</span>';
    }).join('');
  } else {
    playersRow.style.display = 'none';
  }

  var sparkGrid = document.getElementById('metrics-grid-spark');
  var sparkBadge = document.getElementById('spark-badge');
  if (d.spark_available) {
    sparkGrid.style.display = '';
    sparkBadge.style.display = 'block';
    var tps = d.tps;
    var tpsEl = document.getElementById('mv-tps');
    var tpsCard = document.getElementById('mc-tps');
    if (tps !== null && tps !== undefined) {
      tpsEl.textContent = tps.toFixed(1);
      tpsCard.className = 'metric-card ' + (tps >= 19 ? 'good' : tps >= 15 ? 'warn' : 'bad');
    } else {
      tpsEl.textContent = '—';
      tpsCard.className = 'metric-card';
    }
    var mspt = d.mspt;
    var msptEl = document.getElementById('mv-mspt');
    var msptCard = document.getElementById('mc-mspt');
    if (mspt !== null && mspt !== undefined) {
      msptEl.textContent = mspt.toFixed(1);
      msptCard.className = 'metric-card ' + (mspt <= 50 ? 'good' : mspt <= 100 ? 'warn' : 'bad');
    } else {
      msptEl.textContent = '—';
      msptCard.className = 'metric-card';
    }
    var cpuProc = d.cpu_process;
    var cpuProcEl = document.getElementById('mv-cpu-proc');
    var cpuProcCard = document.getElementById('mc-cpu-proc');
    if (cpuProc !== null && cpuProc !== undefined) {
      cpuProcEl.textContent = cpuProc + '%';
      cpuProcCard.className = 'metric-card ' + (cpuProc < 50 ? 'good' : cpuProc < 80 ? 'warn' : 'bad');
    } else {
      cpuProcEl.textContent = '—';
      cpuProcCard.className = 'metric-card';
    }
    var cpuSys = d.cpu_system;
    var cpuSysEl = document.getElementById('mv-cpu-sys');
    if (cpuSys !== null && cpuSys !== undefined) {
      cpuSysEl.textContent = cpuSys + '%';
    } else {
      cpuSysEl.textContent = '—';
    }
  } else {
    sparkGrid.style.display = 'none';
    sparkBadge.style.display = 'none';
  }

  window._metricsLastFetch = Date.now();
}

function _startRelativeTicker() {
  if (window._relativeTickerTimer) return;
  window._relativeTickerTimer = setInterval(function() {
    var el = document.getElementById('metrics-updated');
    if (!el || !window._metricsLastFetch) return;
    var sec = Math.floor((Date.now() - window._metricsLastFetch) / 1000);
    var txt;
    if (sec < 5) txt = 'ahora mismo';
    else if (sec < 60) txt = 'hace ' + sec + 's';
    else if (sec < 3600) txt = 'hace ' + Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
    else txt = 'hace ' + Math.floor(sec / 3600) + 'h';
    el.textContent = 'Actualizado ' + txt;
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
