// -- Mods list ----------------------------------------------------------------
var allMods = [];
var currentModpackVersion = {};

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

function loadModsList() {
  if (!currentModpack) {
    return;
  }
  var list = document.getElementById('mods-list');
  if (!list) {
    return;
  }
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  document.getElementById('mods-count').textContent = '';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      allMods = data.mods || [];
      if (!data.exists) {
        list.innerHTML = '<p class="empty-msg">No se encontró carpeta <code>mods/</code> en este modpack.</p>';
        return;
      }
      renderModsList(allMods);
    })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg" style="color:var(--red)">Error al cargar mods</p>';
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
    list.innerHTML = '<p class="empty-msg" style="padding:16px">Sin resultados</p>';
    return;
  }
  var html = '<div class="mods-table-wrap">';
  mods.forEach(function(mod) {
    var icon = mod.enabled ? '🧩' : '⬜';
    var opacityStyle = mod.enabled ? '' : ' style="opacity:.45"';
    var disabledLabel = mod.enabled ? '' : '<span style="font-size:.72rem;color:var(--muted)">desactivado</span>';
    html += '<div class="mod-list-item"' + opacityStyle + '>'
      + '<span class="mod-icon">' + icon + '</span>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.name) + '</div></div>'
      + disabledLabel
      + '<button type="button" class="btn-danger mod-delete" title="Borrar mod" data-filename="' + escHtml(mod.filename) + '" style="opacity:1;font-size:.78rem;padding:4px 8px;flex-shrink:0">🗑</button>'
      + '</div>';
  });
  html += '</div>';
  list.innerHTML = html;
}

document.getElementById('mods-list').addEventListener('click', function(event) {
  var deleteBtn = event.target.closest('.mod-delete');
  if (deleteBtn) {
    deleteMod(deleteBtn.dataset.filename);
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
      } else {
        showToast(data.detail || 'Error al borrar', 'error');
      }
    })
    .catch(function() { showToast('Error de red', 'error'); });
}

document.getElementById('mods-search').addEventListener('input', function() {
  var query = this.value.toLowerCase().trim();
  if (!query) {
    renderModsList(allMods);
    return;
  }
  var filtered = allMods.filter(function(mod) {
    return mod.name.toLowerCase().indexOf(query) !== -1;
  });
  renderModsList(filtered);
});


// -- Mod upload ---------------------------------------------------------------
var modUploadZone = document.getElementById('mod-upload-zone');
var modFileInput = document.getElementById('mod-file-input');
var modFolderInput = document.getElementById('mod-folder-input');
var modFolderBtn = document.getElementById('mod-folder-btn');

modUploadZone.addEventListener('dragover', function(event) {
  event.preventDefault();
  this.classList.add('drag-over');
});

modUploadZone.addEventListener('dragleave', function() {
  this.classList.remove('drag-over');
});

modUploadZone.addEventListener('drop', function(event) {
  event.preventDefault();
  this.classList.remove('drag-over');
  if (event.dataTransfer.files[0]) {
    handleModFileSelected(event.dataTransfer.files[0]);
  }
});

modFileInput.addEventListener('change', function() {
  if (this.files[0]) {
    handleModFileSelected(this.files[0]);
  }
});

modFolderBtn.addEventListener('click', function() {
  modFolderInput.click();
});

modFolderInput.addEventListener('change', function() {
  if (this.files.length) {
    uploadModsBulk(this.files);
  }
  this.value = '';
});

function handleModFileSelected(file) {
  if (file.name.toLowerCase().endsWith('.zip')) {
    uploadModsBulk([file]);
  } else {
    uploadMod(file);
  }
}

function uploadMod(file) {
  if (!file.name.toLowerCase().endsWith('.jar')) {
    showAlert('Solo se aceptan archivos .jar o .zip');
    return;
  }
  var resultEl = document.getElementById('mod-upload-result');
  resultEl.style.display = 'block';
  resultEl.innerHTML = '<div style="color:var(--muted);font-size:.83rem">Subiendo y verificando ' + escHtml(file.name) + '...</div>';

  var form = new FormData();
  form.append('file', file);
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload', {
    method: 'POST',
    body: form
  })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      modFileInput.value = '';
      if (result.ok && result.data.success) {
        var info = '';
        if (result.data.mod_id) {
          info += ' · ID: ' + escHtml(result.data.mod_id);
        }
        if (result.data.mod_version) {
          info += ' · v' + escHtml(result.data.mod_version);
        }
        if (result.data.size_kb) {
          info += ' · ' + result.data.size_kb + ' KB';
        }
        var replacedMsg = '';
        if (result.data.replaced_filename) {
          replacedMsg = '<div style="color:var(--muted);font-size:.78rem;margin-top:2px">'
            + 'Se reemplazó ' + escHtml(result.data.replaced_filename)
            + ' (v' + escHtml(result.data.previous_version) + ' → v' + escHtml(result.data.mod_version) + ')</div>';
        }
        resultEl.innerHTML = '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Mod instalado: '
          + escHtml(result.data.filename) + info + '</div>' + replacedMsg;
        loadModsList();
        setTimeout(function() { resultEl.style.display = 'none'; }, 4000);
      } else {
        resultEl.innerHTML = '<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--red)">❌ '
          + escHtml(result.data.detail || 'Error desconocido') + '</div>';
      }
    })
    .catch(function(error) {
      modFileInput.value = '';
      resultEl.innerHTML = '<div style="color:var(--red);font-size:.82rem">❌ Error de red: ' + escHtml(error.message) + '</div>';
    });
}


// -- Subida masiva (.zip / carpeta) --------------------------------------------
var lastBulkData = null;
var MOD_MODAL_PAGE_SIZE = 10;

var BULK_CATEGORIES = [
  {
    key: 'added', icon: '✅', color: 'var(--green)', modalTitle: 'Mods agregados', modalType: 'list',
    many: function(n) { return n + ' mods agregados'; },
    fewPrefix: 'Se han agregado los mods: '
  },
  {
    key: 'already_installed', icon: 'ℹ️', color: 'var(--muted)', modalTitle: 'Mods ya instalados', modalType: 'list',
    many: function(n) { return n + ' mods ya estaban instalados'; },
    fewPrefix: 'Ya están instalados los mods: '
  },
  {
    key: 'needs_confirmation', icon: '⚠️', color: 'var(--yellow)', modalTitle: 'Mods con versión más antigua', modalType: 'downgrade',
    many: function(n) { return n + ' mods requieren verificación de versión anterior'; },
    fewPrefix: 'Verificación para pasar a versión anterior: ', alwaysClickable: true
  },
  {
    key: 'errors', icon: '❌', color: 'var(--red)', modalTitle: 'Mods con error', modalType: 'list',
    many: function(n) { return n + ' mods con error'; },
    fewPrefix: 'No se pudieron agregar los mods: '
  }
];

function uploadModsBulk(fileList) {
  var files = Array.prototype.slice.call(fileList).filter(function(f) {
    return f.name.toLowerCase().endsWith('.jar') || f.name.toLowerCase().endsWith('.zip');
  });
  if (!files.length) {
    showAlert('No se encontraron archivos .jar o .zip');
    return;
  }
  var resultEl = document.getElementById('mod-upload-result');
  resultEl.style.display = 'block';
  resultEl.innerHTML = '<div style="color:var(--muted);font-size:.83rem">Subiendo y verificando ' + files.length + ' archivo(s)...</div>';

  var form = new FormData();
  files.forEach(function(f) { form.append('files', f); });

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk', {
    method: 'POST',
    body: form
  })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      modFileInput.value = '';
      if (result.ok && result.data.success) {
        renderBulkResult(result.data);
        loadModsList();
      } else {
        resultEl.innerHTML = '<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--red)">❌ '
          + escHtml(result.data.detail || 'Error desconocido') + '</div>';
      }
    })
    .catch(function(error) {
      resultEl.innerHTML = '<div style="color:var(--red);font-size:.82rem">❌ Error de red: ' + escHtml(error.message) + '</div>';
    });
}

function renderBulkResult(data) {
  lastBulkData = data;
  var resultEl = document.getElementById('mod-upload-result');
  var rows = BULK_CATEGORIES.map(function(cat) {
    var items = data[cat.key] || [];
    if (!items.length) {
      return '';
    }
    var names = items.map(function(it) {
      return it.display_name + (cat.key === 'errors' && it.detail ? ' (' + it.detail + ')' : '');
    });
    if (items.length <= 2 && !cat.alwaysClickable) {
      return '<div class="bulk-result-row"><span class="bulk-result-icon">' + cat.icon + '</span>'
        + '<span style="color:' + cat.color + '">' + escHtml(cat.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    if (items.length <= 2) {
      // needs_confirmation con pocos mods: texto clicable que abre el mismo formulario
      return '<div class="bulk-result-row clickable" style="color:' + cat.color + '" data-bulk-cat="' + cat.key + '">'
        + '<span class="bulk-result-icon">' + cat.icon + '</span>'
        + '<span>' + escHtml(cat.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    return '<div class="bulk-result-row clickable" style="color:' + cat.color + '" data-bulk-cat="' + cat.key + '">'
      + '<span class="bulk-result-icon">' + cat.icon + '</span><span>' + escHtml(cat.many(items.length)) + '</span></div>';
  }).join('');

  resultEl.innerHTML = rows || '<div class="bulk-result-row" style="color:var(--muted)">No se procesó ningún mod.</div>';
}

document.getElementById('mod-upload-result').addEventListener('click', function(event) {
  var row = event.target.closest('[data-bulk-cat]');
  if (!row || !lastBulkData) {
    return;
  }
  var cat = BULK_CATEGORIES.filter(function(c) { return c.key === row.dataset.bulkCat; })[0];
  var items = lastBulkData[cat.key] || [];
  if (cat.modalType === 'downgrade') {
    openDowngradeModal(lastBulkData.batch_id, items);
  } else {
    openModListModal(cat.modalTitle, cat.icon, items);
  }
});


// -- Modal: paginación genérica -------------------------------------------------
function renderModModalPagination(containerId, page, totalItems, onChange) {
  var container = document.getElementById(containerId);
  var totalPages = Math.max(1, Math.ceil(totalItems / MOD_MODAL_PAGE_SIZE));
  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = '<button type="button" class="btn-secondary" id="' + containerId + '-prev"' + (page === 0 ? ' disabled' : '') + '>‹ Anterior</button>'
    + '<span>Página ' + (page + 1) + ' / ' + totalPages + '</span>'
    + '<button type="button" class="btn-secondary" id="' + containerId + '-next"' + (page >= totalPages - 1 ? ' disabled' : '') + '>Siguiente ›</button>';
  document.getElementById(containerId + '-prev').addEventListener('click', function() {
    if (page > 0) {
      onChange(page - 1);
    }
  });
  document.getElementById(containerId + '-next').addEventListener('click', function() {
    if (page < totalPages - 1) {
      onChange(page + 1);
    }
  });
}


// -- Modal: lista simple de mods (agregados / ya instalados / con error) ------
var modListState = { items: [], page: 0 };

function openModListModal(title, icon, items) {
  document.getElementById('mod-list-modal-title').textContent = title;
  document.getElementById('mod-list-modal-icon').textContent = icon;
  modListState = { items: items, page: 0 };
  renderModListModalPage();
  document.getElementById('mod-list-modal').classList.add('show');
}

function renderModListModalPage() {
  var body = document.getElementById('mod-list-modal-body');
  var start = modListState.page * MOD_MODAL_PAGE_SIZE;
  var pageItems = modListState.items.slice(start, start + MOD_MODAL_PAGE_SIZE);
  body.innerHTML = pageItems.map(function(item) {
    var detail = item.detail ? '<div class="mod-modal-detail">' + escHtml(item.detail) + '</div>' : '';
    return '<div class="mod-modal-item"><div class="mod-info"><div class="mod-display">' + escHtml(item.display_name) + '</div>' + detail + '</div></div>';
  }).join('');
  renderModModalPagination('mod-list-modal-pagination', modListState.page, modListState.items.length, function(p) {
    modListState.page = p;
    renderModListModalPage();
  });
}

document.getElementById('mod-list-modal-close').addEventListener('click', function() {
  document.getElementById('mod-list-modal').classList.remove('show');
});
document.getElementById('mod-list-modal-close2').addEventListener('click', function() {
  document.getElementById('mod-list-modal').classList.remove('show');
});
document.getElementById('mod-list-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});


// -- Modal: formulario para aceptar/rechazar degradar versión ------------------
var downgradeState = { items: [], page: 0, batchId: null, selected: {} };

function openDowngradeModal(batchId, items) {
  downgradeState = { items: items, page: 0, batchId: batchId, selected: {} };
  items.forEach(function(item) {
    downgradeState.selected[item.filename] = false;
  });
  renderDowngradeModalPage();
  document.getElementById('mod-downgrade-modal').classList.add('show');
}

function renderDowngradeModalPage() {
  var body = document.getElementById('mod-downgrade-modal-body');
  var start = downgradeState.page * MOD_MODAL_PAGE_SIZE;
  var pageItems = downgradeState.items.slice(start, start + MOD_MODAL_PAGE_SIZE);
  body.innerHTML = pageItems.map(function(item) {
    var checked = downgradeState.selected[item.filename] ? ' checked' : '';
    return '<label class="mod-modal-item" style="cursor:pointer">'
      + '<input type="checkbox" class="mod-downgrade-check" data-filename="' + escHtml(item.filename) + '"' + checked + '>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(item.display_name) + '</div>'
      + '<div class="mod-modal-detail">v' + escHtml(item.mod_version) + ' reemplazaría a v' + escHtml(item.existing_version)
      + ' (' + escHtml(item.existing_filename) + ')</div></div></label>';
  }).join('');
  Array.prototype.forEach.call(body.querySelectorAll('.mod-downgrade-check'), function(cb) {
    cb.addEventListener('change', function() {
      downgradeState.selected[this.dataset.filename] = this.checked;
    });
  });
  renderModModalPagination('mod-downgrade-modal-pagination', downgradeState.page, downgradeState.items.length, function(p) {
    downgradeState.page = p;
    renderDowngradeModalPage();
  });
}

function submitDowngradeDecision(acceptFilenames) {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch_id: downgradeState.batchId, accept: acceptFilenames })
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      document.getElementById('mod-downgrade-modal').classList.remove('show');
      if (data.success) {
        var n = data.applied.length;
        showToast(n ? (n + ' mod(s) degradados a versión anterior') : 'No se aplicaron cambios', 'success');
        loadModsList();
      } else {
        showToast(data.detail || 'Error al confirmar', 'error');
      }
    })
    .catch(function() { showToast('Error de red', 'error'); });
}

document.getElementById('mod-downgrade-confirm').addEventListener('click', function() {
  var accept = Object.keys(downgradeState.selected).filter(function(f) { return downgradeState.selected[f]; });
  submitDowngradeDecision(accept);
});

document.getElementById('mod-downgrade-reject-all').addEventListener('click', function() {
  submitDowngradeDecision([]);
});

document.getElementById('mod-downgrade-modal-close').addEventListener('click', function() {
  document.getElementById('mod-downgrade-modal').classList.remove('show');
});
document.getElementById('mod-downgrade-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});
