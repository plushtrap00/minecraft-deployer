// -- Descargar e instalar un modpack completo desde Modrinth/CurseForge -------
var dlSelectedPack = null; // {source, id, title}

document.getElementById('dl-search-btn').addEventListener('click', searchModpacks);
document.getElementById('dl-search-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    searchModpacks();
  }
});

function searchModpacks() {
  var source = document.getElementById('dl-source').value;
  var query = document.getElementById('dl-search-input').value.trim();
  var results = document.getElementById('dl-search-results');
  results.innerHTML = '<p class="empty-msg">Buscando...</p>';

  apiFetch('/api/modpack-install/search?source=' + encodeURIComponent(source) + '&query=' + encodeURIComponent(query))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        results.innerHTML = modErrorHtml(result.data.detail || 'Error al buscar');
        return;
      }
      renderModpackResults(result.data.results || []);
    })
    .catch(function() {
      results.innerHTML = modErrorHtml('Error de red');
    });
}

function renderModpackResults(items) {
  var results = document.getElementById('dl-search-results');
  if (!items.length) {
    results.innerHTML = '<p class="empty-msg">Sin resultados</p>';
    return;
  }
  results.innerHTML = '<div class="mods-table-wrap">' + items.map(function(item, i) {
    return '<div class="mod-list-item mod-search-result" data-index="' + i + '" style="cursor:pointer">'
      + (item.icon_url ? '<img src="' + escHtml(item.icon_url) + '" style="width:32px;height:32px;border-radius:6px;flex-shrink:0">' : '<span class="mod-icon">📦</span>')
      + '<div class="mod-info"><div class="mod-display">' + escHtml(item.title) + '</div>'
      + '<div class="mod-file">' + escHtml(item.author || '') + ' · ' + (item.downloads || 0).toLocaleString() + ' descargas</div></div>'
      + '</div>';
  }).join('') + '</div>';

  dlSearchResultsCache = items;
  results.querySelectorAll('.mod-search-result').forEach(function(el) {
    el.addEventListener('click', function() {
      selectModpack(dlSearchResultsCache[parseInt(this.dataset.index, 10)]);
    });
  });
}

var dlSearchResultsCache = [];

function selectModpack(pack) {
  dlSelectedPack = pack;
  document.getElementById('dl-selected-pack').innerHTML =
    '<div class="mod-list-item"><span class="mod-icon">📦</span>'
    + '<div class="mod-info"><div class="mod-display">' + escHtml(pack.title) + '</div>'
    + '<div class="mod-file">' + escHtml(pack.author || '') + '</div></div></div>';

  document.getElementById('dl-version-card').style.display = '';
  document.getElementById('dl-ram-card').style.display = '';
  document.getElementById('dl-install-card').style.display = '';
  document.getElementById('dl-progress-body').innerHTML = '';

  var versionSelect = document.getElementById('dl-version-select');
  versionSelect.innerHTML = '<option value="">Cargando versiones...</option>';

  apiFetch('/api/modpack-install/versions?source=' + encodeURIComponent(pack.source) + '&project_id=' + encodeURIComponent(pack.id))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok || !result.data.versions.length) {
        versionSelect.innerHTML = '<option value="">Sin versiones disponibles</option>';
        return;
      }
      versionSelect.innerHTML = result.data.versions.map(function(v) {
        var label = (v.version_number || v.filename) + ' (' + (v.game_versions || []).join(', ') + (v.loaders ? ' · ' + v.loaders.join(', ') : '') + ')';
        return '<option value="' + escHtml(String(v.version_id)) + '">' + escHtml(label) + '</option>';
      }).join('');
    })
    .catch(function() {
      versionSelect.innerHTML = '<option value="">Error de red</option>';
    });

  if (!document.getElementById('dl-server-name').value) {
    document.getElementById('dl-server-name').value = (pack.slug || pack.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  }
}

var DL_LOG_MAX_LINES = 300;
var DL_LOG_RENDER_THROTTLE_MS = 200;

document.getElementById('dl-install-btn').addEventListener('click', function() {
  if (!dlSelectedPack) {
    showToast('Elegí un modpack primero', 'error');
    return;
  }
  var versionId = document.getElementById('dl-version-select').value;
  if (!versionId) {
    showToast('Elegí una versión del modpack', 'error');
    return;
  }
  var serverName = document.getElementById('dl-server-name').value.trim();
  if (!serverName) {
    showToast('Escribí un nombre para el servidor', 'error');
    return;
  }
  var ramMin = document.getElementById('dl-ram-min-val').value + document.getElementById('dl-ram-min-unit').value;
  var ramMax = document.getElementById('dl-ram-max-val').value + document.getElementById('dl-ram-max-unit').value;

  var btn = this;
  btn.disabled = true;

  var logLines = [];
  var renderTimer = null;
  var body = document.getElementById('dl-progress-body');

  function pushLogLine(message) {
    logLines.push(message);
    if (logLines.length > DL_LOG_MAX_LINES) {
      logLines.splice(0, logLines.length - DL_LOG_MAX_LINES);
    }
  }

  function logHtml() {
    return logLines.length
      ? '<div class="log-viewer" id="dl-install-log" style="height:220px;margin-bottom:10px;font-size:.74rem">'
        + logLines.map(escHtml).join('\n') + '</div>'
      : '';
  }

  function renderNow() {
    renderTimer = null;
    body.innerHTML = logHtml();
    var logEl = document.getElementById('dl-install-log');
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  function scheduleRender() {
    if (renderTimer === null) {
      renderTimer = setTimeout(renderNow, DL_LOG_RENDER_THROTTLE_MS);
    }
  }

  function finish(resultHtml) {
    if (renderTimer !== null) {
      clearTimeout(renderTimer);
      renderTimer = null;
    }
    body.innerHTML = logHtml() + resultHtml;
    var logEl = document.getElementById('dl-install-log');
    if (logEl) {
      logEl.scrollTop = logEl.scrollHeight;
    }
    btn.disabled = false;
  }

  var url = '/api/modpack-install/stream?source=' + encodeURIComponent(dlSelectedPack.source)
    + '&project_id=' + encodeURIComponent(dlSelectedPack.id)
    + '&version_id=' + encodeURIComponent(versionId)
    + '&name=' + encodeURIComponent(serverName)
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
        ? '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Servidor "' + escHtml(data.name) + '" creado a partir del modpack.</div>'
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
    finish(modErrorHtml('Se perdió la conexión durante la instalación del modpack.'));
  };
});
