// -- Mods list ----------------------------------------------------------------
var allMods = [];
var currentModpackVersion = {};

// -- Menú "⋮" de acciones (duplicados / solo-cliente / borrar deshabilitados) --
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
// instalarlo desde CurseForge (ver services/modpack.py::get_pending_mods) —
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
      banner.innerHTML = '⏳ <strong>' + pending.length + ' mod(s) pendientes de instalar</strong> — '
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
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  document.getElementById('mods-count').textContent = '';
  // Se reengancha acá (en vez de en cada sitio que llama a loadModsList() tras
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
    var toggleTitle = mod.enabled ? 'Deshabilitar mod' : 'Habilitar mod';
    var toggleIcon = mod.enabled ? '⏸' : '▶';
    html += '<div class="mod-list-item"' + opacityStyle + '>'
      + '<span class="mod-icon">' + icon + '</span>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.name) + '</div>'
      + '<div class="mod-file">' + escHtml(mod.filename) + '</div></div>'
      + disabledLabel
      + '<button type="button" class="btn-secondary mod-toggle" title="' + toggleTitle + '" data-filename="' + escHtml(mod.filename) + '" style="font-size:.78rem;padding:4px 8px;flex-shrink:0">' + toggleIcon + '</button>'
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
    return;
  }
  var toggleBtn = event.target.closest('.mod-toggle');
  if (toggleBtn) {
    toggleMod(toggleBtn.dataset.filename);
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
      } else {
        showToast(result.data.detail || 'Error al cambiar el estado del mod', 'error');
      }
    })
    .catch(function() { showToast('Error de red', 'error'); });
}


// -- Borrar mods deshabilitados en lote (con confirmación individual) ---------
document.getElementById('mod-delete-disabled-btn').addEventListener('click', openDeleteDisabledModal);

function openDeleteDisabledModal() {
  var disabled = allMods.filter(function(mod) { return !mod.enabled; });
  var body = document.getElementById('mod-delete-disabled-modal-body');

  if (!disabled.length) {
    body.innerHTML = '<p class="empty-msg" style="padding:8px 4px">No hay mods deshabilitados.</p>';
  } else {
    body.innerHTML = disabled.map(function(mod) {
      return '<label class="mod-list-item" style="cursor:pointer">'
        + '<input type="checkbox" class="mod-delete-disabled-check" data-filename="' + escHtml(mod.filename) + '" checked style="flex-shrink:0;width:16px;height:16px">'
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
      }
      loadModsList();
    })
    .catch(function() { showToast('Error de red', 'error'); });
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
    .catch(function() { showToast('Error de red', 'error'); });
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


// -- Mod upload ---------------------------------------------------------------
var modUploadZone = document.getElementById('mod-upload-zone');
var modFileInput = document.getElementById('mod-file-input');
var modFolderInput = document.getElementById('mod-folder-input');
var modFolderBtn = document.getElementById('mod-folder-btn');

// -- Ventana flotante de subida/verificación -----------------------------------
var modUploadModal = document.getElementById('mod-upload-modal');
var modUploadModalBody = document.getElementById('mod-upload-modal-body');
var modUploadModalCloseBtn = document.getElementById('mod-upload-modal-close');

function openModUploadModal(html, title, icon) {
  document.getElementById('mod-upload-modal-title').textContent = title || 'Subida de mods';
  document.getElementById('mod-upload-modal-icon').textContent = icon || '📦';
  modUploadModalBody.innerHTML = html;
  modUploadModal.classList.add('show');
  updateModUploadModalLock();
}

function setModUploadModalBody(html) {
  modUploadModalBody.innerHTML = html;
}

// Actualiza solo el texto del progreso sin tocar el spinner: reemplazar todo
// el innerHTML en cada actualización recreaba el div del spinner cada vez,
// reiniciando su animación CSS antes de completar una vuelta (se veía
// tildado/reiniciándose todo el rato). Si el spinner ya está en el DOM, solo
// se cambia el texto; si no, recién ahí se arma el HTML completo.
function setModUploadProgressText(text) {
  var textEl = document.getElementById('mod-upload-progress-text');
  if (textEl) {
    textEl.textContent = text;
  } else {
    setModUploadModalBody(modUploadProgressHtml(text));
  }
}

// Igual que arriba pero para contenido adicional (p.ej. el log de instalación
// del modloader) que crece aparte del texto de progreso, sin tocar el spinner.
function setModUploadExtraHtml(html) {
  var extraEl = document.getElementById('mod-upload-extra');
  if (extraEl) {
    extraEl.innerHTML = html;
  } else {
    setModUploadModalBody(html);
  }
}

function closeModUploadModal() {
  if (modOperationBusy) {
    return;
  }
  modUploadModal.classList.remove('show');
}

function updateModUploadModalLock() {
  modUploadModalCloseBtn.style.display = modOperationBusy ? 'none' : '';
}

modUploadModalCloseBtn.addEventListener('click', closeModUploadModal);
modUploadModal.addEventListener('click', function(event) {
  if (event.target === this) {
    closeModUploadModal();
  }
});

// -- Aviso de "no salir" mientras se sube/verifica/instala algo en disco -------
var modOperationBusy = false;

function setModOperationBusy(busy) {
  modOperationBusy = busy;
  modFileInput.disabled = busy;
  modFolderBtn.disabled = busy;
  modUploadZone.classList.toggle('busy', busy);
  updateModUploadModalLock();
}

window.addEventListener('beforeunload', function(event) {
  if (modOperationBusy) {
    event.preventDefault();
    event.returnValue = '';
  }
});

// Usado por main.js y manage.js para bloquear la navegación mientras se
// suben/verifican/instalan mods, evitando dejar una operación a medias.
function guardModOperationNav() {
  if (modOperationBusy) {
    showToast('Espera a que termine la operación con los mods antes de salir de esta sección', 'error');
    return true;
  }
  return false;
}

function modUploadProgressHtml(text) {
  return '<div class="mod-upload-progress">'
    + '<div class="mod-upload-spinner"></div>'
    + '<div><div id="mod-upload-progress-text" style="font-weight:600">' + escHtml(text) + '</div>'
    + '<div style="font-size:.78rem;color:var(--yellow);margin-top:2px">⚠️ No cierres ni recargues esta pestaña hasta que termine.</div></div>'
    + '</div>'
    + '<div id="mod-upload-extra"></div>';
}

modUploadZone.addEventListener('dragover', function(event) {
  event.preventDefault();
  if (!modOperationBusy) {
    this.classList.add('drag-over');
  }
});

modUploadZone.addEventListener('dragleave', function() {
  this.classList.remove('drag-over');
});

modUploadZone.addEventListener('drop', function(event) {
  event.preventDefault();
  this.classList.remove('drag-over');
  if (modOperationBusy) {
    showToast('Espera a que termine la operación actual', 'error');
    return;
  }
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
  setModOperationBusy(true);
  openModUploadModal(modUploadProgressHtml('Subiendo y verificando ' + file.name + '...'));

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
      setModOperationBusy(false);
      modFileInput.value = '';
      if (result.ok && result.data.success && result.data.needs_confirmation && result.data.needs_confirmation.length) {
        // Necesita confirmación (versión más antigua o parece solo de cliente):
        // mismo flujo que la subida masiva, reusado tal cual.
        renderBulkResult(result.data);
      } else if (result.ok && result.data.success) {
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
        setModUploadModalBody('<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Mod instalado: '
          + escHtml(result.data.filename) + info + '</div>' + replacedMsg);
        loadModsList();
      } else {
        setModUploadModalBody('<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--red)">❌ '
          + escHtml(result.data.detail || 'Error desconocido') + '</div>');
      }
    })
    .catch(function(error) {
      setModOperationBusy(false);
      modFileInput.value = '';
      setModUploadModalBody('<div style="color:var(--red);font-size:.82rem">❌ Error de red: ' + escHtml(error.message) + '</div>');
    });
}


// -- Subida masiva (.zip / carpeta) --------------------------------------------
var lastBulkData = null;
var MOD_MODAL_PAGE_SIZE = 10;

// needs_confirmation mezcla dos motivos bien distintos (item.reason):
// "downgrade" (versión más antigua que la instalada) y "client_only" (mod
// que parece ser solo de cliente) — mismo criterio que ya usaba
// openDowngradeModal() para el título del modal de detalle, reusado acá para
// que el resumen de arriba (antes de entrar al detalle) también diga lo
// correcto en vez de asumir siempre "versión anterior".
var NEEDS_CONFIRMATION_LABELS = {
  downgrade: {
    title: 'Mods con versión más antigua que la instalada',
    many: function(n) { return n + ' mods requieren verificación de versión anterior'; },
    fewPrefix: 'Verificación para pasar a versión anterior: ',
  },
  client_only: {
    title: 'Mods que parecen ser solo de cliente',
    many: function(n) { return n + ' mods parecen ser solo de cliente'; },
    fewPrefix: 'Parecen ser solo de cliente: ',
  },
};
var NEEDS_CONFIRMATION_MIXED = {
  title: 'Mods que necesitan confirmación',
  many: function(n) { return n + ' mods necesitan confirmación (versión anterior o solo cliente)'; },
  fewPrefix: 'Necesitan confirmación: ',
};

function needsConfirmationLabels(items) {
  var reasons = items.reduce(function(set, it) { set[it.reason || 'downgrade'] = true; return set; }, {});
  var reasonKeys = Object.keys(reasons);
  return (reasonKeys.length === 1 && NEEDS_CONFIRMATION_LABELS[reasonKeys[0]]) || NEEDS_CONFIRMATION_MIXED;
}

// Mismo criterio de reason que needsConfirmationLabels(), pero como
// fragmento de frase en vez de etiqueta completa — para "N mods aceptados
// aunque {fragmento}" / lo que haga falta.
var FLAGGED_REASON_PHRASE = {
  downgrade: 'con versión más antigua que la instalada',
  client_only: 'categorizados como solo de cliente',
};
var FLAGGED_REASON_PHRASE_MIXED = 'marcados para revisión (versión anterior o solo cliente)';

function flaggedReasonPhrase(items) {
  var reasons = items.reduce(function(set, it) { set[it.reason || 'downgrade'] = true; return set; }, {});
  var reasonKeys = Object.keys(reasons);
  return (reasonKeys.length === 1 && FLAGGED_REASON_PHRASE[reasonKeys[0]]) || FLAGGED_REASON_PHRASE_MIXED;
}

function acceptedFlaggedLabels(items) {
  var phrase = flaggedReasonPhrase(items);
  return {
    many: function(n) { return n + ' mods han sido aceptados por el usuario aunque fuesen ' + phrase; },
    fewPrefix: 'Aceptados igualmente por el usuario: ',
  };
}

function rejectedFlaggedLabels(items) {
  return {
    many: function(n) { return n + ' mods han sido rechazados por el usuario'; },
    fewPrefix: 'Rechazados por el usuario: ',
  };
}

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
    key: 'needs_confirmation', icon: '⚠️', color: 'var(--yellow)', modalType: 'downgrade',
    dynamicLabels: true, alwaysClickable: true
  },
  // Estas dos solo aparecen una vez resuelto un lote de needs_confirmation
  // (ver updateBulkDataAfterDowngrade) — antes de eso no existen en los
  // datos, así que renderBulkResult() las salta igual que cualquier
  // categoría vacía.
  {
    key: 'accepted_flagged', icon: '✅', color: 'var(--green)', modalTitle: 'Mods instalados igualmente', modalType: 'list',
    dynamicLabels: true, labelFn: acceptedFlaggedLabels
  },
  {
    key: 'rejected_flagged', icon: '🚫', color: 'var(--muted)', modalTitle: 'Mods rechazados', modalType: 'list',
    dynamicLabels: true, labelFn: rejectedFlaggedLabels
  },
  {
    key: 'errors', icon: '❌', color: 'var(--red)', modalTitle: 'Mods con error', modalType: 'list',
    many: function(n) { return n + ' mods con error'; },
    fewPrefix: 'No se pudieron agregar los mods: '
  }
];

function modErrorHtml(msg) {
  return '<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--red)">❌ '
    + escHtml(msg) + '</div>';
}

function xhrPostFormData(url, form, onProgress) {
  return new Promise(function(resolve, reject) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    var headers = authHeaders();
    Object.keys(headers).forEach(function(k) { xhr.setRequestHeader(k, headers[k]); });
    if (onProgress) {
      xhr.upload.onprogress = function(event) { onProgress(event.loaded); };
    }
    xhr.onload = function() {
      var data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch (e) {
        data = {};
      }
      resolve({ ok: xhr.status >= 200 && xhr.status < 300, data: data });
    };
    xhr.onerror = function() {
      reject(new Error('Error de red'));
    };
    xhr.send(form);
  });
}

function uploadModsBulk(fileList) {
  var files = Array.prototype.slice.call(fileList).filter(function(f) {
    return f.name.toLowerCase().endsWith('.jar') || f.name.toLowerCase().endsWith('.zip');
  });
  if (!files.length) {
    showAlert('No se encontraron archivos .jar o .zip');
    return;
  }
  setModOperationBusy(true);
  openModUploadModal(modUploadProgressHtml('Subiendo ' + files.length + ' archivo(s)...'));

  var form = new FormData();
  files.forEach(function(f) { form.append('files', f); });

  var isZip = files.length === 1 && files[0].name.toLowerCase().endsWith('.zip');
  var cumulative = [];
  var totalBytes = 0;
  files.forEach(function(f) {
    totalBytes += f.size;
    cumulative.push(totalBytes);
  });
  totalBytes = totalBytes || 1;

  xhrPostFormData(
    '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk',
    form,
    function(loaded) {
      if (isZip) {
        var pct = Math.min(100, Math.round((loaded / totalBytes) * 100));
        setModUploadProgressText('Subiendo ' + files[0].name + '... ' + pct + '%');
        return;
      }
      var idx = cumulative.findIndex(function(threshold) { return loaded <= threshold; });
      if (idx === -1) {
        idx = files.length - 1;
      }
      setModUploadProgressText('Enviando mod ' + (idx + 1) + ' de ' + files.length + ': ' + files[idx].name + '...');
    }
  )
    .then(function(result) {
      modFileInput.value = '';
      if (result.ok && result.data.success) {
        streamModsBulkProgress(result.data.job_id);
      } else {
        setModOperationBusy(false);
        setModUploadModalBody(modErrorHtml(result.data.detail || 'Error desconocido'));
      }
    })
    .catch(function(error) {
      setModOperationBusy(false);
      setModUploadModalBody(modErrorHtml('Error de red: ' + error.message));
    });
}

function streamModsBulkProgress(jobId) {
  var url = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk/stream/' + encodeURIComponent(jobId)
    + '?token=' + encodeURIComponent(authToken);
  var source = new EventSource(url);

  source.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === 'progress') {
      setModUploadProgressText('Verificando mod ' + data.current + ' de ' + data.total + ': ' + (data.display_name || data.filename) + '...');
    } else if (data.type === 'done') {
      source.close();
      setModOperationBusy(false);
      renderBulkResult(data);
      loadModsList();
    } else if (data.type === 'error') {
      source.close();
      setModOperationBusy(false);
      setModUploadModalBody(modErrorHtml(data.detail || 'Error desconocido'));
    }
  };

  source.onerror = function() {
    source.close();
    setModOperationBusy(false);
    setModUploadModalBody(modErrorHtml('Se perdió la conexión mientras se verificaban los mods'));
  };
}

function renderBulkResult(data) {
  lastBulkData = data;
  var rows = BULK_CATEGORIES.map(function(cat) {
    var items = data[cat.key] || [];
    if (!items.length) {
      return '';
    }
    var names = items.map(function(it) {
      return it.display_name + (cat.key === 'errors' && it.detail ? ' (' + it.detail + ')' : '');
    });
    // needs_confirmation / accepted_flagged / rejected_flagged no tienen
    // texto fijo: el motivo real (versión anterior vs. solo-cliente) solo se
    // sabe mirando los items de este lote en concreto.
    var labels = cat.dynamicLabels ? (cat.labelFn || needsConfirmationLabels)(items) : cat;
    if (items.length <= 2 && !cat.alwaysClickable) {
      return '<div class="bulk-result-row"><span class="bulk-result-icon">' + cat.icon + '</span>'
        + '<span style="color:' + cat.color + '">' + escHtml(labels.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    if (items.length <= 2) {
      // needs_confirmation con pocos mods: texto clicable que abre el mismo formulario
      return '<div class="bulk-result-row clickable" style="color:' + cat.color + '" data-bulk-cat="' + cat.key + '">'
        + '<span class="bulk-result-icon">' + cat.icon + '</span>'
        + '<span class="bulk-result-link">' + escHtml(labels.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    return '<div class="bulk-result-row clickable" style="color:' + cat.color + '" data-bulk-cat="' + cat.key + '">'
      + '<span class="bulk-result-icon">' + cat.icon + '</span><span class="bulk-result-link">' + escHtml(labels.many(items.length)) + '</span></div>';
  }).join('');

  setModUploadModalBody(rows || '<div class="bulk-result-row" style="color:var(--muted)">No se procesó ningún mod.</div>');
}

modUploadModalBody.addEventListener('click', function(event) {
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
// totalPages lo calcula quien llama: sobre un array ya cargado en memoria
// (Math.ceil(items.length / MOD_MODAL_PAGE_SIZE)) o sobre un total que vive
// en el servidor (Math.ceil(total / limit), como la búsqueda de mods online).
function renderModModalPagination(containerId, page, totalPages, onChange) {
  var container = document.getElementById(containerId);
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
  renderModModalPagination('mod-list-modal-pagination', modListState.page, Math.max(1, Math.ceil(modListState.items.length / MOD_MODAL_PAGE_SIZE)), function(p) {
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
  // Título genérico si el lote mezcla motivos (versión antigua + solo-cliente...),
  // específico si todos los items del lote comparten el mismo motivo.
  var reasons = items.reduce(function(set, it) { set[it.reason || 'downgrade'] = true; return set; }, {});
  var reasonKeys = Object.keys(reasons);
  var titleByReason = {
    downgrade: 'Mods con versión más antigua que la instalada',
    client_only: 'Mods que parecen ser solo de cliente',
  };
  document.getElementById('mod-downgrade-modal-title').textContent =
    (reasonKeys.length === 1 && titleByReason[reasonKeys[0]]) || 'Mods que necesitan confirmación';
  // Por si el modal se reabre con un lote nuevo justo después de haber
  // resuelto uno anterior (que los deja ocultos, ver renderDowngradeResult).
  document.getElementById('mod-downgrade-confirm').style.display = '';
  document.getElementById('mod-downgrade-reject-all').style.display = '';
  document.getElementById('mod-downgrade-confirm').disabled = false;
  document.getElementById('mod-downgrade-reject-all').disabled = false;
  renderDowngradeModalPage();
  document.getElementById('mod-downgrade-modal').classList.add('show');
}

function renderDowngradeModalPage() {
  var body = document.getElementById('mod-downgrade-modal-body');
  var start = downgradeState.page * MOD_MODAL_PAGE_SIZE;
  var pageItems = downgradeState.items.slice(start, start + MOD_MODAL_PAGE_SIZE);
  body.innerHTML = pageItems.map(function(item) {
    var checked = downgradeState.selected[item.filename] ? ' checked' : '';
    var detail = item.reason === 'client_only'
      ? escHtml(item.detail || 'Este mod parece ser solo de cliente.')
      : 'v' + escHtml(item.mod_version) + ' reemplazaría a v' + escHtml(item.existing_version) + ' (' + escHtml(item.existing_filename) + ')';
    return '<label class="mod-modal-item" style="cursor:pointer">'
      + '<input type="checkbox" class="mod-downgrade-check" data-filename="' + escHtml(item.filename) + '"' + checked + '>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(item.display_name) + '</div>'
      + '<div class="mod-modal-detail">' + detail + '</div></div></label>';
  }).join('');
  Array.prototype.forEach.call(body.querySelectorAll('.mod-downgrade-check'), function(cb) {
    cb.addEventListener('change', function() {
      downgradeState.selected[this.dataset.filename] = this.checked;
    });
  });
  renderModModalPagination('mod-downgrade-modal-pagination', downgradeState.page, Math.max(1, Math.ceil(downgradeState.items.length / MOD_MODAL_PAGE_SIZE)), function(p) {
    downgradeState.page = p;
    renderDowngradeModalPage();
  });
}

function submitDowngradeDecision(acceptFilenames) {
  setModOperationBusy(true);
  document.getElementById('mod-downgrade-confirm').disabled = true;
  document.getElementById('mod-downgrade-reject-all').disabled = true;
  document.getElementById('mod-downgrade-modal-pagination').innerHTML = '';
  document.getElementById('mod-downgrade-modal-body').innerHTML = modUploadProgressHtml('Aplicando cambios...');

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch_id: downgradeState.batchId, accept: acceptFilenames })
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        renderDowngradeResult(data);
        updateBulkDataAfterDowngrade(data);
        loadModsList();
      } else {
        document.getElementById('mod-downgrade-modal-body').innerHTML = modErrorHtml(data.detail || 'Error al confirmar');
        document.getElementById('mod-downgrade-confirm').disabled = false;
        document.getElementById('mod-downgrade-reject-all').disabled = false;
      }
    })
    .catch(function() {
      document.getElementById('mod-downgrade-modal-body').innerHTML = modErrorHtml('Error de red');
      document.getElementById('mod-downgrade-confirm').disabled = false;
      document.getElementById('mod-downgrade-reject-all').disabled = false;
    })
    .then(function() {
      setModOperationBusy(false);
    });
}

function renderDowngradeResult(data) {
  var applied = data.applied || [];
  var skipped = data.skipped || [];
  var html = '';
  if (applied.length) {
    html += '<div class="bulk-result-row" style="color:var(--green)"><span class="bulk-result-icon">✅</span>'
      + '<span>Instalados de todas formas: <b>' + applied.map(function(it) { return escHtml(it.display_name); }).join('</b>, <b>') + '</b></span></div>';
  }
  if (skipped.length) {
    html += '<div class="bulk-result-row" style="color:var(--muted)"><span class="bulk-result-icon">⏭️</span>'
      + '<span>Sin cambios (no aceptados): <b>' + skipped.map(function(it) { return escHtml(it.display_name); }).join('</b>, <b>') + '</b></span></div>';
  }
  document.getElementById('mod-downgrade-modal-body').innerHTML = html || '<div class="bulk-result-row" style="color:var(--muted)">No se aplicó ningún cambio.</div>';
  // Viven en el <div class="modal-footer"> aparte del cuerpo, así que
  // reemplazar mod-downgrade-modal-body no los toca — sin esto quedaban
  // visibles pero deshabilitados para siempre, sin ninguna acción posible.
  document.getElementById('mod-downgrade-confirm').style.display = 'none';
  document.getElementById('mod-downgrade-reject-all').style.display = 'none';
}

// El modal "📦 Subida de mods" (mod-upload-modal) se queda abierto DEBAJO de
// este todo el rato — nunca se cierra al abrir el de confirmación — así que
// si no se actualiza acá, al volver a él (o si sigue visible detrás) seguía
// mostrando "N mods necesitan confirmación" con un enlace que reabre el
// mismo lote ya resuelto (y borrado) en el servidor, dando "El lote ya no
// existe o expiró" en cualquier acción. Se reemplaza needs_confirmation por
// dos categorías nuevas reflejando lo que el usuario decidió de verdad.
function updateBulkDataAfterDowngrade(data) {
  if (!lastBulkData) {
    return;
  }
  lastBulkData.needs_confirmation = [];
  lastBulkData.accepted_flagged = (lastBulkData.accepted_flagged || []).concat(data.applied || []);
  lastBulkData.rejected_flagged = (lastBulkData.rejected_flagged || []).concat(data.skipped || []);
  renderBulkResult(lastBulkData);
}

document.getElementById('mod-downgrade-confirm').addEventListener('click', function() {
  var accept = Object.keys(downgradeState.selected).filter(function(f) { return downgradeState.selected[f]; });
  submitDowngradeDecision(accept);
});

document.getElementById('mod-downgrade-reject-all').addEventListener('click', function() {
  submitDowngradeDecision([]);
});

document.getElementById('mod-downgrade-modal-close').addEventListener('click', function() {
  if (modOperationBusy) {
    return;
  }
  document.getElementById('mod-downgrade-modal').classList.remove('show');
});
document.getElementById('mod-downgrade-modal').addEventListener('click', function(event) {
  if (event.target === this && !modOperationBusy) {
    this.classList.remove('show');
  }
});


// -- Posibles mods duplicados ---------------------------------------------------
var DUPLICATE_CONFIDENCE_LABEL = {
  high: { icon: '🔴', text: 'Mismo ID interno' },
  medium: { icon: '🟡', text: 'Nombre muy parecido' }
};

document.getElementById('mod-duplicates-btn').addEventListener('click', openDuplicatesModal);

function openDuplicatesModal() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('mod-duplicates-modal-body').innerHTML = '<p class="empty-msg">Buscando posibles duplicados...</p>';
  document.getElementById('mod-duplicates-modal').classList.add('show');

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/duplicates')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      renderDuplicatesModal(data.groups || []);
    })
    .catch(function(error) {
      document.getElementById('mod-duplicates-modal-body').innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
}

function renderDuplicatesModal(groups) {
  var body = document.getElementById('mod-duplicates-modal-body');
  if (!groups.length) {
    body.innerHTML = '<p class="empty-msg">No se encontraron posibles duplicados.</p>';
    return;
  }
  body.innerHTML = groups.map(function(group) {
    var conf = DUPLICATE_CONFIDENCE_LABEL[group.confidence] || { icon: '⚠️', text: group.confidence };
    var modsHtml = group.mods.map(function(mod) {
      return '<div class="mod-modal-item">'
        + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.display_name) + '</div>'
        + '<div class="mod-modal-detail">' + escHtml(mod.filename) + (mod.mod_version ? ' · v' + escHtml(mod.mod_version) : '') + '</div></div>'
        + '<button type="button" class="btn-danger mod-delete" title="Borrar mod" data-filename="' + escHtml(mod.filename) + '" style="opacity:1;font-size:.78rem;padding:4px 8px;flex-shrink:0">🗑</button>'
        + '</div>';
    }).join('');
    return '<div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px">'
      + '<div style="font-size:.8rem;color:var(--muted);margin-bottom:6px">' + conf.icon + ' <b>' + escHtml(conf.text) + '</b> — ' + escHtml(group.reason) + '</div>'
      + modsHtml
      + '</div>';
  }).join('');
}

document.getElementById('mod-duplicates-modal-body').addEventListener('click', function(event) {
  var deleteBtn = event.target.closest('.mod-delete');
  if (deleteBtn) {
    deleteMod(deleteBtn.dataset.filename);
  }
});

document.getElementById('mod-duplicates-modal-close').addEventListener('click', function() {
  document.getElementById('mod-duplicates-modal').classList.remove('show');
});
document.getElementById('mod-duplicates-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});


// -- Mods solo-cliente -----------------------------------------------------------
document.getElementById('mod-client-only-btn').addEventListener('click', openClientOnlyModal);

var clientOnlyModalData = null; // último resultado cargado, para togglear/borrar sin recargar todo

function openClientOnlyModal() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('mod-client-only-modal-body').innerHTML = '<p class="empty-msg">Analizando metadata de los mods...</p>';
  document.getElementById('mod-client-only-modal').classList.add('show');

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/client-only')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      clientOnlyModalData = data;
      renderClientOnlyModal(data);
    })
    .catch(function(error) {
      document.getElementById('mod-client-only-modal-body').innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
}

function renderClientOnlyGroup(items) {
  return '<div class="mods-table-wrap" style="margin-bottom:8px">' + items.map(function(mod) {
    var opacityStyle = mod.enabled ? '' : ' style="opacity:.5"';
    var confidenceText = mod.confidence === 'high' ? ' · confianza alta' : (mod.confidence === 'medium' ? ' · confianza media' : '');
    var disabledNote = mod.enabled ? '' : ' · <span style="color:var(--yellow)">desactivado</span>';
    var reasonLine = mod.reason ? '<div class="mod-modal-detail">' + escHtml(mod.reason) + confidenceText + '</div>' : '';
    var toggleTitle = mod.enabled ? 'Deshabilitar mod' : 'Habilitar mod';
    var toggleIcon = mod.enabled ? '⏸' : '▶';
    return '<div class="mod-modal-item"' + opacityStyle + '>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.display_name) + '</div>'
      + '<div class="mod-modal-detail">' + escHtml(mod.filename) + disabledNote + '</div>'
      + reasonLine
      + '</div>'
      + '<button type="button" class="btn-secondary client-only-toggle" title="' + toggleTitle + '" data-filename="' + escHtml(mod.filename) + '" style="font-size:.78rem;padding:4px 8px;flex-shrink:0">' + toggleIcon + '</button>'
      + '<button type="button" class="btn-danger client-only-delete" title="Borrar mod" data-filename="' + escHtml(mod.filename) + '" style="opacity:1;font-size:.78rem;padding:4px 8px;flex-shrink:0">🗑</button>'
      + '</div>';
  }).join('') + '</div>';
}

function renderClientOnlyModal(data) {
  var body = document.getElementById('mod-client-only-modal-body');
  var clientOnly = data.client_only || [];
  var unknown = data.unknown || [];
  var server = data.server || [];

  var html = '<div style="font-size:.85rem;font-weight:600;margin:4px 0 8px">🖥️ Solo cliente (' + clientOnly.length + ')</div>';
  html += clientOnly.length
    ? renderClientOnlyGroup(clientOnly)
    : '<p class="empty-msg" style="padding:8px 4px">No se detectó ningún mod solo-cliente.</p>';

  if (unknown.length) {
    html += '<div style="font-size:.85rem;font-weight:600;margin:16px 0 8px">❓ Categoría desconocida (' + unknown.length + ')</div>'
      + '<p class="hint" style="margin-bottom:8px">Este mod no declara de forma clara si hace falta en el servidor — revísalo a mano si no estás seguro.</p>'
      + renderClientOnlyGroup(unknown);
  }

  html += '<div style="font-size:.8rem;color:var(--muted);margin-top:16px;padding-top:10px;border-top:1px solid var(--border)">'
    + '🖧 ' + server.length + ' mod(s) detectado(s) como necesarios en el servidor (no se listan aquí).</div>';

  body.innerHTML = html;
}

// Deshabilitar/borrar directamente desde este modal, sin tener que ir a
// buscar el mismo mod en la lista general — reusa los mismos endpoints que
// esa lista, pero refresca ESTE modal después (no la lista de detrás, que
// loadModsList() ya se encarga de mantener al día por su cuenta).
document.getElementById('mod-client-only-modal-body').addEventListener('click', function(event) {
  var toggleBtn = event.target.closest('.client-only-toggle');
  if (toggleBtn) {
    clientOnlyToggleMod(toggleBtn.dataset.filename);
    return;
  }
  var deleteBtn = event.target.closest('.client-only-delete');
  if (deleteBtn) {
    clientOnlyDeleteMod(deleteBtn.dataset.filename);
  }
});

function clientOnlyToggleMod(filename) {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/' + encodeURIComponent(filename) + '/toggle', {
    method: 'POST'
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok && result.data.success) {
        showToast(result.data.enabled ? 'Mod habilitado' : 'Mod deshabilitado', 'success');
        updateModStateLocally(filename, result.data.filename, result.data.enabled);
      } else {
        showToast(result.data.detail || 'Error al cambiar el estado del mod', 'error');
      }
    })
    .catch(function() { showToast('Error de red', 'error'); });
}

function clientOnlyDeleteMod(filename) {
  showConfirm(
    'Borrar "' + filename + '"',
    'Esta acción no se puede deshacer.',
    function() {
      apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/' + encodeURIComponent(filename), {
        method: 'DELETE'
      })
        .then(function(response) { return response.json(); })
        .then(function(data) {
          if (data.success) {
            showToast('Mod borrado', 'success');
            removeModLocally(filename);
          } else {
            showToast(data.detail || 'Error al borrar', 'error');
          }
        })
        .catch(function() { showToast('Error de red', 'error'); });
    }
  );
}

// Actualiza la lista general (allMods, ya cargada) y este modal (clientOnlyModalData,
// ya cargado) en memoria, en vez de volver a pedir ambas cosas al servidor por
// un cambio de un solo mod — la respuesta del propio toggle/delete ya trae
// todo lo necesario para reflejarlo sin una ida y vuelta de más.
function updateModStateLocally(oldFilename, newFilename, enabled) {
  allMods.forEach(function(mod) {
    if (mod.filename === oldFilename) {
      mod.filename = newFilename;
      mod.enabled = enabled;
    }
  });
  applyModsFilters();

  if (clientOnlyModalData) {
    ['client_only', 'unknown', 'server'].forEach(function(key) {
      (clientOnlyModalData[key] || []).forEach(function(mod) {
        if (mod.filename === oldFilename) {
          mod.filename = newFilename;
          mod.enabled = enabled;
        }
      });
    });
    renderClientOnlyModal(clientOnlyModalData);
  }
}

function removeModLocally(filename) {
  allMods = allMods.filter(function(mod) { return mod.filename !== filename; });
  applyModsFilters();

  if (clientOnlyModalData) {
    ['client_only', 'unknown', 'server'].forEach(function(key) {
      clientOnlyModalData[key] = (clientOnlyModalData[key] || []).filter(function(mod) { return mod.filename !== filename; });
    });
    renderClientOnlyModal(clientOnlyModalData);
  }
}

document.getElementById('mod-client-only-modal-close').addEventListener('click', function() {
  document.getElementById('mod-client-only-modal').classList.remove('show');
});
document.getElementById('mod-client-only-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});


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
var modSearchLastResults = [];
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
  return '<button type="button" class="btn-secondary btn-sm mod-search-back" style="margin-bottom:10px">‹ Volver a resultados</button>';
}

document.getElementById('mod-search-btn').addEventListener('click', function() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('mod-search-input').value = '';
  Array.prototype.forEach.call(document.querySelectorAll('#mod-search-tabs .mgmt-tab'), function(t) {
    t.classList.toggle('active', t.dataset.source === 'modrinth');
  });
  modSearchSource = 'modrinth';
  modSearchCategories = [];
  loadModSearchCategories(modSearchSource);
  document.getElementById('mod-search-modal').classList.add('show');
  runModSearch('', 0);
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
  modSearchCategoryPanelToggle.textContent = collapsed ? '▼' : '▲';
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
    modSearchCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cached) || '<p class="empty-msg" style="padding:6px">Sin categorías</p>';
    return;
  }
  modSearchCategoryPanelBody.innerHTML = '<p class="empty-msg" style="padding:6px">Cargando...</p>';
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
      modSearchCategoryPanelBody.innerHTML = renderModSearchCategoryOptions(cats) || '<p class="empty-msg" style="padding:6px">Sin categorías</p>';
    })
    .catch(function() {
      modSearchCategoryPanelBody.innerHTML = '<p class="empty-msg" style="padding:6px">Error al cargar categorías</p>';
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
      body.innerHTML = modErrorHtml('Error de red: ' + error.message);
    });
}

function renderModSearchResults(results) {
  modSearchLastResults = results;
  var body = document.getElementById('mod-search-modal-body');
  if (!results.length) {
    body.innerHTML = '<p class="empty-msg">Sin resultados para esta versión/modloader.</p>';
    document.getElementById('mod-search-pagination').innerHTML = '';
    return;
  }
  body.innerHTML = results.map(function(mod, i) {
    // Sin src todavía: applyModSearchImage() lo completa abajo, desde caché
    // (blob ya descargado) o disparando la descarga una sola vez.
    var icon = mod.icon_url
      ? '<img class="mod-search-icon" data-icon-url="' + escHtml(mod.icon_url) + '" alt="" loading="lazy" decoding="async">'
      : '<span class="mod-search-icon" style="display:flex;align-items:center;justify-content:center;font-size:1.2rem">🧩</span>';
    var badge = mod.installed ? '<span class="mod-search-badge">✅ Instalado</span>' : '';
    var desc = mod.description ? '<div class="mod-search-desc">' + escHtml(mod.description) + '</div>' : '';
    var link = mod.page_url
      ? '<a class="mod-search-link" href="' + escHtml(mod.page_url) + '" target="_blank" rel="noopener" title="Ver página del mod" onclick="event.stopPropagation()">↗</a>'
      : '';
    return '<div class="mod-search-result-item" data-index="' + i + '">'
      + icon
      + '<div class="mod-search-info">'
      + '<div class="mod-search-title-row"><span class="mod-search-title">' + escHtml(mod.title) + '</span>' + badge + '</div>'
      + desc
      + '<div class="mod-search-meta">' + escHtml(mod.author || '') + ' · ⬇ ' + formatDownloads(mod.downloads) + '</div>'
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
      body.innerHTML = modSearchBackButtonHtml() + modErrorHtml('Error de red: ' + error.message);
    });
}

function renderModSearchFilesPage() {
  var body = document.getElementById('mod-search-modal-body');
  var mod = modSearchFilesState.mod;
  var files = modSearchFilesState.items;
  var badge = mod.installed ? ' <span class="mod-search-badge">✅ Instalado</span>' : '';
  var header = '<div class="mod-search-files-header">'
    + '<button type="button" class="btn-secondary btn-sm mod-search-back">‹ Volver a resultados</button>'
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
        : '<span style="font-size:.72rem;color:var(--muted)">Sin descarga directa</span>')
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
    // Vuelve a la página de resultados ya cargada, sin volver a pedirla al servidor.
    renderModSearchResults(modSearchLastResults);
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
        body.innerHTML = '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Mod instalado: '
          + escHtml(result.data.filename) + '</div>';
        document.getElementById('mod-search-pagination').innerHTML = '';
        // El flag "installed" de otras páginas ya cacheadas puede haber
        // quedado desactualizado con este mod recién instalado.
        modSearchResultsCache.clear();
        loadModsList();
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
      showToast('Error de red: ' + error.message, 'error');
    });
}
