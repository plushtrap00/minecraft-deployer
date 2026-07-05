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
}

function stopSysmonStream() {
  if (sysmonSSE) {
    sysmonSSE.close();
    sysmonSSE = null;
  }
}

// El estado de auto-actualización se pide aparte del stream de CPU/RAM/temp,
// y corre SIEMPRE desde que carga la página (no solo mientras el panel está
// abierto): así el badge de notificación en la pestaña "Sistema" se puede
// prender aunque el usuario nunca haya abierto el panel. Se cachea para que
// renderSysmon() lo incluya en cada re-render sin tener que volver a pedirlo.
loadAutoUpdateStatus();
setInterval(loadAutoUpdateStatus, AUTO_UPDATE_STATUS_POLL_MS);

function loadAutoUpdateStatus() {
  apiFetch('/api/auto-update/status')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      lastAutoUpdateStatus = data;
      updateSysmonBadge();
      if (lastSysmonStats) {
        renderSysmon(lastSysmonStats);
      }
    })
    .catch(function() {});
}

function updateSysmonBadge() {
  var badge = document.getElementById('sysmon-nav-badge');
  if (!badge) {
    return;
  }
  var status = lastAutoUpdateStatus;
  var hasUpdate = !!(status && status.enabled && status.commits_behind > 0);
  badge.style.display = hasUpdate ? '' : 'none';
}

// El botón "Actualizar ahora" se recrea en cada render de renderAutoUpdateSection()
// (sysmon-body se reescribe entero), así que el listener se delega en el
// contenedor estable en vez de reengancharse a mano cada vez.
document.getElementById('sysmon-body').addEventListener('click', function(event) {
  if (event.target.closest('#auto-update-apply-btn')) {
    applyAutoUpdate();
  }
});

function applyAutoUpdate() {
  var btn = document.getElementById('auto-update-apply-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Actualizando...';
  }
  apiFetch('/api/auto-update/apply', { method: 'POST' })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok) {
        showToast(result.data.message || 'Actualización aplicada. La app se está reiniciando...', 'success');
      } else {
        showToast(result.data.detail || 'No se pudo actualizar', 'error');
        if (btn) {
          btn.disabled = false;
          btn.textContent = '⬇ Actualizar ahora';
        }
      }
    })
    .catch(function() {
      // Es esperable que la conexión se corte apenas la app se reinicia --
      // no se trata como un error real.
      showToast('Actualización enviada, la app se está reiniciando...', 'success');
    });
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
    html += autoUpdateRow('Estado', '🔔 ' + status.commits_behind + ' commit(s) nuevos disponibles', 'var(--yellow)');

    var blockedReason = status.server_running
      ? 'hay un servidor de Minecraft en marcha'
      : (status.busy ? status.busy_reasons.join(', ') : null);

    html += '<div style="margin-top:6px;display:flex;flex-direction:column;gap:4px;align-items:flex-start">';
    html += '<button type="button" class="btn-secondary btn-sm" id="auto-update-apply-btn"'
      + (blockedReason ? ' disabled' : '') + '>⬇ Actualizar ahora</button>';
    if (blockedReason) {
      html += '<span class="sysmon-no-temps">Bloqueado: ' + escHtml(blockedReason) + '</span>';
    }
    html += '</div>';
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
