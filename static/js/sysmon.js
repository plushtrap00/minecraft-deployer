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

var AUTO_UPDATE_STATUS_POLL_MS = 30000;
var AUTO_UPDATE_RESTART_POLL_MS = 2000;
var AUTO_UPDATE_RESTART_MAX_WAIT_MS = 120000; // ~2 minutos de margen antes de rendirse
var lastSysmonStats = null;
var lastAutoUpdateStatus = null;
var autoUpdateChecking = false;
var autoUpdateRestarting = false;
var autoUpdateRestartStartedAt = null;
var autoUpdatePollTimer = null;

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

// El estado de auto-actualización se pide aparte del stream de CPU/RAM/temp, y
// corre SIEMPRE desde que carga la página (no solo mientras el panel está
// abierto): así el badge de notificación en la pestaña "Sistema" se puede
// encender aunque el usuario nunca haya abierto el panel.
//
// Un único bucle (con setTimeout encadenado, no dos intervalos separados) se
// autoprograma con un intervalo lento en operación normal y uno rápido
// mientras se está esperando que la app vuelva a responder tras un
// "Actualizar ahora" — antes había un segundo poll dedicado y más rápido para
// ese caso, corriendo en paralelo con este, y bajo cualquier retraso del
// navegador (por ejemplo, si la pestaña queda en segundo plano y Chrome
// empieza a limitar los timers) ese poll paralelo podía directamente no
// completar sus intentos a tiempo, dejando la recarga automática sin
// dispararse nunca aunque la app ya hubiera vuelto a responder hacía rato.
function scheduleNextAutoUpdatePoll() {
  var delay = autoUpdateRestarting ? AUTO_UPDATE_RESTART_POLL_MS : AUTO_UPDATE_STATUS_POLL_MS;
  autoUpdatePollTimer = setTimeout(loadAutoUpdateStatus, delay);
}

function loadAutoUpdateStatus() {
  var wasRestarting = autoUpdateRestarting;
  apiFetch('/api/auto-update/status')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      lastAutoUpdateStatus = data;
      if (wasRestarting) {
        // La app volvió a responder tras el reinicio: se recarga la página
        // entera para que quede visualmente claro que ya terminó, en vez de
        // solo refrescar el panel.
        autoUpdateRestarting = false;
        hideRestartOverlay();
        showToast('✅ Actualizado. Recargando la página...', 'success');
        setTimeout(function() { window.location.reload(); }, 800);
        return;
      }
      updateSysmonBadge();
      if (lastSysmonStats) {
        renderSysmon(lastSysmonStats);
      }
      scheduleNextAutoUpdatePoll();
    })
    .catch(function(error) {
      if (error && error.message === 'Sesión expirada') {
        // apiFetch ya llamó a logout() — pasa de forma normal la primera vez
        // que carga la página sin sesión todavía (esta llamada sale disparada
        // en cuanto se define, sin esperar al login). Aun así hay que seguir
        // programando el siguiente intento: si no, en cuanto el usuario inicia
        // sesión de verdad (sin recargar la página) este bucle queda muerto
        // para siempre y el aviso de actualización nunca se vuelve a comprobar.
        scheduleNextAutoUpdatePoll();
        return;
      }
      if (!wasRestarting) {
        // Esta pestaña no pidió ningún reinicio, pero de golpe la app dejó de
        // responder -- probablemente otra sesión disparó uno (auto-actualización
        // o el panel de Configuración). Se trata igual que uno propio: bloquear
        // la interacción hasta que vuelva a responder, en vez de dejar que el
        // usuario siga tocando botones contra un servidor que se está reiniciando.
        beginRestartWatch();
        return;
      }
      if (autoUpdateRestartStartedAt !== null
          && Date.now() - autoUpdateRestartStartedAt > AUTO_UPDATE_RESTART_MAX_WAIT_MS) {
        autoUpdateRestarting = false;
        hideRestartOverlay();
        showToast('La app está tardando en volver a responder. Recarga la página a mano en unos segundos.', 'error');
        if (lastSysmonStats) {
          renderSysmon(lastSysmonStats);
        }
      }
      scheduleNextAutoUpdatePoll();
    });
}

loadAutoUpdateStatus();

function updateSysmonBadge() {
  var badge = document.getElementById('sysmon-nav-badge');
  if (!badge) {
    return;
  }
  var status = lastAutoUpdateStatus;
  var hasUpdate = !autoUpdateRestarting && !!(status && ((status.enabled && status.commits_behind > 0) || status.restart_pending));
  badge.style.display = hasUpdate ? '' : 'none';
}

// El botón "Actualizar ahora" se recrea en cada render de renderAutoUpdateSection()
// (sysmon-body se reescribe entero), así que el listener se delega en el
// contenedor estable en vez de reengancharse a mano cada vez.
document.getElementById('sysmon-body').addEventListener('click', function(event) {
  if (event.target.closest('#auto-update-apply-btn')) {
    applyAutoUpdate();
  }
  if (event.target.closest('#auto-update-check-btn')) {
    checkForUpdatesNow();
  }
  if (event.target.closest('#sysmon-restart-btn')) {
    doAppRestart(document.getElementById('sysmon-restart-btn'));
  }
});

// Botón "🔍 Comprobar ahora" — antes vivía arriba junto a CPU/RAM (donde solo
// forzaba un refresco de un stream que ya se actualiza solo), reaprovechado
// acá para forzar una comprobación real contra GitHub sin esperar al próximo
// ciclo del bucle en segundo plano.
function checkForUpdatesNow() {
  autoUpdateChecking = true;
  if (lastSysmonStats) {
    renderSysmon(lastSysmonStats);
  }
  apiFetch('/api/auto-update/check', { method: 'POST' })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      autoUpdateChecking = false;
      if (result.ok) {
        lastAutoUpdateStatus = result.data;
        updateSysmonBadge();
        showToast(
          result.data.commits_behind > 0
            ? '🔔 Hay ' + result.data.commits_behind + ' commit(s) nuevos disponibles'
            : '✅ Ya tienes la última versión',
          'success'
        );
      } else {
        showToast(result.data.detail || 'No se pudo comprobar', 'error');
      }
      if (lastSysmonStats) {
        renderSysmon(lastSysmonStats);
      }
    })
    .catch(function() {
      autoUpdateChecking = false;
      showToast('Error de red al comprobar actualizaciones', 'error');
      if (lastSysmonStats) {
        renderSysmon(lastSysmonStats);
      }
    });
}

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
        showToast('Actualización aplicada. Reiniciando la app...', 'success');
        beginRestartWatch('Aplicando la actualización...', 'Esto puede tardar unos segundos. No cierres esta pestaña.');
      } else {
        showToast(result.data.detail || 'No se pudo actualizar', 'error');
        if (btn) {
          btn.disabled = false;
          btn.textContent = '⬇ Actualizar ahora';
        }
      }
    })
    .catch(function() {
      // La conexión cortándose aquí es justo la señal esperada de que la app
      // ya está reiniciando -- no se trata como un error real.
      showToast('Actualización enviada. Reiniciando la app...', 'success');
      beginRestartWatch('Aplicando la actualización...', 'Esto puede tardar unos segundos. No cierres esta pestaña.');
    });
}

function beginRestartWatch(title, sub) {
  autoUpdateRestarting = true;
  autoUpdateRestartStartedAt = Date.now();
  showRestartOverlay(title, sub);
  updateSysmonBadge();
  if (lastSysmonStats) {
    renderSysmon(lastSysmonStats);
  }
  if (autoUpdatePollTimer !== null) {
    clearTimeout(autoUpdatePollTimer);
  }
  // Pequeño margen inicial: la app todavía está terminando de mandar esta
  // misma respuesta y programando su propio reinicio (ver schedule_restart
  // en services/auto_update.py) antes de que el proceso realmente muera.
  autoUpdatePollTimer = setTimeout(loadAutoUpdateStatus, AUTO_UPDATE_RESTART_POLL_MS);
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
  html += renderRestartPendingSection();

  document.getElementById('sysmon-body').innerHTML = html;
}

// Aparece solo cuando queda un cambio de .env o de constantes guardado pero
// sin aplicar (ver "Más tarde" en el diálogo que ofrece config_admin.js justo
// tras guardar, y restart_pending en services/auto_update.py) — mismo patrón
// de "bloqueado por X" que la sección de auto-actualización de arriba, para
// que el motivo sea igual de visible en los dos casos.
function renderRestartPendingSection() {
  var status = lastAutoUpdateStatus;
  if (!status || !status.restart_pending || autoUpdateRestarting) {
    return '';
  }
  var blockedReason = status.server_running
    ? 'hay un servidor de Minecraft en marcha'
    : (status.busy ? status.busy_reasons.join(', ') : null);

  var html = '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">⚡ Reinicio pendiente</div>';
  html += '<span class="sysmon-no-temps">Guardaste cambios de .env o de constantes que todavía no se aplicaron.</span>';
  html += '<div style="margin-top:6px;display:flex;flex-direction:column;gap:4px;align-items:flex-start">';
  html += '<button type="button" class="btn-secondary btn-sm" id="sysmon-restart-btn"'
    + (blockedReason ? ' disabled' : '') + '>🔄 Reiniciar ahora</button>';
  if (blockedReason) {
    html += '<span class="sysmon-no-temps">Bloqueado: ' + escHtml(blockedReason) + '</span>';
  }
  html += '</div></div>';
  return html;
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

  if (autoUpdateRestarting) {
    html += '<span class="sysmon-no-temps">⏳ Actualización aplicada, esperando a que la app vuelva a responder...</span></div>';
    return html;
  }

  if (!status) {
    html += '<span class="sysmon-no-temps">Cargando...</span></div>';
    return html;
  }

  if (!status.enabled) {
    html += '<span class="sysmon-no-temps">Comprobación automática deshabilitada (AUTO_UPDATE_ENABLED=false en el .env) — puedes comprobar a mano igualmente.</span>';
  } else {
    html += autoUpdateRow('Entorno', status.in_docker ? 'Docker' : 'Nativo (systemd)');
  }

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
  } else if (status.last_check) {
    // Solo "al día" si ya se comprobó de verdad alguna vez (automático o a
    // mano) — si nunca se comprobó, commits_behind sigue en su valor inicial
    // 0 y mostrar "al día" sería un falso positivo.
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

  html += '<div style="margin-top:6px">'
    + '<button type="button" class="btn-secondary btn-xs" id="auto-update-check-btn"' + (autoUpdateChecking ? ' disabled' : '') + '>'
    + (autoUpdateChecking ? '↻ Comprobando...' : '🔍 Comprobar ahora') + '</button>'
    + '</div>';

  html += '</div>';
  return html;
}
