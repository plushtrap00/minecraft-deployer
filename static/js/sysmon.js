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
    renderSysmon(data);
  };
}

function stopSysmonStream() {
  if (sysmonSSE) {
    sysmonSSE.close();
    sysmonSSE = null;
  }
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

  document.getElementById('sysmon-body').innerHTML = html;
}
