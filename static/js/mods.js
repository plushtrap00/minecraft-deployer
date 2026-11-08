// -- Mods list ----------------------------------------------------------------
var allMods = [];
var currentModpackVersion = {};

// -- Menú «Más opciones» de acciones (duplicados / solo-cliente / borrar deshabilitados) --
// Los botones mantienen los mismos id que antes (mod-duplicates-btn, etc.),
// solo cambia dónde viven visualmente, así que sus propios listeners (más
// abajo en este archivo) no necesitan tocarse.
document.getElementById('mods-menu-btn').addEventListener('click', function(event) {
  event.stopPropagation();
  var isOpen = document.getElementById('mods-menu-dropdown').classList.toggle('show');
  this.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
});

document.getElementById('mods-menu-dropdown').addEventListener('click', function(event) {
  if (event.target.closest('.mods-menu-item')) {
    this.classList.remove('show');
    document.getElementById('mods-menu-btn').setAttribute('aria-expanded', 'false');
  }
});

document.addEventListener('click', function(event) {
  var menu = document.getElementById('mods-menu');
  if (menu && !menu.contains(event.target)) {
    document.getElementById('mods-menu-dropdown').classList.remove('show');
    document.getElementById('mods-menu-btn').setAttribute('aria-expanded', 'false');
  }
});

function loadModpackVersion() {
  if (!currentModpack) {
    return;
  }
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/version')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      currentModpackVersion = data;
      var badge = document.getElementById('modpack-version-badge');
      if (!badge) {
        return;
      }
      if (data.mc_version || data.modloader) {
        var modloader = data.modloader || 'Unknown';
        var modloaderClass = modloader.toLowerCase().replace('/', '-').split(' ')[0];
        badge.innerHTML = '<span class="version-badge ' + modloaderClass + '">'
          + (data.mc_version ? 'MC ' + data.mc_version : '')
          + (data.mc_version && data.modloader ? ' · ' : '')
          + (data.modloader ? data.modloader : '')
          + (data.modloader_version ? ' ' + data.modloader_version : '')
          + '</span>';
        badge.style.display = '';
      } else {
        badge.style.display = 'none';
      }
    })
    .catch(function() {});
}

// Mods que el autor del modpack bloqueó para descarga por terceros al
// instalarlo desde CurseForge (ver services/pending_mods.py::get_pending_mods) —
// mientras sigan en la lista, el servidor se niega a arrancar (routes/server.py).
function loadPendingMods() {
  var banner = document.getElementById('mods-pending-banner');
  if (!currentModpack || !banner) {
    return;
  }
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/pending-mods')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var pending = data.pending_mods || [];
      if (!pending.length) {
        banner.style.display = 'none';
        return;
      }
      banner.innerHTML = icon('clock') + ' <strong>' + pending.length + ' mod(s) pendientes de instalar</strong> — '
        + 'el autor de este modpack bloqueó su descarga por terceros, así que hay que importarlos a mano '
        + '(arriba: arrastra el .jar o usa "Subir carpeta de mods"). El servidor no arrancará hasta que estén todos: '
        + pending.map(escHtml).join(', ');
      banner.style.display = '';
    })
    .catch(function() { banner.style.display = 'none'; });
}

function loadModsList() {
  if (!currentModpack) {
    return;
  }
  var list = document.getElementById('mods-list');
  if (!list) {
    return;
  }
  list.innerHTML = loadingHtml();
  document.getElementById('mods-count').textContent = '';
  // Se reengancha aquí (en vez de en cada sitio que llama a loadModsList() tras
  // subir/borrar/togglear un mod) para que la lista de pendientes se
  // refresque sola cada vez que la de mods cambia, sin tener que acordarse de
  // añadirlo en cada punto nuevo que toque mods/.
  loadPendingMods();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      allMods = data.mods || [];
      if (!data.exists) {
        list.innerHTML = '<p class="empty-msg">No se encontró carpeta <code>mods/</code> en este modpack.</p>';
        return;
      }
      applyModsFilters();
    })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg text-red">Error al cargar mods</p>';
    });
}

function renderModsList(mods) {
  var list = document.getElementById('mods-list');
  var count = document.getElementById('mods-count');
  if (!list) {
    return;
  }
  if (count) {
    count.textContent = mods.length + ' / ' + allMods.length + ' mods';
  }
  if (!mods.length) {
    list.innerHTML = '<p class="empty-msg pad-m">Ningún mod coincide con la búsqueda o el filtro.</p>';
    return;
  }
  var html = '<div class="mods-table-wrap">';
  mods.forEach(function(mod) {
    var disabledClass = mod.enabled ? '' : ' is-disabled';
    var disabledLabel = mod.enabled ? '' : '<span class="mod-disabled-label">desactivado</span>';
    var toggleTitle = mod.enabled ? 'Deshabilitar mod' : 'Habilitar mod';
    html += '<div class="mod-list-item' + disabledClass + '">'
      + '<span class="mod-icon">' + icon('puzzle') + '</span>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.name) + '</div>'
      + '<div class="mod-file">' + escHtml(mod.filename) + '</div></div>'
      + disabledLabel
      + '<button type="button" class="btn-ghost mod-row-btn mod-change-version" title="Cambiar versión" aria-label="Cambiar versión de ' + escHtml(mod.name) + '" data-name="' + escHtml(mod.name) + '">' + icon('refresh-cw') + '</button>'
      + '<button type="button" class="btn-ghost mod-row-btn mod-toggle" title="' + toggleTitle + '" aria-label="' + toggleTitle + ' ' + escHtml(mod.name) + '" data-filename="' + escHtml(mod.filename) + '">' + icon(mod.enabled ? 'pause' : 'play') + '</button>'
      + '<button type="button" class="btn-ghost mod-row-btn mod-row-btn-danger mod-delete" title="Borrar mod" aria-label="Borrar ' + escHtml(mod.name) + '" data-filename="' + escHtml(mod.filename) + '">' + icon('trash-2') + '</button>'
      + '</div>';
  });
  html += '</div>';
  list.innerHTML = html;
}

document.getElementById('mods-list').addEventListener('click', function(event) {
  var deleteBtn = event.target.closest('.mod-delete');
  if (deleteBtn) {
    deleteMod(deleteBtn.dataset.filename);
    return;
  }
  var toggleBtn = event.target.closest('.mod-toggle');
  if (toggleBtn) {
    toggleMod(toggleBtn.dataset.filename);
    return;
  }
  var changeVersionBtn = event.target.closest('.mod-change-version');
  if (changeVersionBtn) {
    openModSearchModal(changeVersionBtn.dataset.name);
  }
});

function toggleMod(filename) {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/' + encodeURIComponent(filename) + '/toggle', {
    method: 'POST'
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok && result.data.success) {
        showToast(result.data.enabled ? 'Mod habilitado' : 'Mod deshabilitado', 'success');
        loadModsList();
        if (result.data.enabled) {
          checkModDependencies(false);
        }
      } else {
        showToast(result.data.detail || 'Error al cambiar el estado del mod', 'error');
      }
    })
    .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
}


// -- Borrar mods deshabilitados en lote (con confirmación individual) ---------
document.getElementById('mod-delete-disabled-btn').addEventListener('click', openDeleteDisabledModal);

function openDeleteDisabledModal() {
  var disabled = allMods.filter(function(mod) { return !mod.enabled; });
  var body = document.getElementById('mod-delete-disabled-modal-body');

  if (!disabled.length) {
    body.innerHTML = emptyArt('chest', 'No hay mods deshabilitados', 'Los mods que deshabilites se guardan aquí para volver a activarlos cuando quieras.');
  } else {
    body.innerHTML = disabled.map(function(mod) {
      return '<label class="mod-list-item cursor-pointer">'
        + '<input type="checkbox" class="mod-delete-disabled-check check-md shrink-0" data-filename="' + escHtml(mod.filename) + '" checked>'
        + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.name) + '</div>'
        + '<div class="mod-file">' + escHtml(mod.filename) + '</div></div>'
        + '</label>';
    }).join('');
  }

  document.getElementById('mod-delete-disabled-confirm').disabled = !disabled.length;
  updateDeleteDisabledCount();
  document.getElementById('mod-delete-disabled-modal').classList.add('show');
}

function updateDeleteDisabledCount() {
  var checks = document.querySelectorAll('.mod-delete-disabled-check');
  var checked = document.querySelectorAll('.mod-delete-disabled-check:checked');
  document.getElementById('mod-delete-disabled-count').textContent = checked.length + ' / ' + checks.length + ' seleccionados';
}

document.getElementById('mod-delete-disabled-modal-body').addEventListener('change', function(event) {
  if (event.target.classList.contains('mod-delete-disabled-check')) {
    updateDeleteDisabledCount();
  }
});

document.getElementById('mod-delete-disabled-confirm').addEventListener('click', function() {
  var checked = document.querySelectorAll('.mod-delete-disabled-check:checked');
  var filenames = Array.prototype.map.call(checked, function(el) { return el.dataset.filename; });
  if (!filenames.length) {
    showToast('No hay ningún mod seleccionado', 'error');
    return;
  }

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/delete-disabled', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filenames: filenames })
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      document.getElementById('mod-delete-disabled-modal').classList.remove('show');
      if (data.errors && data.errors.length) {
        showToast(data.deleted.length + ' borrado(s), ' + data.errors.length + ' con error', 'error');
      } else {
        showToast(data.deleted.length + ' mod(s) borrado(s)', 'success');
        if (data.deleted.length) {
          unlockAchievement('tidy');
        }
      }
      loadModsList();
    })
    .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
});

document.getElementById('mod-delete-disabled-cancel').addEventListener('click', function() {
  document.getElementById('mod-delete-disabled-modal').classList.remove('show');
});
document.getElementById('mod-delete-disabled-modal-close').addEventListener('click', function() {
  document.getElementById('mod-delete-disabled-modal').classList.remove('show');
});
document.getElementById('mod-delete-disabled-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});

// -- Dependencias obligatorias que faltan --------------------------------------
// Se comprueba solo (sin red, solo leyendo los jars) tras cada instalación, y
// a mano desde "Más opciones". Si falta algo se instala sin preguntar: un
// mod sin sus dependencias obligatorias impide que el servidor arranque.
var modDepsState = { rows: [], busy: false };

var MOD_DEPS_STATES = {
  pending: { icon: 'clock', label: 'En cola' },
  searching: { icon: 'search', label: 'Buscando…' },
  downloading: { icon: 'download', label: 'Descargando…' },
  installed: { icon: 'circle-check', label: 'Instalada' },
  enabled: { icon: 'refresh-cw', label: 'Reactivada' },
  unresolved: { icon: 'triangle-alert', label: 'No encontrada' }
};

document.getElementById('mod-deps-btn').addEventListener('click', function() {
  checkModDependencies(true);
});

// manual: si no falta nada, se dice igualmente (tras una instalación, en
// cambio, no se abre nada para no molestar).
function checkModDependencies(manual) {
  if (!currentModpack) {
    return;
  }
  if (manual) {
    openModDepsModal(modSearchSpinnerHtml('Comprobando las dependencias de los mods instalados...'));
  }
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/dependencies')
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (!result.ok) {
        if (manual) {
          setModDepsBody(modErrorHtml(result.data.detail || 'No se pudieron comprobar las dependencias'));
        }
        return;
      }
      var missing = result.data.missing || [];
      if (!missing.length) {
        if (manual) {
          setModDepsBody('<div class="mod-deps-empty"><div class="mod-deps-empty-icon">' + icon('circle-check') + '</div>'
            + '<div class="mod-deps-empty-title">No falta ninguna dependencia</div>'
            + '<div class="mod-deps-empty-desc">Todos los mods habilitados tienen instaladas las dependencias obligatorias que declaran.</div></div>');
        }
        return;
      }
      if (!manual) {
        openModDepsModal('');
      }
      installModDependencies(missing);
    })
    .catch(function(error) {
      if (manual) {
        setModDepsBody(modErrorHtml('No se pudo conectar con el panel: ' + error.message));
      }
    });
}

function openModDepsModal(html) {
  setModDepsBody(html);
  document.getElementById('mod-deps-modal').classList.add('show');
}

function setModDepsBody(html) {
  document.getElementById('mod-deps-modal-body').innerHTML = html;
}

function setModDepsBusy(busy) {
  modDepsState.busy = busy;
  setModOperationBusy(busy);
  document.getElementById('mod-deps-modal-close').style.display = busy ? 'none' : '';
  document.getElementById('mod-deps-modal-done').disabled = busy;
}

function closeModDepsModal() {
  if (!modDepsState.busy) {
    document.getElementById('mod-deps-modal').classList.remove('show');
  }
}

function modDepsRow(depId) {
  var row = modDepsState.rows.filter(function(r) { return r.dep_id === depId; })[0];
  if (!row) {
    row = { dep_id: depId, requested_by: [], state: 'pending' };
    modDepsState.rows.push(row);
  }
  return row;
}

function installModDependencies(missing) {
  modDepsState.rows = missing.map(function(m) {
    return { dep_id: m.dep_id, requested_by: m.requested_by || [], state: 'pending' };
  });
  setModDepsBusy(true);
  renderModDeps('Preparando...', null);

  var url = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/dependencies/install/stream';
  var source = new EventSource(url);
  source.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === 'progress') {
      if (data.dep_id) {
        var row = modDepsRow(data.dep_id);
        row.state = data.state;
        if (data.requested_by) {
          row.requested_by = data.requested_by;
        }
        if (data.filename) {
          row.filename = data.filename;
        }
      }
      renderModDeps(data.message, null);
    } else if (data.type === 'done') {
      source.close();
      (data.installed || []).forEach(function(it) {
        var row = modDepsRow(it.dep_id);
        row.state = 'installed';
        row.filename = it.filename;
      });
      (data.enabled || []).forEach(function(it) {
        var row = modDepsRow(it.dep_id);
        row.state = 'enabled';
        row.filename = it.filename;
      });
      (data.unresolved || []).forEach(function(it) {
        var row = modDepsRow(it.dep_id);
        row.state = 'unresolved';
        row.reason = it.reason;
        row.requested_by = it.requested_by || row.requested_by;
      });
      setModDepsBusy(false);
      renderModDeps(null, data);
      loadModsList();
    } else if (data.type === 'error') {
      source.close();
      setModDepsBusy(false);
      setModDepsBody(modErrorHtml(data.detail || 'Error al instalar las dependencias'));
    }
  };
  source.onerror = function() {
    source.close();
    setModDepsBusy(false);
    setModDepsBody(modErrorHtml('Se perdió la conexión mientras se instalaban las dependencias'));
    loadModsList();
  };
}

// progressText: mientras trabaja; result: el evento "done" al terminar.
function renderModDeps(progressText, result) {
  var summary;
  if (result) {
    var ok = (result.installed || []).length + (result.enabled || []).length;
    var failed = (result.unresolved || []).length;
    if (!failed) {
      summary = '<div class="mod-deps-summary ok">' + (ok === 1 ? 'Se ha instalado la dependencia que faltaba.' : 'Se han instalado las ' + ok + ' dependencias que faltaban.') + '</div>';
    } else {
      summary = '<div class="mod-deps-summary warn">'
        + (ok ? ok + ' instalada' + (ok === 1 ? '' : 's') + ', pero ' : '')
        + (failed === 1 ? 'una no se ha podido instalar sola' : failed + ' no se han podido instalar solas')
        + '. El servidor no arrancará hasta que estén.</div>';
    }
  } else {
    var n = modDepsState.rows.length;
    summary = '<div class="mod-deps-summary info">Faltan <b>' + n + '</b> dependencia' + (n === 1 ? '' : 's') + ' obligatoria' + (n === 1 ? '' : 's') + '. Instalándola' + (n === 1 ? '' : 's') + '...</div>';
  }

  var rows = modDepsState.rows.map(function(row) {
    var st = MOD_DEPS_STATES[row.state] || MOD_DEPS_STATES.pending;
    var owners = row.requested_by.map(function(r) { return r.display_name || r.mod_id; });
    var detail = owners.length ? 'Lo necesita ' + owners.join(', ') : '';
    var extra = '';
    if (row.filename && (row.state === 'installed' || row.state === 'enabled')) {
      extra = '<div class="mod-deps-file">' + escHtml(row.filename) + '</div>';
    }
    if (row.state === 'unresolved') {
      extra = '<div class="mod-deps-reason">' + escHtml(row.reason || '') + '</div>';
    }
    var action = row.state === 'unresolved'
      ? '<button type="button" class="btn-secondary btn-sm mod-deps-search" data-dep="' + escHtml(row.dep_id) + '">' + icon('search') + 'Buscar</button>'
      : '<span class="mod-deps-badge ' + row.state + '">' + st.label + '</span>';
    return '<div class="mod-deps-item ' + row.state + '">'
      + '<span class="mod-deps-icon">' + icon(st.icon) + '</span>'
      + '<div class="mod-deps-info"><div class="mod-deps-name">' + escHtml(row.dep_id) + '</div>'
      + '<div class="mod-deps-owners">' + escHtml(detail) + '</div>' + extra + '</div>'
      + action
      + '</div>';
  }).join('');

  var progress = progressText
    ? '<div class="mod-deps-progress"><div class="mod-upload-spinner"></div><span>' + escHtml(progressText) + '</span></div>'
    : '';
  setModDepsBody(summary + '<div class="mod-deps-list">' + rows + '</div>' + progress);
}

document.getElementById('mod-deps-modal-body').addEventListener('click', function(event) {
  var btn = event.target.closest('.mod-deps-search');
  if (!btn) {
    return;
  }
  // El buscador queda debajo de este modal en el DOM: se cierra este antes.
  closeModDepsModal();
  openModSearchModal(btn.dataset.dep);
});

document.getElementById('mod-deps-modal-close').addEventListener('click', closeModDepsModal);
document.getElementById('mod-deps-modal-done').addEventListener('click', closeModDepsModal);
document.getElementById('mod-deps-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closeModDepsModal();
  }
});

// -- Descargar mods como .zip -----------------------------------------------------
// Cuenta y peso de un grupo de mods, para las tarjetas y el resumen del .zip.
function modDownloadStats(mods) {
  return {
    count: mods.length,
    size: mods.reduce(function(total, mod) { return total + (mod.size || 0); }, 0)
  };
}

function modDownloadStatsHtml(stats) {
  return '<strong>' + stats.count + ' mod' + (stats.count === 1 ? '' : 's') + '</strong>' + fmtSize(stats.size);
}

function modDownloadIncludeDisabled() {
  return document.querySelector('input[name="mod-download-scope"]:checked').value === 'all';
}

document.getElementById('mod-download-btn').addEventListener('click', function() {
  var enabled = modDownloadStats(allMods.filter(function(mod) { return mod.enabled; }));
  var all = modDownloadStats(allMods);
  var disabledCount = all.count - enabled.count;

  document.getElementById('mod-download-stats-enabled').innerHTML = modDownloadStatsHtml(enabled);
  document.getElementById('mod-download-stats-all').innerHTML = modDownloadStatsHtml(all);
  document.getElementById('mod-download-desc-all').textContent = disabledCount
    ? 'Incluye ' + disabledCount + ' deshabilitado' + (disabledCount === 1 ? '' : 's')
    : 'No hay mods deshabilitados';

  // Sin deshabilitados las dos opciones serían idénticas: se bloquea "Todos".
  var allRadio = document.querySelector('input[name="mod-download-scope"][value="all"]');
  allRadio.disabled = !disabledCount;
  document.getElementById('mod-download-option-all').classList.toggle('disabled', !disabledCount);
  document.querySelector('input[name="mod-download-scope"][value="enabled"]').checked = true;

  document.getElementById('mod-download-filename').textContent = currentModpack + '-mods.zip';
  updateModDownloadSummary();
  document.getElementById('mod-download-modal').classList.add('show');
});

function updateModDownloadSummary() {
  var includeDisabled = modDownloadIncludeDisabled();
  var stats = modDownloadStats(allMods.filter(function(mod) { return mod.enabled || includeDisabled; }));
  document.getElementById('mod-download-size').textContent = stats.count ? '≈ ' + fmtSize(stats.size) : 'Vacío';
  var confirmBtn = document.getElementById('mod-download-confirm');
  confirmBtn.disabled = !stats.count;
  confirmBtn.textContent = stats.count ? 'Descargar ' + stats.count + ' mod' + (stats.count === 1 ? '' : 's') : 'Sin mods';
}

Array.prototype.forEach.call(document.querySelectorAll('input[name="mod-download-scope"]'), function(radio) {
  radio.addEventListener('change', updateModDownloadSummary);
});

document.getElementById('mod-download-confirm').addEventListener('click', function() {
  // Enlace directo con ?token= (como la descarga de kubejs): el navegador
  // gestiona la descarga en streaming sin cargar el zip entero en memoria.
  var link = document.createElement('a');
  link.href = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/download?include_disabled='
    + (modDownloadIncludeDisabled() ? '1' : '0');
  link.setAttribute('download', currentModpack + '-mods.zip');
  document.body.appendChild(link);
  link.click();
  link.remove();
  document.getElementById('mod-download-modal').classList.remove('show');
  showToast('Preparando la descarga…', 'success');
});

document.getElementById('mod-download-cancel').addEventListener('click', function() {
  document.getElementById('mod-download-modal').classList.remove('show');
});
document.getElementById('mod-download-modal-close').addEventListener('click', function() {
  document.getElementById('mod-download-modal').classList.remove('show');
});
document.getElementById('mod-download-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});

function deleteMod(filename) {
  showConfirm(
    'Borrar "' + filename + '"',
    'Esta acción no se puede deshacer.',
    function() { doDeleteMod(filename); }
  );
}

function doDeleteMod(filename) {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/' + encodeURIComponent(filename), {
    method: 'DELETE'
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        showToast('Mod borrado', 'success');
        loadModsList();
        if (document.getElementById('mod-duplicates-modal').classList.contains('show')) {
          openDuplicatesModal();
        }
      } else {
        showToast(data.detail || 'Error al borrar', 'error');
      }
    })
    .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
}

function applyModsFilters() {
  var query = document.getElementById('mods-search').value.toLowerCase().trim();
  var statusFilter = document.getElementById('mods-status-filter').value;

  var filtered = allMods.filter(function(mod) {
    if (statusFilter === 'hide-disabled' && !mod.enabled) {
      return false;
    }
    if (statusFilter === 'only-disabled' && mod.enabled) {
      return false;
    }
    if (query && mod.name.toLowerCase().indexOf(query) === -1) {
      return false;
    }
    return true;
  });
  renderModsList(filtered);
}

document.getElementById('mods-search').addEventListener('input', applyModsFilters);
document.getElementById('mods-status-filter').addEventListener('change', applyModsFilters);
