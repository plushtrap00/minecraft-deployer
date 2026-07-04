// -- Cambio de versión de modloader --------------------------------------------
var modloaderInfo = null; // { loader, loader_display, mc_version, current_version, available }
var modloaderCheckedVersion = null; // versión ya verificada compatible, lista para instalar

document.getElementById('modloader-change-btn').addEventListener('click', function() {
  if (guardModOperationNav()) {
    return;
  }
  openModloaderModal();
});

function openModloaderModal() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('modloader-install-btn').disabled = true;
  modloaderCheckedVersion = null;
  document.getElementById('modloader-modal-body').innerHTML = '<p class="empty-msg">Cargando versiones disponibles...</p>';
  document.getElementById('modloader-modal').classList.add('show');

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/modloader/versions')
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        document.getElementById('modloader-modal-body').innerHTML = modErrorHtml(result.data.detail || 'Error desconocido');
        return;
      }
      modloaderInfo = result.data;
      renderModloaderModalBody();
    })
    .catch(function(error) {
      document.getElementById('modloader-modal-body').innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
}

function renderModloaderModalBody() {
  var body = document.getElementById('modloader-modal-body');
  var info = modloaderInfo;
  var html = '<p style="margin-bottom:10px;font-size:.87rem">Loader actual: <b>' + escHtml(info.loader_display)
    + ' ' + escHtml(info.current_version || '?') + '</b> · MC <b>' + escHtml(info.mc_version) + '</b></p>';

  if (!info.available.length) {
    html += '<p class="empty-msg">No hay otras versiones de ' + escHtml(info.loader_display)
      + ' disponibles para MC ' + escHtml(info.mc_version) + '.</p>';
    body.innerHTML = html;
    return;
  }

  html += '<label style="display:block;margin-bottom:6px;font-size:.85rem;color:var(--muted)">Nueva versión:</label>'
    + '<select id="modloader-version-select" class="w-full">'
    + info.available.map(function(v) { return '<option value="' + escHtml(v) + '">' + escHtml(v) + '</option>'; }).join('')
    + '</select>'
    + '<div id="modloader-check-result" style="margin-top:12px"></div>';
  body.innerHTML = html;

  document.getElementById('modloader-version-select').addEventListener('change', function() {
    modloaderCheckedVersion = null;
    document.getElementById('modloader-install-btn').disabled = true;
    document.getElementById('modloader-check-result').innerHTML = '';
  });
}

document.getElementById('modloader-verify-btn').addEventListener('click', function() {
  var select = document.getElementById('modloader-version-select');
  if (!select) {
    return;
  }
  var version = select.value;
  var resultEl = document.getElementById('modloader-check-result');
  resultEl.innerHTML = '<div style="color:var(--muted);font-size:.83rem">Verificando compatibilidad con los mods instalados...</div>';
  document.getElementById('modloader-install-btn').disabled = true;
  modloaderCheckedVersion = null;

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/modloader/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: version })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        resultEl.innerHTML = modErrorHtml(result.data.detail || 'Error desconocido');
        return;
      }
      if (result.data.compatible) {
        resultEl.innerHTML = '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">'
          + '✅ Todos los mods siguen siendo compatibles.</div>';
        modloaderCheckedVersion = version;
        document.getElementById('modloader-install-btn').disabled = false;
      } else {
        var names = result.data.incompatible_mods.map(function(m) {
          return escHtml(m.display_name) + ' (requiere ' + escHtml(m.required) + ')';
        }).join(', ');
        resultEl.innerHTML = modErrorHtml('No se puede cambiar de versión: dejarían de ser compatibles: ' + names);
      }
    })
    .catch(function(error) {
      resultEl.innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
});

document.getElementById('modloader-install-btn').addEventListener('click', function() {
  if (!modloaderCheckedVersion) {
    return;
  }
  var version = modloaderCheckedVersion;
  showConfirm(
    'Cambiar a ' + modloaderInfo.loader_display + ' ' + version,
    'Esto reemplaza los archivos del modloader del servidor. Asegurate de que el servidor esté detenido.',
    function() { startModloaderInstall(version); }
  );
});

var MODLOADER_LOG_MAX_LINES = 300;
var MODLOADER_LOG_MAX_LINE_LENGTH = 500;
var MODLOADER_LOG_RENDER_THROTTLE_MS = 200;

function startModloaderInstall(version) {
  var loaderDisplay = modloaderInfo.loader_display;
  var installLogLines = [];
  var headerHtml = modUploadProgressHtml('Instalando ' + loaderDisplay + ' ' + version + '...');
  var renderTimer = null;

  function pushLogLine(message) {
    if (message.length > MODLOADER_LOG_MAX_LINE_LENGTH) {
      message = message.slice(0, MODLOADER_LOG_MAX_LINE_LENGTH) + '… [línea truncada]';
    }
    installLogLines.push(message);
    if (installLogLines.length > MODLOADER_LOG_MAX_LINES) {
      installLogLines.splice(0, installLogLines.length - MODLOADER_LOG_MAX_LINES);
    }
  }

  function renderInstallLogNow() {
    renderTimer = null;
    var logHtml = installLogLines.length
      ? '<div class="log-viewer" id="modloader-install-log" style="height:220px;margin-top:10px;font-size:.74rem">'
        + installLogLines.map(escHtml).join('\n') + '</div>'
      : '';
    setModUploadModalBody(headerHtml + logHtml);
    var logEl = document.getElementById('modloader-install-log');
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  // El instalador puede imprimir cientos de líneas muy seguido (descarga de
  // librerías); reconstruir todo el log y el DOM en cada una congelaba la
  // pestaña y disparaba el uso de memoria. Se agrupan los renders cada
  // MODLOADER_LOG_RENDER_THROTTLE_MS en vez de uno por línea.
  function scheduleRender() {
    if (renderTimer === null) {
      renderTimer = setTimeout(renderInstallLogNow, MODLOADER_LOG_RENDER_THROTTLE_MS);
    }
  }

  function finish(finalHeaderHtml) {
    if (renderTimer !== null) {
      clearTimeout(renderTimer);
      renderTimer = null;
    }
    headerHtml = finalHeaderHtml;
    renderInstallLogNow();
  }

  document.getElementById('modloader-modal').classList.remove('show');
  setModOperationBusy(true);
  openModUploadModal('', 'Cambio de modloader', '🔧');
  renderInstallLogNow();

  var url = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/modloader/install/stream'
    + '?version=' + encodeURIComponent(version) + '&token=' + encodeURIComponent(authToken);
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
      setModOperationBusy(false);
      var resultHtml = data.success
        ? '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">'
          + '✅ Modloader actualizado a ' + escHtml(data.version) + '.</div>'
        : modErrorHtml(data.detail || 'Error desconocido');
      finish(resultHtml);
      if (data.success) {
        loadModpackVersion();
      }
    } else if (data.type === 'error') {
      source.close();
      setModOperationBusy(false);
      finish(modErrorHtml(data.detail || 'Error desconocido'));
    }
  };

  source.onerror = function() {
    source.close();
    setModOperationBusy(false);
    finish(modErrorHtml('Se perdió la conexión durante la instalación. Revisa el estado del servidor manualmente.'));
  };
}

document.getElementById('modloader-modal-close').addEventListener('click', function() {
  document.getElementById('modloader-modal').classList.remove('show');
});
document.getElementById('modloader-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});
