// ── Monitor de sistema ────────────────────────────────────────────────────────
var sysmonOpen = false;
var sysmonSSE = null;

document.getElementById('btn-logout').addEventListener('click', function() {
  if (confirm('¿Cerrar sesión?')) {
    logout();
  }
});

document.getElementById('btn-sysmon').addEventListener('click', function() {
  sysmonOpen = !sysmonOpen;
  var panel = document.getElementById('sysmon-panel');
  if (sysmonOpen) {
    panel.classList.add('open');
    this.classList.add('active');
    startSysmonStream();
  } else {
    panel.classList.remove('open');
    this.classList.remove('active');
    stopSysmonStream();
  }
});

document.getElementById('sysmon-close-btn').addEventListener('click', function() {
  sysmonOpen = false;
  document.getElementById('sysmon-panel').classList.remove('open');
  document.getElementById('btn-sysmon').classList.remove('active');
  stopSysmonStream();
});

document.getElementById('sysmon-refresh-btn').addEventListener('click', function() {
  stopSysmonStream();
  startSysmonStream();
});

var AUTO_UPDATE_STATUS_POLL_MS = 30000;
var autoUpdateStatusTimer = null;
var lastSysmonStats = null;
var lastAutoUpdateStatus = null;

function startSysmonStream() {
  if (sysmonSSE) {
    return;
  }
  document.getElementById('sysmon-body').innerHTML = '<p style="color:var(--muted);font-size:.82rem">Cargando...</p>';
  sysmonSSE = new EventSource('/api/system-stats/stream?token=' + encodeURIComponent(authToken));
  sysmonSSE.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.error || !data.cpu) {
      document.getElementById('sysmon-body').innerHTML =
        '<p style="color:var(--red);font-size:.82rem">Error: ' + escHtml(data.error || 'Respuesta inesperada del servidor') + '</p>';
      return;
    }
    lastSysmonStats = data;
    renderSysmon(data);
  };

  // El estado de auto-actualización no necesita empujarse cada ~2s como el
  // resto del panel (cambia como mucho cada varios minutos): se pide aparte
  // con su propio intervalo, más lento, y se cachea para que renderSysmon()
  // lo incluya en cada re-render sin tener que volver a pedirlo.
  loadAutoUpdateStatus();
  if (autoUpdateStatusTimer === null) {
    autoUpdateStatusTimer = setInterval(loadAutoUpdateStatus, AUTO_UPDATE_STATUS_POLL_MS);
  }
}

function stopSysmonStream() {
  if (sysmonSSE) {
    sysmonSSE.close();
    sysmonSSE = null;
  }
  if (autoUpdateStatusTimer !== null) {
    clearInterval(autoUpdateStatusTimer);
    autoUpdateStatusTimer = null;
  }
}

function loadAutoUpdateStatus() {
  apiFetch('/api/auto-update/status')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      lastAutoUpdateStatus = data;
      if (lastSysmonStats) {
        renderSysmon(lastSysmonStats);
      }
    })
    .catch(function() {});
}

function sysColor(pct) {
  if (pct < 60) {
    return 'ok';
  }
  if (pct < 85) {
    return 'warn';
  }
  return 'bad';
}

function sysBar(label, pct, valLabel) {
  var cls = sysColor(pct);
  return '<div class="sysmon-bar-row">'
    + '<span class="sysmon-bar-label" title="' + escHtml(label) + '">' + escHtml(label) + '</span>'
    + '<div class="sysmon-bar-wrap"><div class="sysmon-bar-fill ' + cls + '" style="width:' + Math.min(pct, 100) + '%"></div></div>'
    + '<span class="sysmon-bar-val">' + escHtml(valLabel) + '</span>'
    + '</div>';
}

function renderSysmon(stats) {
  var now = new Date();
  document.getElementById('sysmon-updated').textContent =
    now.getHours().toString().padStart(2, '0') + ':'
    + now.getMinutes().toString().padStart(2, '0') + ':'
    + now.getSeconds().toString().padStart(2, '0');

  var html = '';

  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">⚙️ CPU</div>';
  html += sysBar('CPU', stats.cpu.total_percent, stats.cpu.total_percent.toFixed(0) + '%');
  html += '</div>';

  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">🧠 RAM</div>';
  html += sysBar('RAM', stats.ram.percent, stats.ram.used_gb.toFixed(1) + ' / ' + stats.ram.total_gb.toFixed(1) + ' GB');
  html += '</div>';

  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">🌡️ Temperatura</div>';
  if (stats.cpu_temp === null && stats.gpu_temp === null) {
    html += '<span class="sysmon-no-temps">Sin sensores detectados. '
      + 'Instala: <code>sudo apt install lm-sensors && sudo sensors-detect --auto</code></span>';
  } else {
    if (stats.cpu_temp !== null) {
      html += sysBar('CPU', stats.cpu_temp, stats.cpu_temp.toFixed(1) + '°C');
    }
    if (stats.gpu_temp !== null) {
      html += sysBar('GPU', stats.gpu_temp, stats.gpu_temp.toFixed(1) + '°C');
    }
  }
  html += '</div>';

  html += renderAutoUpdateSection();

  document.getElementById('sysmon-body').innerHTML = html;
}

function autoUpdateRow(label, value, valueColor) {
  var valueStyle = valueColor ? ' style="color:' + valueColor + ';font-weight:600"' : '';
  return '<div class="sysmon-proc-row">'
    + '<span class="sysmon-proc-name">' + escHtml(label) + '</span>'
    + '<span class="sysmon-proc-stats"><span' + valueStyle + '>' + escHtml(value) + '</span></span>'
    + '</div>';
}

function renderAutoUpdateSection() {
  var status = lastAutoUpdateStatus;
  var html = '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">🔄 Auto-actualización</div>';

  if (!status) {
    html += '<span class="sysmon-no-temps">Cargando...</span></div>';
    return html;
  }

  if (!status.enabled) {
    html += '<span class="sysmon-no-temps">Deshabilitada (AUTO_UPDATE_ENABLED=false en el .env)</span></div>';
    return html;
  }

  html += autoUpdateRow('Entorno', status.in_docker ? 'Docker' : 'Nativo (systemd)');

  if (status.commits_behind > 0) {
    if (status.server_running) {
      html += autoUpdateRow('Estado', '⏸ ' + status.commits_behind + ' pendiente(s) — servidor en marcha', 'var(--yellow)');
    } else if (status.busy) {
      html += autoUpdateRow('Estado', '⏸ ' + status.commits_behind + ' pendiente(s) — ' + status.busy_reasons.join(', '), 'var(--yellow)');
    } else {
      html += autoUpdateRow('Estado', '⬇ ' + status.commits_behind + ' pendiente(s), aplicando...', 'var(--accent)');
    }
  } else {
    html += autoUpdateRow('Estado', '✅ Al día', 'var(--green)');
  }

  if (status.last_check) {
    var d = new Date(status.last_check * 1000);
    var timeStr = d.getHours().toString().padStart(2, '0') + ':'
      + d.getMinutes().toString().padStart(2, '0') + ':'
      + d.getSeconds().toString().padStart(2, '0');
    html += autoUpdateRow('Último chequeo', timeStr);
  }

  if (status.last_error) {
    html += autoUpdateRow('Error', status.last_error, 'var(--red)');
  }

  html += '</div>';
  return html;
}
