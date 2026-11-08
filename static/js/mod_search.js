// Buscar e instalar mods desde Modrinth / CurseForge.

// -- Buscar e instalar mods desde Modrinth / CurseForge ------------------------
var modSearchSource = 'modrinth';
var modSearchCategories = [];
var modSearchBusy = false;
var modSearchDebounceTimer = null;
var modSearchRequestToken = 0;

// Estado de la última página de resultados mostrada (para poder volver sin
// re-pedirla al servidor) y de la vista de versiones de un mod concreto.
var modSearchQuery = '';
var modSearchOffset = 0;
var modSearchLimit = 20;
var modSearchTotal = 0;
var modSearchFilesState = { items: [], page: 0, mod: null };

// -- Caché en memoria (LRU simple) ---------------------------------------------
// Nada de esto persiste entre recargas de página a propósito: es solo para no
// re-pedir la misma página/lista dos veces dentro de la misma sesión de uso
// del modal (ida y vuelta entre páginas, pestañas, o el detalle de un mod).
function createModSearchLru(maxSize) {
  var map = new Map();
  return {
    get: function(key) {
      if (!map.has(key)) {
        return undefined;
      }
      var value = map.get(key);
      map.delete(key);
      map.set(key, value); // reinsertar = marcarlo como el más reciente
      return value;
    },
    set: function(key, value) {
      if (map.has(key)) {
        map.delete(key);
      }
      map.set(key, value);
      if (map.size > maxSize) {
        map.delete(map.keys().next().value); // expulsa el más antiguo
      }
    },
    clear: function() {
      map.clear();
    }
  };
}

// ~30 páginas de 20 resultados: suficiente para navegar bastante sin acumular
// memoria sin límite si el usuario prueba muchos términos distintos.
var modSearchResultsCache = createModSearchLru(30);
var modSearchCategoriesCache = createModSearchLru(10); // como mucho 2 fuentes
var modSearchFilesCache = createModSearchLru(30);

function modSearchResultsCacheKey(source, query, categories, offset) {
  return source + '|' + query + '|' + categories.slice().sort().join(',') + '|' + offset;
}

// -- Caché real de íconos (bytes, no solo la URL) -------------------------------
// Modrinth/CurseForge sirven los íconos con "Cache-Control: s-maxage=..." (para
// CDNs compartidos) pero SIN "max-age"/"public", así que el navegador no tiene
// garantía de guardarlos en su propio caché: cada vez que se recreaban los
// <img> al volver a una página ya vista, se volvían a descargar por completo
// (de ahí los MB repetidos en la pestaña Network). Aquí se descarga el ícono
// UNA sola vez con fetch()+blob y se reusa un object URL en cualquier render
// posterior, sin volver a tocar la red pase lo que pase con esos headers.
var modSearchImageCache = new Map(); // url original -> object URL
var modSearchImagePending = new Map(); // url original -> [<img> esperando el blob]
var MOD_SEARCH_IMAGE_CACHE_MAX = 150;

function modSearchImageCacheSet(url, objectUrl) {
  modSearchImageCache.set(url, objectUrl);
  if (modSearchImageCache.size > MOD_SEARCH_IMAGE_CACHE_MAX) {
    var oldestKey = modSearchImageCache.keys().next().value;
    URL.revokeObjectURL(modSearchImageCache.get(oldestKey));
    modSearchImageCache.delete(oldestKey);
  }
}

function applyModSearchImage(imgEl, url) {
  var cached = modSearchImageCache.get(url);
  if (cached) {
    imgEl.src = cached;
    return;
  }
  var pending = modSearchImagePending.get(url);
  if (pending) {
    pending.push(imgEl); // ya hay una descarga en curso para esta misma URL
    return;
  }
  modSearchImagePending.set(url, [imgEl]);
  fetch(url)
    .then(function(response) {
      if (!response.ok) {
        throw new Error('bad response');
      }
      return response.blob();
    })
    .then(function(blob) {
      var objectUrl = URL.createObjectURL(blob);
      modSearchImageCacheSet(url, objectUrl);
      var waiters = modSearchImagePending.get(url) || [];
      modSearchImagePending.delete(url);
      waiters.forEach(function(el) { el.src = objectUrl; });
    })
    .catch(function() {
      // Si el fetch falla (p.ej. CORS bloqueado por el CDN), al menos que
      // cargue la imagen directo como antes, en vez de quedar en blanco.
      var waiters = modSearchImagePending.get(url) || [];
      modSearchImagePending.delete(url);
      waiters.forEach(function(el) { el.src = url; });
    });
}

function formatDownloads(n) {
  n = n || 0;
  if (n >= 1000000) {
    return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
  }
  if (n >= 1000) {
    return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  }
  return String(n);
}

function modSearchSpinnerHtml(text) {
  return '<div class="mod-upload-progress"><div class="mod-upload-spinner"></div><div>' + escHtml(text) + '</div></div>';
}

function modSearchBackButtonHtml() {
  return '<button type="button" class="btn-secondary btn-sm mod-search-back mb-s">' + icon('chevron-left') + 'Volver a resultados</button>';
}

// query precargada: usado tanto por "Buscar mods" (vacía) como por
// "Cambiar versión" en un mod ya instalado (nombre del mod) — desde ahí el
// usuario ve el resultado real marcado "Instalado" (mark_installed compara
// por mod_id, no por nombre de archivo, así que es fiable) y puede elegir
// cualquier versión, más nueva o más vieja: install_searched_mod() reusa
// process_mod_jar(), el mismo chequeo de versión anterior que ya dispara el
// modal de confirmación al subir un mod a mano.
function openModSearchModal(prefillQuery) {
  if (!currentModpack) {
    return;
  }
  document.getElementById('mod-search-input').value = prefillQuery || '';
  Array.prototype.forEach.call(document.querySelectorAll('#mod-search-tabs .mgmt-tab'), function(t) {
    t.classList.toggle('active', t.dataset.source === 'modrinth');
  });
  modSearchSource = 'modrinth';
  modSearchCategories = [];
  loadModSearchCategories(modSearchSource);
  document.getElementById('mod-search-modal').classList.add('show');
  runModSearch(prefillQuery || '', 0);
}

document.getElementById('mod-search-btn').addEventListener('click', function() {
  openModSearchModal('');
});

document.getElementById('mod-search-modal-close').addEventListener('click', function() {
  if (!modSearchBusy) {
    document.getElementById('mod-search-modal').classList.remove('show');
  }
});
document.getElementById('mod-search-modal').addEventListener('click', function(event) {
  if (event.target === this && !modSearchBusy) {
    this.classList.remove('show');
  }
});

document.getElementById('mod-search-tabs').addEventListener('click', function(event) {
  var tab = event.target.closest('.mgmt-tab');
  if (!tab || modSearchBusy) {
    return;
  }
  Array.prototype.forEach.call(this.querySelectorAll('.mgmt-tab'), function(t) { t.classList.remove('active'); });
  tab.classList.add('active');
  modSearchSource = tab.dataset.source;
  modSearchCategories = [];
  loadModSearchCategories(modSearchSource);
  runModSearch(document.getElementById('mod-search-input').value.trim(), 0);
});

// -- Filtro de categorías: panel con checkboxes y subcategorías expandibles ---
var modSearchCategoryPanelToggle = document.getElementById('mod-search-category-panel-toggle');
var modSearchCategoryPanelBody = document.getElementById('mod-search-category-panel-body');

// Colapsa/expande el panel entero (checkboxes + subcategorías), no toca la
// selección. Solo la flechita es clicable a propósito: el título y la lista
// no deben sentirse como parte de un botón gigante.
modSearchCategoryPanelToggle.addEventListener('click', function() {
  var collapsed = modSearchCategoryPanelBody.classList.toggle('collapsed');
  modSearchCategoryPanelToggle.classList.toggle('collapsed', collapsed);
  modSearchCategoryPanelToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
});

function renderModSearchCategoryOptions(categories) {
  return categories.map(function(c) {
    var childrenId = 'mod-search-subcats-' + escHtml(String(c.id));
    var hasChildren = c.children && c.children.length > 0;
    var row = '<div class="mod-search-category-row">'
      + '<label class="mod-search-category-option"><input type="checkbox" value="' + escHtml(String(c.id)) + '"> ' + escHtml(c.name) + '</label>'
      + (hasChildren ? '<button type="button" class="mod-search-category-expand" data-target="' + childrenId + '">+</button>' : '')
      + '</div>';
    var childrenHtml = hasChildren
      ? '<div class="mod-search-subcategory-list" id="' + childrenId + '">' + c.children.map(function(ch) {
          return '<label class="mod-search-category-option sub"><input type="checkbox" value="' + escHtml(String(ch.id)) + '"> ' + escHtml(ch.name) + '</label>';
        }).join('') + '</div>'
      : '';
    return row + childrenHtml;
  }).join('');
}

function loadModSearchCategories(source) {
  var cached = modSearchCategoriesCache.get(source);
  if (cached) {
    modSearchCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cached) || '<p class="empty-msg pad-s">Sin categorías</p>';
    return;
  }
  modSearchCategoryPanelBody.innerHTML = loadingHtml();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/search/categories?source=' + encodeURIComponent(source))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        modSearchCategoryPanelBody.innerHTML = '';
        document.getElementById('mod-search-modal-body').innerHTML = modErrorHtml(result.data.detail || 'No se pudieron cargar las categorías');
        return;
      }
      var cats = result.data.categories || [];
      modSearchCategoriesCache.set(source, cats);
      modSearchCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cats) || '<p class="empty-msg pad-s">Sin categorías</p>';
    })
    .catch(function() {
      modSearchCategoryPanelBody.innerHTML = '<p class="empty-msg pad-s">Error al cargar categorías</p>';
    });
}

modSearchCategoryPanelBody.addEventListener('click', function(event) {
  var expandBtn = event.target.closest('.mod-search-category-expand');
  if (!expandBtn) {
    return;
  }
  var target = document.getElementById(expandBtn.dataset.target);
  var isOpen = target.classList.toggle('show');
  expandBtn.textContent = isOpen ? '−' : '+';
  expandBtn.classList.toggle('open', isOpen);
});

modSearchCategoryPanelBody.addEventListener('change', function(event) {
  if (event.target.type !== 'checkbox') {
    return;
  }
  var value = event.target.value;
  var idx = modSearchCategories.indexOf(value);
  if (event.target.checked && idx === -1) {
    modSearchCategories.push(value);
  } else if (!event.target.checked && idx !== -1) {
    modSearchCategories.splice(idx, 1);
  }
  runModSearch(document.getElementById('mod-search-input').value.trim(), 0);
});

// -- Input de texto: busca solo/a con Enter, o tras una pausa al escribir -----
var modSearchInputEl = document.getElementById('mod-search-input');

modSearchInputEl.addEventListener('input', function() {
  clearTimeout(modSearchDebounceTimer);
  var value = this.value;
  modSearchDebounceTimer = setTimeout(function() {
    runModSearch(value.trim(), 0);
  }, 400);
});

modSearchInputEl.addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    clearTimeout(modSearchDebounceTimer);
    runModSearch(this.value.trim(), 0);
  }
});

// -- Búsqueda (resultados paginados por el servidor) ---------------------------

function runModSearch(query, offset) {
  offset = offset || 0;
  modSearchQuery = query;
  document.getElementById('mod-search-pagination').innerHTML = '';

  var cacheKey = modSearchResultsCacheKey(modSearchSource, query, modSearchCategories, offset);
  var cached = modSearchResultsCache.get(cacheKey);
  if (cached) {
    modSearchOffset = offset;
    modSearchLimit = cached.limit;
    modSearchTotal = cached.total;
    renderModSearchResults(cached.results);
    return;
  }

  var body = document.getElementById('mod-search-modal-body');
  body.innerHTML = modSearchSpinnerHtml('Buscando...');

  var url = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/search?source=' + encodeURIComponent(modSearchSource)
    + '&query=' + encodeURIComponent(query) + '&offset=' + offset;
  if (modSearchCategories.length) {
    url += '&category=' + encodeURIComponent(modSearchCategories.join(','));
  }

  var requestToken = ++modSearchRequestToken;
  apiFetch(url)
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (requestToken !== modSearchRequestToken) {
        return; // se disparó otra búsqueda mientras esta estaba en vuelo
      }
      if (!result.ok) {
        body.innerHTML = modErrorHtml(result.data.detail || 'Error al buscar');
        return;
      }
      modSearchOffset = offset;
      modSearchLimit = result.data.limit || 20;
      modSearchTotal = result.data.total || 0;
      modSearchResultsCache.set(cacheKey, {
        results: result.data.results || [], total: modSearchTotal, limit: modSearchLimit
      });
      renderModSearchResults(result.data.results || []);
    })
    .catch(function(error) {
      if (requestToken !== modSearchRequestToken) {
        return;
      }
      body.innerHTML = modErrorHtml('No se pudo conectar con el panel: ' + error.message);
    });
}

function renderModSearchResults(results) {
  var body = document.getElementById('mod-search-modal-body');
  if (!results.length) {
    body.innerHTML = emptyArt('spyglass', 'Ningún mod a la vista', 'No hay resultados para esta versión y modloader. Prueba con otras palabras o quita algún filtro.');
    document.getElementById('mod-search-pagination').innerHTML = '';
    return;
  }
  body.innerHTML = results.map(function(mod, i) {
    // Sin src todavía: applyModSearchImage() lo completa abajo, desde caché
    // (blob ya descargado) o disparando la descarga una sola vez.
    var iconHtml = mod.icon_url
      ? '<img class="mod-search-icon" data-icon-url="' + escHtml(mod.icon_url) + '" alt="" loading="lazy" decoding="async">'
      : '<span class="mod-search-icon mod-search-icon-empty">' + icon('puzzle') + '</span>';
    var badge = mod.installed ? '<span class="mod-search-badge">Instalado</span>' : '';
    var desc = mod.description ? '<div class="mod-search-desc">' + escHtml(mod.description) + '</div>' : '';
    var link = isWebUrl(mod.page_url)
      ? '<a class="mod-search-link" href="' + escHtml(mod.page_url) + '" target="_blank" rel="noopener" title="Ver página del mod" onclick="event.stopPropagation()">↗</a>'
      : '';
    return '<div class="mod-search-result-item" data-index="' + i + '">'
      + iconHtml
      + '<div class="mod-search-info">'
      + '<div class="mod-search-title-row"><span class="mod-search-title">' + escHtml(mod.title) + '</span>' + badge + '</div>'
      + desc
      + '<div class="mod-search-meta">' + escHtml(mod.author || '') + ' · ' + formatDownloads(mod.downloads) + ' descargas' + '</div>'
      + '</div>'
      + link
      + '</div>';
  }).join('');
  body._modSearchResults = results;

  Array.prototype.forEach.call(body.querySelectorAll('img[data-icon-url]'), function(img) {
    applyModSearchImage(img, img.dataset.iconUrl);
  });

  var totalPages = Math.max(1, Math.ceil(modSearchTotal / modSearchLimit));
  var page = Math.floor(modSearchOffset / modSearchLimit);
  renderModModalPagination('mod-search-pagination', page, totalPages, function(p) {
    runModSearch(modSearchQuery, p * modSearchLimit);
  });
}

// -- Versiones/archivos de un mod (todas las traídas de una vez, paginadas en cliente) --

function openModSearchFiles(mod) {
  document.getElementById('mod-search-pagination').innerHTML = '';

  var cacheKey = mod.source + '|' + mod.id;
  var cachedFiles = modSearchFilesCache.get(cacheKey);
  if (cachedFiles) {
    modSearchFilesState = { items: cachedFiles, page: 0, mod: mod };
    renderModSearchFilesPage();
    return;
  }

  var body = document.getElementById('mod-search-modal-body');
  body.innerHTML = modSearchSpinnerHtml('Buscando versiones compatibles...');
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/search/' + encodeURIComponent(mod.source) + '/' + encodeURIComponent(mod.id) + '/files')
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        body.innerHTML = modSearchBackButtonHtml() + modErrorHtml(result.data.detail || 'Error al obtener versiones');
        return;
      }
      var files = result.data.files || [];
      modSearchFilesCache.set(cacheKey, files);
      modSearchFilesState = { items: files, page: 0, mod: mod };
      renderModSearchFilesPage();
    })
    .catch(function(error) {
      body.innerHTML = modSearchBackButtonHtml() + modErrorHtml('No se pudo conectar con el panel: ' + error.message);
    });
}

function renderModSearchFilesPage() {
  var body = document.getElementById('mod-search-modal-body');
  var mod = modSearchFilesState.mod;
  var files = modSearchFilesState.items;
  var badge = mod.installed ? ' <span class="mod-search-badge">Instalado</span>' : '';
  var header = '<div class="mod-search-files-header">'
    + '<button type="button" class="btn-secondary btn-sm mod-search-back">' + icon('chevron-left') + 'Volver a resultados</button>'
    + '<span class="mod-search-title">' + escHtml(mod.title) + badge + '</span>'
    + '</div>';

  if (!files.length) {
    body.innerHTML = header + '<p class="empty-msg">No hay versiones compatibles con la versión/modloader de este servidor.</p>';
    document.getElementById('mod-search-pagination').innerHTML = '';
    return;
  }

  var start = modSearchFilesState.page * MOD_MODAL_PAGE_SIZE;
  var pageItems = files.slice(start, start + MOD_MODAL_PAGE_SIZE);
  var list = pageItems.map(function(f, i) {
    var available = !!f.download_url;
    var detail = escHtml(f.filename) + (f.game_versions && f.game_versions.length ? ' · MC ' + escHtml(f.game_versions.join(', ')) : '');
    return '<div class="mod-modal-item">'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(f.version_number || f.filename) + '</div>'
      + '<div class="mod-modal-detail">' + detail + '</div></div>'
      + '<div class="mod-search-file-action">'
      + (available
        ? '<button type="button" class="btn-sm mod-search-install" data-index="' + (start + i) + '">Instalar</button>'
        : '<span class="text-muted text-xs">Sin descarga directa</span>')
      + '</div>'
      + '</div>';
  }).join('');
  body.innerHTML = header + '<div class="mods-table-wrap">' + list + '</div>';

  var totalPages = Math.max(1, Math.ceil(files.length / MOD_MODAL_PAGE_SIZE));
  renderModModalPagination('mod-search-pagination', modSearchFilesState.page, totalPages, function(p) {
    modSearchFilesState.page = p;
    renderModSearchFilesPage();
  });
}

document.getElementById('mod-search-modal-body').addEventListener('click', function(event) {
  if (modSearchBusy) {
    return;
  }
  var row = event.target.closest('.mod-search-result-item');
  if (row) {
    var mod = this._modSearchResults[Number(row.dataset.index)];
    if (mod) {
      openModSearchFiles(mod);
    }
    return;
  }
  var backBtn = event.target.closest('.mod-search-back');
  if (backBtn) {
    // Vuelve a la misma página de resultados: sale de caché si sigue ahí, y si
    // se vació tras instalar un mod se vuelve a pedir para que salga "Instalado".
    runModSearch(modSearchQuery, modSearchOffset);
    return;
  }
  var installBtn = event.target.closest('.mod-search-install');
  if (installBtn) {
    var file = modSearchFilesState.items[Number(installBtn.dataset.index)];
    if (file) {
      installSearchedMod(modSearchFilesState.mod, file, installBtn);
    }
  }
});

function installSearchedMod(mod, file, buttonEl) {
  modSearchBusy = true;
  buttonEl.disabled = true;
  buttonEl.textContent = 'Instalando...';

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/search/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source: mod.source,
      download_url: file.download_url,
      filename: file.filename
    })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      modSearchBusy = false;
      if (result.ok && result.data.success && result.data.needs_confirmation && result.data.needs_confirmation.length) {
        document.getElementById('mod-search-modal').classList.remove('show');
        openDowngradeModal(result.data.batch_id, result.data.needs_confirmation);
        return;
      }
      var body = document.getElementById('mod-search-modal-body');
      if (result.ok && result.data.success) {
        showToast('Mod instalado: ' + result.data.filename, 'success');
        // Se vuelve a pintar la lista de versiones (con «Volver a resultados»)
        // en vez de sustituirla por el aviso: si no, el modal se quedaba sin
        // forma de volver salvo tocando los filtros.
        mod.installed = true;
        renderModSearchFilesPage();
        var header = body.querySelector('.mod-search-files-header');
        if (header) {
          header.insertAdjacentHTML('afterend', '<div class="mb-m">' + noticeHtml('ok', 'Mod instalado: ' + escHtml(result.data.filename)) + '</div>');
        }
        // El flag "installed" de otras páginas ya cacheadas puede haber
        // quedado desactualizado con este mod recién instalado.
        modSearchResultsCache.clear();
        loadModsList();
        checkModDependencies(false);
      } else {
        buttonEl.disabled = false;
        buttonEl.textContent = 'Instalar';
        showToast(result.data.detail || 'Error al instalar', 'error');
      }
    })
    .catch(function(error) {
      modSearchBusy = false;
      buttonEl.disabled = false;
      buttonEl.textContent = 'Instalar';
      showToast('No se pudo conectar con el panel: ' + error.message, 'error');
    });
}
