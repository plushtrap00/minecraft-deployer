// -- Descargar e instalar un modpack completo desde Modrinth/CurseForge -------
// Mismo patrón visual/funcional que "Buscar mods online" (mods.js): pestañas
// de fuente, panel de categorías colapsable y resultados paginados. Reusa
// varias funciones genéricas ya definidas ahí (renderModModalPagination,
// applyModSearchImage, formatDownloads, createModSearchLru,
// renderModSearchCategoryOptions) en vez de duplicarlas.
var dlSelectedPack = null; // {source, id, title, slug, author}
var dlSearchInitialized = false;

var dlSource = 'modrinth';
var dlCategories = [];
var dlLoaderFilter = '';
var dlMcVersionFilter = '';
var dlMcVersionsLoaded = false;
var dlBusy = false;
var dlDebounceTimer = null;
var dlRequestToken = 0;

var dlQuery = '';
var dlOffset = 0;
var dlLimit = 20;
var dlTotal = 0;
var dlSearchResultsCache = []; // última página cruda, para mapear el click por índice

var dlResultsCache = createModSearchLru(30);
var dlCategoriesCache = createModSearchLru(4); // como mucho 2 fuentes

function dlResultsCacheKey(source, query, categories, offset, loader, mcVersion) {
  return source + '|' + query + '|' + categories.slice().sort().join(',') + '|' + offset + '|' + loader + '|' + mcVersion;
}

// Llamado por create_server.js la primera vez que se abre "Descargar modpack".
function initDlSearchIfNeeded() {
  if (dlSearchInitialized) {
    return;
  }
  dlSearchInitialized = true;
  loadDlCategories(dlSource);
  loadDlMcVersions();
  runDlSearch('', 0);
}

// -- Filtros de modloader / versión de Minecraft -------------------------------
// Reutiliza el mismo endpoint que ya usa "Crear servidor nuevo" para listar
// versiones oficiales de Minecraft (API de Mojang), en vez de duplicar la lista.
function loadDlMcVersions() {
  if (dlMcVersionsLoaded) {
    return;
  }
  dlMcVersionsLoaded = true;
  apiFetch('/api/create-server/mc-versions')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var select = document.getElementById('dl-mc-version-filter');
      var versions = data.versions || [];
      versions.forEach(function(v) {
        var opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);
      });
    })
    .catch(function() {}); // sin versiones para filtrar no bloquea la búsqueda
}

document.getElementById('dl-loader-filter').addEventListener('change', function() {
  dlLoaderFilter = this.value;
  runDlSearch(document.getElementById('dl-search-input').value.trim(), 0);
});

document.getElementById('dl-mc-version-filter').addEventListener('change', function() {
  dlMcVersionFilter = this.value;
  runDlSearch(document.getElementById('dl-search-input').value.trim(), 0);
});

// -- Pestañas de fuente ---------------------------------------------------------
document.getElementById('dl-source-tabs').addEventListener('click', function(event) {
  var tab = event.target.closest('.mgmt-tab');
  if (!tab || dlBusy) {
    return;
  }
  Array.prototype.forEach.call(this.querySelectorAll('.mgmt-tab'), function(t) { t.classList.remove('active'); });
  tab.classList.add('active');
  dlSource = tab.dataset.source;
  dlCategories = [];
  loadDlCategories(dlSource);
  runDlSearch(document.getElementById('dl-search-input').value.trim(), 0);
});

// -- Panel de categorías: checkboxes + subcategorías expandibles ---------------
var dlCategoryPanelToggle = document.getElementById('dl-category-panel-toggle');
var dlCategoryPanelBody = document.getElementById('dl-category-panel-body');

dlCategoryPanelToggle.addEventListener('click', function() {
  var collapsed = dlCategoryPanelBody.classList.toggle('collapsed');
  dlCategoryPanelToggle.textContent = collapsed ? '▼' : '▲';
});

function loadDlCategories(source) {
  var cached = dlCategoriesCache.get(source);
  if (cached) {
    dlCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cached) || '<p class="empty-msg" style="padding:6px">Sin categorías</p>';
    return;
  }
  dlCategoryPanelBody.innerHTML = '<p class="empty-msg" style="padding:6px">Cargando...</p>';
  apiFetch('/api/modpack-install/categories?source=' + encodeURIComponent(source))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        dlCategoryPanelBody.innerHTML = '<p class="empty-msg" style="padding:6px">Error al cargar categorías</p>';
        return;
      }
      var cats = result.data.categories || [];
      dlCategoriesCache.set(source, cats);
      dlCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cats) || '<p class="empty-msg" style="padding:6px">Sin categorías</p>';
    })
    .catch(function() {
      dlCategoryPanelBody.innerHTML = '<p class="empty-msg" style="padding:6px">Error al cargar categorías</p>';
    });
}

dlCategoryPanelBody.addEventListener('click', function(event) {
  var expandBtn = event.target.closest('.mod-search-category-expand');
  if (!expandBtn) {
    return;
  }
  var target = document.getElementById(expandBtn.dataset.target);
  var isOpen = target.classList.toggle('show');
  expandBtn.textContent = isOpen ? '−' : '+';
  expandBtn.classList.toggle('open', isOpen);
});

dlCategoryPanelBody.addEventListener('change', function(event) {
  if (event.target.type !== 'checkbox') {
    return;
  }
  var value = event.target.value;
  var idx = dlCategories.indexOf(value);
  if (event.target.checked && idx === -1) {
    dlCategories.push(value);
  } else if (!event.target.checked && idx !== -1) {
    dlCategories.splice(idx, 1);
  }
  runDlSearch(document.getElementById('dl-search-input').value.trim(), 0);
});

// -- Input de búsqueda: busca solo/a con Enter, o tras una pausa al escribir ---
var dlSearchInputEl = document.getElementById('dl-search-input');

dlSearchInputEl.addEventListener('input', function() {
  clearTimeout(dlDebounceTimer);
  var value = this.value;
  dlDebounceTimer = setTimeout(function() {
    runDlSearch(value.trim(), 0);
  }, 400);
});

dlSearchInputEl.addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    clearTimeout(dlDebounceTimer);
    runDlSearch(this.value.trim(), 0);
  }
});

// -- Búsqueda (resultados paginados por el servidor) ---------------------------
function runDlSearch(query, offset) {
  offset = offset || 0;
  dlQuery = query;
  document.getElementById('dl-search-pagination').innerHTML = '';

  var cacheKey = dlResultsCacheKey(dlSource, query, dlCategories, offset, dlLoaderFilter, dlMcVersionFilter);
  var cached = dlResultsCache.get(cacheKey);
  if (cached) {
    dlOffset = offset;
    dlLimit = cached.limit;
    dlTotal = cached.total;
    renderDlResults(cached.results);
    return;
  }

  var body = document.getElementById('dl-search-results');
  body.innerHTML = modSearchSpinnerHtml('Buscando...');

  var url = '/api/modpack-install/search?source=' + encodeURIComponent(dlSource)
    + '&query=' + encodeURIComponent(query) + '&offset=' + offset;
  if (dlCategories.length) {
    url += '&category=' + encodeURIComponent(dlCategories.join(','));
  }
  if (dlLoaderFilter) {
    url += '&loader=' + encodeURIComponent(dlLoaderFilter);
  }
  if (dlMcVersionFilter) {
    url += '&mc_version=' + encodeURIComponent(dlMcVersionFilter);
  }

  var requestToken = ++dlRequestToken;
  apiFetch(url)
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (requestToken !== dlRequestToken) {
        return; // se disparó otra búsqueda mientras esta estaba en vuelo
      }
      if (!result.ok) {
        body.innerHTML = modErrorHtml(result.data.detail || 'Error al buscar');
        return;
      }
      dlOffset = offset;
      dlLimit = result.data.limit || 20;
      dlTotal = result.data.total || 0;
      dlResultsCache.set(cacheKey, { results: result.data.results || [], total: dlTotal, limit: dlLimit });
      renderDlResults(result.data.results || []);
    })
    .catch(function(error) {
      if (requestToken !== dlRequestToken) {
        return;
      }
      body.innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
}

function renderDlResults(results) {
  dlSearchResultsCache = results;
  var body = document.getElementById('dl-search-results');
  if (!results.length) {
    body.innerHTML = '<p class="empty-msg">Sin resultados.</p>';
    document.getElementById('dl-search-pagination').innerHTML = '';
    return;
  }
  body.innerHTML = results.map(function(item, i) {
    var icon = item.icon_url
      ? '<img class="mod-search-icon" data-icon-url="' + escHtml(item.icon_url) + '" alt="" loading="lazy" decoding="async">'
      : '<span class="mod-search-icon" style="display:flex;align-items:center;justify-content:center;font-size:1.2rem">📦</span>';
    var desc = item.description ? '<div class="mod-search-desc">' + escHtml(item.description) + '</div>' : '';
    var link = item.page_url
      ? '<a class="mod-search-link" href="' + escHtml(item.page_url) + '" target="_blank" rel="noopener" title="Ver página del modpack" onclick="event.stopPropagation()">↗</a>'
      : '';
    return '<div class="mod-search-result-item" data-index="' + i + '" style="cursor:pointer">'
      + icon
      + '<div class="mod-search-info">'
      + '<div class="mod-search-title-row"><span class="mod-search-title">' + escHtml(item.title) + '</span></div>'
      + desc
      + '<div class="mod-search-meta">' + escHtml(item.author || '') + ' · ⬇ ' + formatDownloads(item.downloads) + '</div>'
      + '</div>'
      + link
      + '</div>';
  }).join('');

  Array.prototype.forEach.call(body.querySelectorAll('img[data-icon-url]'), function(img) {
    applyModSearchImage(img, img.dataset.iconUrl);
  });

  Array.prototype.forEach.call(body.querySelectorAll('.mod-search-result-item'), function(el) {
    el.addEventListener('click', function() {
      selectModpackToInstall(dlSearchResultsCache[parseInt(this.dataset.index, 10)]);
    });
  });

  var totalPages = Math.max(1, Math.ceil(dlTotal / dlLimit));
  var page = Math.floor(dlOffset / dlLimit);
  renderModModalPagination('dl-search-pagination', page, totalPages, function(p) {
    runDlSearch(dlQuery, p * dlLimit);
  });
}

// Nombre distinto a propósito: manage.js ya tiene un selectModpack() global
// (abre el panel de gestión de un modpack instalado) — todos los <script> de
// esta app comparten el mismo scope global (sin módulos), así que un nombre
// igual pisaba en silencio esa función al cargar este archivo después,
// rompiendo el acceso a "Gestión de modpacks" por completo.
function selectModpackToInstall(pack) {
  dlSelectedPack = pack;
  document.getElementById('dl-selected-pack').innerHTML =
    '<div class="mod-list-item"><span class="mod-icon">📦</span>'
    + '<div class="mod-info"><div class="mod-display">' + escHtml(pack.title) + '</div>'
    + '<div class="mod-file">' + escHtml(pack.author || '') + '</div></div></div>';

  document.getElementById('dl-version-card').style.display = '';
  document.getElementById('dl-ram-card').style.display = '';
  document.getElementById('dl-install-card').style.display = '';
  document.getElementById('dl-progress-body').innerHTML = '';
  document.getElementById('dl-duplicate-warning').innerHTML = '';
  dlDuplicateCheckPending = false;
  dlDuplicateMatches = [];
  dlInstallBlocked = false;
  updateDlInstallBtnAppearance();

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
      checkDlDuplicate();
    })
    .catch(function() {
      versionSelect.innerHTML = '<option value="">Error de red</option>';
    });

  if (!document.getElementById('dl-server-name').value) {
    document.getElementById('dl-server-name').value = (pack.slug || pack.title || '').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
  }
}

// -- Aviso de posible instalación duplicada ------------------------------------
// Compara la lista de mods de la versión elegida contra los servidores ya
// existentes (misma versión de MC) SIN descargar nada pesado — ver
// find_similar_installed_modpacks() en services/modpack_install.py. Mientras
// se comprueba, el botón de instalar queda bloqueado (para que no dé tiempo a
// pulsarlo antes de saber el resultado); si encuentra coincidencia, el botón
// se marca con ⚠️ pero sigue permitiendo instalar igualmente (puede haber más
// de un servidor legítimo con el mismo modpack: mundos separados, pruebas...).
var dlDuplicateCheckToken = 0;
var dlDuplicateCheckPending = false;
var dlDuplicateMatches = [];
var dlInstallBusy = false;
var dlInstallBlocked = false;

document.getElementById('dl-version-select').addEventListener('change', checkDlDuplicate);

function updateDlInstallBtnAppearance() {
  var btn = document.getElementById('dl-install-btn');
  btn.disabled = dlInstallBusy || dlDuplicateCheckPending || dlInstallBlocked;
  if (dlInstallBusy) {
    return;
  }
  // El botón vive en la tarjeta "4 · Instalar modpack", separada de donde
  // aparece el aviso de "Comprobando si ya está instalado..." (tarjeta "2");
  // sin este texto en el propio botón, mientras se comprueba solo se veía
  // deshabilitado sin ninguna pista de por qué, como si estuviera roto.
  if (dlDuplicateCheckPending) {
    btn.innerHTML = '🔍 Comprobando si ya está instalado...';
    return;
  }
  if (dlInstallBlocked) {
    btn.innerHTML = '🚫 Descarga bloqueada por el autor';
    return;
  }
  btn.innerHTML = dlDuplicateMatches.length ? '⚠️ Descargar e instalar' : '🌐 Descargar e instalar';
}

function checkDlDuplicate() {
  var warningEl = document.getElementById('dl-duplicate-warning');
  var versionId = document.getElementById('dl-version-select').value;
  if (!dlSelectedPack || !versionId) {
    warningEl.innerHTML = '';
    dlDuplicateCheckPending = false;
    dlDuplicateMatches = [];
    dlInstallBlocked = false;
    updateDlInstallBtnAppearance();
    return;
  }

  var requestToken = ++dlDuplicateCheckToken;
  dlDuplicateCheckPending = true;
  dlDuplicateMatches = [];
  dlInstallBlocked = false;
  updateDlInstallBtnAppearance();
  warningEl.innerHTML = '<p class="empty-msg" style="padding:6px 0;font-size:.78rem">🔍 Comprobando si ya está instalado...</p>';

  var url = '/api/modpack-install/check-existing?source=' + encodeURIComponent(dlSelectedPack.source)
    + '&project_id=' + encodeURIComponent(dlSelectedPack.id) + '&version_id=' + encodeURIComponent(versionId);

  apiFetch(url)
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (requestToken !== dlDuplicateCheckToken) {
        return; // se disparó otra comprobación mientras esta estaba en vuelo
      }
      dlDuplicateCheckPending = false;
      var data = result.ok ? result.data : {};
      dlDuplicateMatches = data.matches || [];
      dlInstallBlocked = !!data.blocked;
      if (dlInstallBlocked) {
        warningEl.innerHTML = dlBlockedHtml(data.reason);
      } else if (dlDuplicateMatches.length) {
        warningEl.innerHTML = dlDuplicateWarningHtml(dlDuplicateMatches);
      } else if (result.ok && data.checked === false) {
        warningEl.innerHTML = '<p class="empty-msg" style="padding:6px 0;font-size:.78rem">ℹ️ No se pudo comprobar si ya está instalado (' + escHtml(data.reason || 'motivo desconocido') + ').</p>';
      } else {
        warningEl.innerHTML = '';
      }
      updateDlInstallBtnAppearance();
    })
    .catch(function() {
      if (requestToken !== dlDuplicateCheckToken) {
        return;
      }
      dlDuplicateCheckPending = false;
      dlDuplicateMatches = []; // sin conexión no se puede comprobar: no bloquear por esto
      dlInstallBlocked = false;
      warningEl.innerHTML = '';
      updateDlInstallBtnAppearance();
    });
}

function dlDuplicateWarningHtml(matches) {
  var lines = matches.map(function(m) {
    return '«' + escHtml(m.server_name) + '» (' + m.overlap_pct + '% de mods coinciden)';
  }).join(', ');
  return '<div style="background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.35);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--yellow);margin-top:10px">'
    + '⚠️ Esta versión se parece a lo ya instalado en ' + lines + '. Puede que ya la tengas — revisa antes de crear otro servidor.</div>';
}

function dlBlockedHtml(reason) {
  var pageLink = dlSelectedPack && dlSelectedPack.page_url
    ? '<a href="' + escHtml(dlSelectedPack.page_url) + '" target="_blank" rel="noopener">la página del modpack en CurseForge</a>'
    : 'la página del modpack en CurseForge';
  return '<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:10px 14px;font-size:.82rem">'
    + '<div style="color:var(--red);font-weight:600;margin-bottom:8px">🚫 ' + escHtml(reason || 'El autor bloqueó la descarga de este modpack por terceros.') + '</div>'
    + '<div style="color:var(--muted)">Cómo instalarlo de todas formas:</div>'
    + '<ol style="margin:6px 0 0 18px;padding:0;color:var(--muted);line-height:1.6">'
    + '<li>Entra en ' + pageLink + ' y ve a la pestaña <b>Files</b>.</li>'
    + '<li>Si esa versión tiene un archivo de <b>«Server Files»</b> aparte del pack normal, descárgalo y súbelo aquí con <b>«📦 Importar modpack existente»</b>.</li>'
    + '<li>Si no hay server files, crea un servidor vacío con <b>«🆕 Crear servidor nuevo»</b> usando el modloader y la versión de Minecraft que se ven en el desplegable de arriba, y añade los mods a mano (subiéndolos o con «🔎 Buscar mods online» una vez creado).</li>'
    + '</ol></div>';
}

var DL_LOG_MAX_LINES = 300;
var DL_LOG_RENDER_THROTTLE_MS = 200;

document.getElementById('dl-install-btn').addEventListener('click', function() {
  if (!dlSelectedPack) {
    showToast('Elige un modpack primero', 'error');
    return;
  }
  var versionId = document.getElementById('dl-version-select').value;
  if (!versionId) {
    showToast('Elige una versión del modpack', 'error');
    return;
  }
  var serverName = document.getElementById('dl-server-name').value.trim();
  if (!serverName) {
    showToast('Escribe un nombre para el servidor', 'error');
    return;
  }
  var ramMin = document.getElementById('dl-ram-min-val').value + document.getElementById('dl-ram-min-unit').value;
  var ramMax = document.getElementById('dl-ram-max-val').value + document.getElementById('dl-ram-max-unit').value;

  var btn = this;
  dlInstallBusy = true;
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
    dlInstallBusy = false;
    updateDlInstallBtnAppearance();
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
