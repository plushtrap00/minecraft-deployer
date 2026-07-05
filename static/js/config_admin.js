// -- Configuración (solo admin): .env y .APP_CONSTANTS -------------------------
var CFG_ENV_TEXT_KEYS = [
  'APP_USERNAME', 'JWT_SECRET', 'WEB_PORT', 'SERVERS_PATH',
  'MC_DOMAIN', 'CURSEFORGE_API_KEY', 'AUTO_UPDATE_INTERVAL_SECONDS',
];

function loadAdminConfig() {
  apiFetch('/api/admin/env')
    .then(function(response) { return response.json(); })
    .then(populateEnvForm)
    .catch(function() { showToast('Error al cargar .env', 'error'); });

  document.getElementById('config-constants-form').innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/admin/constants')
    .then(function(response) { return response.json(); })
    .then(renderConstantsForm)
    .catch(function() {
      document.getElementById('config-constants-form').innerHTML =
        '<p class="empty-msg" style="color:var(--red)">Error al cargar</p>';
    });

  document.getElementById('cfg-restart-body').innerHTML = '';
  var restartBtn = document.getElementById('cfg-restart-btn');
  restartBtn.disabled = false;
  restartBtn.textContent = '🔄 Reiniciar la app ahora';
}

function populateEnvForm(data) {
  CFG_ENV_TEXT_KEYS.forEach(function(key) {
    var el = document.getElementById('cfg-env-' + key);
    if (el) {
      el.value = data[key] || '';
    }
  });
  var toggle = document.getElementById('cfg-env-AUTO_UPDATE_ENABLED');
  toggle.classList.toggle('on', (data.AUTO_UPDATE_ENABLED || '').toLowerCase() === 'true');
}

function renderConstantsForm(data) {
  var container = document.getElementById('config-constants-form');
  var html = '<div class="users-form">';
  Object.keys(data).forEach(function(key) {
    var entry = data[key];
    html += '<div>'
      + '<label class="field-label">' + escHtml(key) + '</label>'
      + '<input type="number" class="w-full cfg-constant-input" data-key="' + escHtml(key) + '" value="' + escHtml(String(entry.value)) + '">'
      + '<div class="field-hint">' + escHtml(entry.description) + '</div>'
      + '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
}

document.getElementById('config-env-form').addEventListener('click', function(event) {
  var track = event.target.closest('#cfg-env-AUTO_UPDATE_ENABLED');
  if (track) {
    track.classList.toggle('on');
  }
});

document.getElementById('cfg-toggle-pass-vis').addEventListener('click', function() {
  var inp = document.getElementById('cfg-env-new-password');
  inp.type = inp.type === 'password' ? 'text' : 'password';
  this.textContent = inp.type === 'password' ? '👁' : '🙈';
});

document.getElementById('cfg-save-env-btn').addEventListener('click', function() {
  var btn = this;
  var newPassword = document.getElementById('cfg-env-new-password').value;
  if (newPassword && newPassword.length < 8) {
    showToast('La nueva contraseña debe tener al menos 8 caracteres', 'error');
    return;
  }

  var values = {};
  CFG_ENV_TEXT_KEYS.forEach(function(key) {
    values[key] = document.getElementById('cfg-env-' + key).value;
  });
  values.AUTO_UPDATE_ENABLED = document.getElementById('cfg-env-AUTO_UPDATE_ENABLED').classList.contains('on') ? 'true' : 'false';

  btn.disabled = true;
  apiFetch('/api/admin/env', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values: values, new_password: newPassword })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      btn.disabled = false;
      if (result.ok) {
        showToast('.env guardado. Reinicia la app para aplicar los cambios.', 'success');
        document.getElementById('cfg-env-new-password').value = '';
      } else {
        showToast(result.data.detail || 'Error al guardar', 'error');
      }
    })
    .catch(function() {
      btn.disabled = false;
      showToast('Error de red', 'error');
    });
});

document.getElementById('cfg-save-constants-btn').addEventListener('click', function() {
  var btn = this;
  var values = {};
  document.querySelectorAll('.cfg-constant-input').forEach(function(input) {
    values[input.dataset.key] = input.value;
  });

  btn.disabled = true;
  apiFetch('/api/admin/constants', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values: values })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      btn.disabled = false;
      if (result.ok) {
        showToast('Constantes guardadas. Reinicia la app para aplicar los cambios.', 'success');
      } else {
        showToast(result.data.detail || 'Error al guardar', 'error');
      }
    })
    .catch(function() {
      btn.disabled = false;
      showToast('Error de red', 'error');
    });
});

document.getElementById('cfg-restart-btn').addEventListener('click', function() {
  var btn = this;
  btn.disabled = true;
  btn.textContent = 'Reiniciando...';
  apiFetch('/api/admin/restart', { method: 'POST' })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok) {
        showToast('Reiniciando la app...', 'success');
        watchConfigRestart();
      } else {
        showToast(result.data.detail || 'No se pudo reiniciar', 'error');
        btn.disabled = false;
        btn.textContent = '🔄 Reiniciar la app ahora';
      }
    })
    .catch(function() {
      // La conexión cortándose aquí es justo la señal esperada de que la app
      // ya está reiniciando -- no se trata como un error real.
      showToast('Reiniciando la app...', 'success');
      watchConfigRestart();
    });
});

var CFG_RESTART_POLL_MS = 2000;
var CFG_RESTART_MAX_WAIT_MS = 120000; // ~2 minutos de margen antes de rendirse

function watchConfigRestart() {
  var startedAt = Date.now();
  document.getElementById('cfg-restart-body').innerHTML = '<p class="empty-msg">⏳ Esperando a que la app vuelva a responder...</p>';

  function poll() {
    apiFetch('/api/auto-update/status')
      .then(function(response) {
        if (!response.ok) {
          throw new Error('todavía no');
        }
        return response.json();
      })
      .then(function() {
        document.getElementById('cfg-restart-body').innerHTML = '<p style="color:var(--green)">✅ La app volvió a responder. Recargando la página...</p>';
        setTimeout(function() { window.location.reload(); }, 800);
      })
      .catch(function() {
        if (Date.now() - startedAt > CFG_RESTART_MAX_WAIT_MS) {
          document.getElementById('cfg-restart-body').innerHTML =
            '<p style="color:var(--red)">La app está tardando en volver a responder. Recarga la página a mano en unos segundos.</p>';
          return;
        }
        setTimeout(poll, CFG_RESTART_POLL_MS);
      });
  }

  setTimeout(poll, CFG_RESTART_POLL_MS);
}
