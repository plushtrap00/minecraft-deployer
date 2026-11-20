// -- Configuración (solo admin): .env y .APP_CONSTANTS -------------------------
var CFG_ENV_TEXT_KEYS = [
  'APP_USERNAME', 'JWT_SECRET', 'WEB_PORT', 'SERVERS_PATH',
  'MC_DOMAIN', 'CURSEFORGE_API_KEY', 'AUTO_UPDATE_INTERVAL_SECONDS', 'APP_LANGUAGE',
];

// -- Sub-pestañas: Variables de entorno / Constantes de la app --------------
['env', 'constants', 'notify'].forEach(function(name) {
  document.getElementById('cfgtab-' + name).addEventListener('click', function() {
    activateCfgTab(name);
  });
});

function activateCfgTab(name) {
  document.querySelectorAll('#cfg-tabs .mgmt-tab').forEach(function(tab) {
    tab.classList.remove('active');
  });
  document.querySelectorAll('.cfg-tab-content').forEach(function(content) {
    content.classList.remove('active');
  });
  document.getElementById('cfgtab-' + name).classList.add('active');
  document.getElementById('cfg-content-' + name).classList.add('active');
  if (name === 'notify') {
    loadNotifications();
  }
}

function loadAdminConfig() {
  apiFetch('/api/admin/env')
    .then(function(response) { return response.json(); })
    .then(populateEnvForm)
    .catch(function() { showToast(t('No se pudo leer el .env'), 'error'); });

  document.getElementById('config-constants-form').innerHTML = loadingHtml();
  apiFetch('/api/admin/constants')
    .then(function(response) { return response.json(); })
    .then(renderConstantsForm)
    .catch(function() {
      document.getElementById('config-constants-form').innerHTML =
        '<p class="empty-msg text-red">' + t('Error al cargar') + '</p>';
    });
}

function populateEnvForm(data) {
  var secretsSet = data.secrets_set || {};
  CFG_ENV_TEXT_KEYS.forEach(function(key) {
    var el = document.getElementById('cfg-env-' + key);
    if (!el) {
      return;
    }
    if (key in secretsSet) {
      setSecretField(el.id, secretsSet[key]);
    } else {
      el.value = data[key] || '';
    }
  });
  var toggle = document.getElementById('cfg-env-AUTO_UPDATE_ENABLED');
  toggle.classList.toggle('on', (data.AUTO_UPDATE_ENABLED || '').toLowerCase() === 'true');

  // En Docker, el puerto y la carpeta de servidores los controla
  // docker-compose.yml (mapeo de puertos y volumen/carpeta), no este .env —
  // cambiarlos aquí no tiene el efecto que parece, así que se deshabilitan
  // con una nota en vez de dejar que parezca que "no hacen nada" al guardar.
  ['WEB_PORT', 'SERVERS_PATH'].forEach(function(key) {
    var input = document.getElementById('cfg-env-' + key);
    var hint = document.getElementById('cfg-env-' + key + '-hint');
    if (!input || !hint) {
      return;
    }
    input.disabled = !!data.in_docker;
    hint.style.display = data.in_docker ? '' : 'none';
    hint.textContent = data.in_docker
      ? t('En Docker esto se controla desde docker-compose.yml, no desde aquí.')
      : '';
  });
}

// Orden de las secciones en las que se agrupan las constantes, para no
// mostrarlas todas juntas en una lista larga (ver campo "category" que manda
// app_constants.py junto a cada valor).
var CFG_CONSTANT_CATEGORY_ORDER = [
  ['Logs'],
  ['Servidor de Minecraft'],
  ['Auto-actualización'],
  ['Mods y modpacks'],
  ['Subidas'],
  ['Sesión y login'],
  ['Otros'],
];

function renderConstantsForm(data) {
  var container = document.getElementById('config-constants-form');
  var byCategory = {};
  Object.keys(data).forEach(function(key) {
    var entry = data[key];
    var category = entry.category || 'Otros';
    (byCategory[category] = byCategory[category] || []).push({ key: key, entry: entry });
  });

  var html = '';
  CFG_CONSTANT_CATEGORY_ORDER.forEach(function(pair, index) {
    var category = pair[0];
    var items = byCategory[category];
    if (!items || !items.length) {
      return;
    }
    html += '<details class="help-section"' + (index === 0 ? ' open' : '') + '>'
      + '<summary>' + escHtml(t(category)) + '</summary>'
      + '<div class="help-section-body"><div class="props-grid">';
    items.forEach(function(item) {
      html += '<div class="prop-field">'
        + '<label class="prop-label">' + escHtml(item.key) + '</label>'
        + '<input type="number" class="w-full cfg-constant-input" data-key="' + escHtml(item.key) + '" value="' + escHtml(String(item.entry.value)) + '">'
        + '<div class="field-hint">' + escHtml(t(item.entry.description)) + '</div>'
        + '</div>';
    });
    html += '</div></div></details>';
  });
  container.innerHTML = html;
}

document.getElementById('config-env-form').addEventListener('click', function(event) {
  var track = event.target.closest('#cfg-env-AUTO_UPDATE_ENABLED');
  if (track) {
    track.classList.toggle('on');
  }
});

// Ojo para ver lo que hay en un campo oculto: la contraseña nueva y los dos
// secretos del .env (JWT_SECRET y la API key de CurseForge), que de entrada
// van tapados para que no se vean en pantalla ni en una captura.
function bindPassToggle(buttonId, inputId) {
  document.getElementById(buttonId).addEventListener('click', function() {
    var inp = document.getElementById(inputId);
    inp.type = inp.type === 'password' ? 'text' : 'password';
    this.innerHTML = icon(inp.type === 'password' ? 'eye' : 'eye-off');
  });
}

bindPassToggle('cfg-toggle-pass-vis', 'cfg-env-new-password');
bindPassToggle('cfg-jwt-vis', 'cfg-env-JWT_SECRET');
bindPassToggle('cfg-cf-vis', 'cfg-env-CURSEFORGE_API_KEY');

document.getElementById('cfg-save-env-btn').addEventListener('click', function() {
  var btn = this;
  var newPassword = document.getElementById('cfg-env-new-password').value;
  if (newPassword && newPassword.length < 8) {
    showToast(t('La nueva contraseña debe tener al menos 8 caracteres'), 'error');
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
    body: JSON.stringify({
      values: values,
      new_password: newPassword,
      clear: secretsToClear(document.getElementById('config-env-form'))
    })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      btn.disabled = false;
      if (result.ok) {
        document.getElementById('cfg-env-new-password').value = '';
        // Vuelve a pedir el estado: los secretos recién escritos o quitados
        // pasan a «Guardado» o a vacío (el valor no se queda en la página).
        apiFetch('/api/admin/env')
          .then(function(response) { return response.json(); })
          .then(populateEnvForm);
        if (result.data.changed) {
          offerAppRestart(t('.env guardado.'));
        } else {
          showToast(t('No había cambios que guardar.'), 'success');
        }
      } else {
        showToast(result.data.detail || t('Error al guardar'), 'error');
      }
    })
    .catch(function() {
      btn.disabled = false;
      showToast(t('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.'), 'error');
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
        if (result.data.changed) {
          offerAppRestart(t('Constantes guardadas.'));
        } else {
          showToast(t('No había cambios que guardar.'), 'success');
        }
      } else {
        showToast(result.data.detail || t('Error al guardar'), 'error');
      }
    })
    .catch(function() {
      btn.disabled = false;
      showToast(t('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.'), 'error');
    });
});

// Se ofrece reiniciar justo tras guardar un cambio real en el .env o las
// constantes (el backend ya filtró el caso de "guardar sin tocar nada" — ver
// el campo "changed" de la respuesta), pero es una decisión del usuario, no
// automática: "Más tarde" dispara loadAutoUpdateStatus() para que el aviso de
// reinicio pendiente aparezca ya mismo en el monitor de sistema (sysmon.js),
// sin esperar a su siguiente sondeo periódico.
function offerAppRestart(savedMessage) {
  showConfirm(
    savedMessage,
    t('Los cambios no se aplican hasta reiniciar la app. ¿Reiniciarla ahora? (no reinicia si hay un servidor de Minecraft corriendo o una operación en curso)'),
    doAppRestart,
    {
      icon: '🔄',
      confirmLabel: t('Reiniciar ahora'),
      cancelLabel: t('Más tarde'),
      tone: 'accent',
      onCancel: function() { loadAutoUpdateStatus(); },
    }
  );
}

// El reinicio en sí se sigue con el mismo poll compartido de sysmon.js
// (beginRestartWatch), que ya corre siempre en segundo plano: así se bloquea
// la app con el mismo overlay global en vez de tener su propio poll y su
// propio texto de estado duplicados. btn es opcional (lo usa el botón de
// reinicio pendiente del monitor de sistema para desactivarse mientras dura
// la petición; el diálogo de confirmación no necesita uno propio).
function doAppRestart(btn) {
  if (btn) {
    btn.disabled = true;
  }
  apiFetch('/api/admin/restart', { method: 'POST' })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok) {
        showToast(t('Reiniciando la app…'), 'success');
        beginRestartWatch(t('Aplicando los cambios de configuración…'), t('Esto puede tardar unos segundos. No cierres esta pestaña.'));
      } else {
        showToast(result.data.detail || t('No se pudo reiniciar'), 'error');
        if (btn) {
          btn.disabled = false;
        }
      }
    })
    .catch(function() {
      // La conexión cortándose aquí es justo la señal esperada de que la app
      // ya está reiniciando -- no se trata como un error real.
      showToast(t('Reiniciando la app…'), 'success');
      beginRestartWatch(t('Aplicando los cambios de configuración…'), t('Esto puede tardar unos segundos. No cierres esta pestaña.'));
    });
}
