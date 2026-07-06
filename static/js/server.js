// -- Servidor -----------------------------------------------------------------
var sseSource = null;
var serverRunning = false;
var mcDomain = '';

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

function applyServerState(running, modpack) {
  serverRunning = running;
  var dot = document.getElementById('status-dot');
  if (running && modpack) {
    document.getElementById('status-modpack').textContent = '— ' + modpack;
  } else {
    document.getElementById('status-modpack').textContent = '';
  }
  document.getElementById('stop-btn').style.display = running ? '' : 'none';
  document.getElementById('server-picker').style.display = running ? 'none' : 'block';
  document.getElementById('console-card').style.display = running ? 'block' : 'none';
  document.getElementById('metrics-card').style.display = running ? 'block' : 'none';
  if (running) {
    dot.className = 'status-dot running';
    document.getElementById('status-text').textContent = 'Servidor en marcha';
    document.getElementById('console-modpack').textContent = modpack || '';
    if (!sseSource) {
      startSSE();
    }
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
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var packs = data.modpacks;
      if (!packs || !packs.length) {
        list.innerHTML = '<p class="empty-msg">No hay modpacks instalados</p>';
        return;
      }
      list.innerHTML = '';
      packs.forEach(function(pack) {
        var element = document.createElement('div');
        element.className = 'server-pick-item' + (pack.start_script ? '' : ' no-script');
        var scriptLabel;
        if (pack.start_script) {
          scriptLabel = '<span style="font-size:.72rem;color:var(--muted)">' + pack.start_script + '</span>';
        } else {
          scriptLabel = '<span style="font-size:.72rem;color:var(--red)">sin script de arranque</span>';
        }
        var verLabel = '';
        if (pack.mc_version || pack.modloader) {
          verLabel = '<span style="font-size:.72rem;color:var(--accent);margin-left:6px">'
            + (pack.mc_version ? 'MC ' + pack.mc_version : '')
            + (pack.mc_version && pack.modloader ? ' · ' : '')
            + (pack.modloader || '') + '</span>';
        }
        var startDisabled = pack.start_script ? '' : ' disabled';
        element.innerHTML = '<span style="font-size:1.3rem">🗂️</span>'
          + '<div style="flex:1">'
          + '<div style="font-weight:600">' + pack.name + '</div>'
          + '<div style="margin-top:2px">' + scriptLabel + verLabel + '</div>'
          + '</div>'
          + '<button style="padding:6px 14px;font-size:.82rem"' + startDisabled + '>▶ Iniciar</button>';
        if (pack.start_script) {
          element.querySelector('button').addEventListener('click', function() { startServer(pack.name); });
        }
        list.appendChild(element);
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
  var desc = document.getElementById('net-toggle-desc');
  if (isPublic) {
    track.classList.add('on');
    label.textContent = '🌐 Público';
    if (mcDomain) {
      desc.textContent = 'Accesible desde internet · ' + mcDomain + ':25565';
    } else {
      desc.textContent = 'Accesible desde internet';
    }
  } else {
    track.classList.remove('on');
    label.textContent = '🏠 Solo LAN';
    desc.textContent = 'Solo accesible desde tu red local (192.168.1.x)';
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
        label.textContent = '🔒 No disponible';
        desc.textContent = 'En Docker, el acceso público/LAN se controla desde el mapeo de puertos de docker-compose.yml, no desde aquí.';
        return;
      }
      track.classList.remove('disabled');
      track.style.pointerEvents = '';
      netPublic = (data.mode === 'public');
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
          showToast('🌐 Firewall: acceso público activado', 'success');
        } else {
          showToast('🏠 Firewall: solo LAN', 'success');
        }
      } else {
        showToast('Error: ' + (result.data.detail || 'no se pudo cambiar el firewall'), 'error');
      }
    })
    .catch(function(error) {
      track.style.opacity = '';
      track.style.pointerEvents = '';
      showToast('Error de red: ' + error.message, 'error');
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
        showToast(result.data.detail || 'Error al iniciar', 'error');
        applyServerState(false, null);
      }
    })
    .catch(function(error) {
      showToast(error.message, 'error');
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
document.getElementById('cmd-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    sendCommand();
  }
});

function sendCommand() {
  var input = document.getElementById('cmd-input');
  var cmd = input.value.trim();
  if (!cmd) {
    return;
  }
  input.value = '';
  var form = new FormData();
  form.append('cmd', cmd);
  apiFetch('/api/server/command', { method: 'POST', body: form })
    .catch(function() { showToast('Error al enviar comando', 'error'); });
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

function appendLine(line) {
  var consoleEl = document.getElementById('console');
  if (!consoleEl) {
    return;
  }
  var div = document.createElement('div');
  var clean = line.replace(/\[[0-9;]*m/g, '');
  var lineLower = clean.toLowerCase();
  if (lineLower.indexOf('error') !== -1 || lineLower.indexOf('exception') !== -1) {
    div.className = 'log-error';
  } else if (lineLower.indexOf('warn') !== -1) {
    div.className = 'log-warn';
  } else if (lineLower.indexOf('done') !== -1 || lineLower.indexOf('joined') !== -1 || lineLower.indexOf('left') !== -1) {
    div.className = 'log-done';
  } else if (lineLower.indexOf('loading') !== -1 || lineLower.indexOf('starting') !== -1) {
    div.className = 'log-info';
  }
  div.textContent = clean;
  consoleEl.appendChild(div);
  var excess = consoleEl.children.length - 800;
  for (var i = 0; i < excess; i++) {
    consoleEl.removeChild(consoleEl.firstChild);
  }
  consoleEl.scrollTop = consoleEl.scrollHeight;
}


// -- Metrics ------------------------------------------------------------------
var metricsTimer = null;

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
  ['mv-tps', 'mv-mspt'].forEach(function(id) {
    document.getElementById(id).textContent = '—';
  });
  document.getElementById('metrics-updated').textContent = '';
  window._metricsLastFetch = null;
  document.getElementById('metrics-players-row').style.display = 'none';
  ['mc-tps', 'mc-mspt'].forEach(function(id) {
    document.getElementById(id).className = 'metric-card';
  });
}

function updateMetricsUI(data) {
  var players = data.players_online || [];
  var playersRow = document.getElementById('metrics-players-row');
  if (players.length) {
    playersRow.style.display = 'block';
    document.getElementById('metrics-players-list').innerHTML = players.map(function(playerName) {
      return '<span class="player-chip">👤 ' + escHtml(playerName) + '</span>';
    }).join('');
  } else {
    playersRow.style.display = 'none';
  }

  var tps = data.tps;
  var tpsEl = document.getElementById('mv-tps');
  var tpsCard = document.getElementById('mc-tps');
  if (tps !== null && tps !== undefined) {
    tpsEl.textContent = tps.toFixed(1);
    if (tps >= 19) {
      tpsCard.className = 'metric-card good';
    } else if (tps >= 15) {
      tpsCard.className = 'metric-card warn';
    } else {
      tpsCard.className = 'metric-card bad';
    }
  } else {
    tpsEl.textContent = '—';
    tpsCard.className = 'metric-card';
  }

  var mspt = data.mspt;
  var msptEl = document.getElementById('mv-mspt');
  var msptCard = document.getElementById('mc-mspt');
  if (mspt !== null && mspt !== undefined) {
    msptEl.textContent = mspt.toFixed(1);
    if (mspt <= 50) {
      msptCard.className = 'metric-card good';
    } else if (mspt <= 100) {
      msptCard.className = 'metric-card warn';
    } else {
      msptCard.className = 'metric-card bad';
    }
  } else {
    msptEl.textContent = '—';
    msptCard.className = 'metric-card';
  }

  var rconWarning = document.getElementById('rcon-warning');
  if (data.rcon_status && data.rcon_status !== 'ok') {
    rconWarning.textContent = '⚠️ RCON: ' + data.rcon_status;
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
    var el = document.getElementById('metrics-updated');
    if (!el || !window._metricsLastFetch) {
      return;
    }
    var sec = Math.floor((Date.now() - window._metricsLastFetch) / 1000);
    var timeText;
    if (sec < 5) {
      timeText = 'ahora mismo';
    } else if (sec < 60) {
      timeText = 'hace ' + sec + 's';
    } else if (sec < 3600) {
      timeText = 'hace ' + Math.floor(sec / 60) + 'm ' + (sec % 60) + 's';
    } else {
      timeText = 'hace ' + Math.floor(sec / 3600) + 'h';
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
