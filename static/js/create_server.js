// -- Crear servidor nuevo desde cero --------------------------------------------
document.getElementById('deploy-mode-import').addEventListener('click', function() {
  this.classList.add('active');
  document.getElementById('deploy-mode-create').classList.remove('active');
  document.getElementById('deploy-import-section').style.display = '';
  document.getElementById('deploy-create-section').style.display = 'none';
});

document.getElementById('deploy-mode-create').addEventListener('click', function() {
  this.classList.add('active');
  document.getElementById('deploy-mode-import').classList.remove('active');
  document.getElementById('deploy-import-section').style.display = 'none';
  document.getElementById('deploy-create-section').style.display = '';
  if (!createMcVersionsLoaded) {
    loadCreateMcVersions();
  }
});

var createMcVersionsLoaded = false;

function loadCreateMcVersions() {
  var select = document.getElementById('create-mc-version');
  apiFetch('/api/create-server/mc-versions')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      createMcVersionsLoaded = true;
      select.innerHTML = data.versions.map(function(v) {
        return '<option value="' + escHtml(v) + '">' + escHtml(v) + '</option>';
      }).join('');
      onCreateLoaderOrVersionChange();
    })
    .catch(function() {
      select.innerHTML = '<option value="">Error al cargar versiones</option>';
    });
}

document.getElementById('create-loader').addEventListener('change', onCreateLoaderOrVersionChange);
document.getElementById('create-mc-version').addEventListener('change', onCreateLoaderOrVersionChange);

function onCreateLoaderOrVersionChange() {
  var loader = document.getElementById('create-loader').value;
  var mcVersion = document.getElementById('create-mc-version').value;
  var versionField = document.getElementById('create-loader-version-field');
  var hint = document.getElementById('create-loader-hint');

  if (loader === 'vanilla') {
    versionField.style.display = 'none';
    hint.textContent = '';
    return;
  }

  versionField.style.display = '';
  var loaderSelect = document.getElementById('create-loader-version');
  loaderSelect.innerHTML = '<option value="">Cargando...</option>';
  hint.textContent = '';
  if (!mcVersion) {
    return;
  }

  apiFetch('/api/create-server/loader-versions?loader=' + encodeURIComponent(loader) + '&mc_version=' + encodeURIComponent(mcVersion))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        loaderSelect.innerHTML = '<option value="">Error</option>';
        hint.textContent = result.data.detail || 'Error al consultar versiones';
        return;
      }
      if (!result.data.versions.length) {
        loaderSelect.innerHTML = '<option value="">Sin versiones disponibles</option>';
        hint.textContent = 'No hay versiones de ' + result.data.loader_display + ' para MC ' + mcVersion + '. Prueba otra versión de Minecraft.';
        return;
      }
      loaderSelect.innerHTML = result.data.versions.map(function(v) {
        return '<option value="' + escHtml(v) + '">' + escHtml(v) + '</option>';
      }).join('');
    })
    .catch(function() {
      loaderSelect.innerHTML = '<option value="">Error de red</option>';
    });
}

var CREATE_LOG_MAX_LINES = 300;
var CREATE_LOG_RENDER_THROTTLE_MS = 200;

document.getElementById('create-server-btn').addEventListener('click', function() {
  var name = document.getElementById('create-name').value.trim();
  if (!name) {
    showToast('Escribe un nombre para el servidor', 'error');
    return;
  }
  var mcVersion = document.getElementById('create-mc-version').value;
  if (!mcVersion) {
    showToast('Elegí una versión de Minecraft', 'error');
    return;
  }
  var loader = document.getElementById('create-loader').value;
  var loaderVersion = loader === 'vanilla' ? '' : document.getElementById('create-loader-version').value;
  if (loader !== 'vanilla' && !loaderVersion) {
    showToast('Elegí una versión del modloader', 'error');
    return;
  }
  var ramMin = document.getElementById('create-ram-min-val').value + document.getElementById('create-ram-min-unit').value;
  var ramMax = document.getElementById('create-ram-max-val').value + document.getElementById('create-ram-max-unit').value;

  var btn = this;
  btn.disabled = true;

  var logLines = [];
  var renderTimer = null;
  var body = document.getElementById('create-progress-body');

  function pushLogLine(message) {
    logLines.push(message);
    if (logLines.length > CREATE_LOG_MAX_LINES) {
      logLines.splice(0, logLines.length - CREATE_LOG_MAX_LINES);
    }
  }

  function logHtml() {
    return logLines.length
      ? '<div class="log-viewer" id="create-server-log" style="height:220px;margin-bottom:10px;font-size:.74rem">'
        + logLines.map(escHtml).join('\n') + '</div>'
      : '';
  }

  function renderNow() {
    renderTimer = null;
    body.innerHTML = logHtml();
    var logEl = document.getElementById('create-server-log');
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  function scheduleRender() {
    if (renderTimer === null) {
      renderTimer = setTimeout(renderNow, CREATE_LOG_RENDER_THROTTLE_MS);
    }
  }

  function finish(resultHtml) {
    if (renderTimer !== null) {
      clearTimeout(renderTimer);
      renderTimer = null;
    }
    body.innerHTML = logHtml() + resultHtml;
    var logEl = document.getElementById('create-server-log');
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
    btn.disabled = false;
  }

  var url = '/api/create-server/stream?name=' + encodeURIComponent(name)
    + '&mc_version=' + encodeURIComponent(mcVersion)
    + '&loader=' + encodeURIComponent(loader)
    + '&loader_version=' + encodeURIComponent(loaderVersion)
    + '&ram_min=' + encodeURIComponent(ramMin)
    + '&ram_max=' + encodeURIComponent(ramMax)
    + '&token=' + encodeURIComponent(authToken);
  var source = new EventSource(url);

  source.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === 'log') {
      pushLogLine(data.message);
      scheduleRender();
    } else if (data.type === 'done') {
      source.close();
      var resultHtml = data.success
        ? '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Servidor "' + escHtml(data.name) + '" creado. Ya podés subirle mods desde Gestión de modpacks.</div>'
        : modErrorHtml(data.detail || 'Error desconocido');
      finish(resultHtml);
      if (data.success) {
        loadModpacks();
      }
    } else if (data.type === 'error') {
      source.close();
      finish(modErrorHtml(data.detail || 'Error desconocido'));
    }
  };

  source.onerror = function() {
    source.close();
    finish(modErrorHtml('Se perdió la conexión durante la creación del servidor.'));
  };
});
