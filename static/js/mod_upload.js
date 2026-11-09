// Subida de mods sueltos, en lote (.zip / carpeta) y los modales que usa.
// Comparte globales con mods.js (se carga justo después).

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
  document.getElementById('mod-upload-modal-icon').innerHTML = emojiIcon(icon || '📦');
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
    + '<div><div id="mod-upload-progress-text" class="fw-semibold">' + escHtml(text) + '</div>'
    + '<div class="mod-upload-keep-open">No cierres ni recargues esta pestaña hasta que termine.</div></div>'
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
  if (!checkUploadSize(file)) {
    return;
  }
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
          replacedMsg = '<div class="text-muted text-xs mt-xs">'
            + 'Se reemplazó ' + escHtml(result.data.replaced_filename)
            + ' (v' + escHtml(result.data.previous_version) + ' → v' + escHtml(result.data.mod_version) + ')</div>';
        }
        setModUploadModalBody(noticeHtml('ok', 'Mod instalado: ' + escHtml(result.data.filename) + info) + replacedMsg);
        loadModsList();
        checkModDependencies(false);
      } else {
        setModUploadModalBody(modErrorHtml(result.data.detail || 'No se pudo instalar el mod'));
      }
    })
    .catch(function(error) {
      setModOperationBusy(false);
      modFileInput.value = '';
      setModUploadModalBody(modErrorHtml('No se pudo conectar con el panel: ' + error.message));
    });
}


// -- Subida masiva (.zip / carpeta) --------------------------------------------
var lastBulkData = null;
var MOD_MODAL_PAGE_SIZE = 10;

// needs_confirmation mezcla dos motivos bien distintos (item.reason):
// "downgrade" (versión más antigua que la instalada) y "client_only" (mod
// que parece ser solo de cliente) — mismo criterio que ya usaba
// openDowngradeModal() para el título del modal de detalle, reusado aquí para
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
    key: 'added', icon: 'circle-check', tone: 'green', modalTitle: 'Mods agregados', modalType: 'list',
    many: function(n) { return n + ' mods agregados'; },
    fewPrefix: 'Se han agregado los mods: '
  },
  {
    key: 'already_installed', icon: 'info', tone: 'muted', modalTitle: 'Mods ya instalados', modalType: 'list',
    many: function(n) { return n + ' mods ya estaban instalados'; },
    fewPrefix: 'Ya están instalados los mods: '
  },
  {
    key: 'needs_confirmation', icon: 'triangle-alert', tone: 'yellow', modalType: 'downgrade',
    dynamicLabels: true, alwaysClickable: true
  },
  // Estas dos solo aparecen una vez resuelto un lote de needs_confirmation
  // (ver updateBulkDataAfterDowngrade) — antes de eso no existen en los
  // datos, así que renderBulkResult() las salta igual que cualquier
  // categoría vacía.
  {
    key: 'accepted_flagged', icon: 'circle-check', tone: 'green', modalTitle: 'Mods instalados igualmente', modalType: 'list',
    dynamicLabels: true, labelFn: acceptedFlaggedLabels
  },
  {
    key: 'rejected_flagged', icon: 'ban', tone: 'muted', modalTitle: 'Mods rechazados', modalType: 'list',
    dynamicLabels: true, labelFn: rejectedFlaggedLabels
  },
  {
    key: 'errors', icon: 'circle-x', tone: 'red', modalTitle: 'Mods con error', modalType: 'list',
    many: function(n) { return n + ' mods con error'; },
    fewPrefix: 'No se pudieron agregar los mods: '
  }
];

function modErrorHtml(msg) {
  return noticeHtml('error', escHtml(msg));
}

function xhrPostFormData(url, form, onProgress) {
  return new Promise(function(resolve, reject) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', url);
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
  if (!checkUploadSize(files)) {
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
      setModUploadModalBody(modErrorHtml('No se pudo conectar con el panel: ' + error.message));
    });
}

function streamModsBulkProgress(jobId) {
  var url = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/mods/upload-bulk/stream/' + encodeURIComponent(jobId);
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
      if ((data.added || []).length) {
        checkModDependencies(false);
      }
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
      return '<div class="bulk-result-row"><span class="bulk-result-icon">' + icon(cat.icon) + '</span>'
        + '<span class="text-' + cat.tone + '">' + escHtml(labels.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    if (items.length <= 2) {
      // needs_confirmation con pocos mods: texto clicable que abre el mismo formulario
      return '<div class="bulk-result-row clickable text-' + cat.tone + '" data-bulk-cat="' + cat.key + '">'
        + '<span class="bulk-result-icon">' + icon(cat.icon) + '</span>'
        + '<span class="bulk-result-link">' + escHtml(labels.fewPrefix) + '<b>' + names.map(escHtml).join('</b>, <b>') + '</b></span></div>';
    }
    return '<div class="bulk-result-row clickable text-' + cat.tone + '" data-bulk-cat="' + cat.key + '">'
      + '<span class="bulk-result-icon">' + icon(cat.icon) + '</span><span class="bulk-result-link">' + escHtml(labels.many(items.length)) + '</span></div>';
  }).join('');

  setModUploadModalBody(rows || '<div class="bulk-result-row text-muted">No se procesó ningún mod.</div>');
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
  document.getElementById('mod-list-modal-icon').innerHTML = emojiIcon(icon);
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
    return '<label class="mod-modal-item cursor-pointer">'
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
        checkModDependencies(false);
      } else {
        document.getElementById('mod-downgrade-modal-body').innerHTML = modErrorHtml(data.detail || 'Error al confirmar');
        document.getElementById('mod-downgrade-confirm').disabled = false;
        document.getElementById('mod-downgrade-reject-all').disabled = false;
      }
    })
    .catch(function() {
      document.getElementById('mod-downgrade-modal-body').innerHTML = modErrorHtml('No se pudo conectar con el panel. Vuelve a intentarlo.');
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
    html += '<div class="bulk-result-row text-green"><span class="bulk-result-icon">' + icon('circle-check') + '</span>'
      + '<span>Instalados de todas formas: <b>' + applied.map(function(it) { return escHtml(it.display_name); }).join('</b>, <b>') + '</b></span></div>';
  }
  if (skipped.length) {
    html += '<div class="bulk-result-row text-muted"><span class="bulk-result-icon">' + icon('square') + '</span>'
      + '<span>Sin cambios (no aceptados): <b>' + skipped.map(function(it) { return escHtml(it.display_name); }).join('</b>, <b>') + '</b></span></div>';
  }
  document.getElementById('mod-downgrade-modal-body').innerHTML = html || '<div class="bulk-result-row text-muted">No se aplicó ningún cambio.</div>';
  // Viven en el <div class="modal-footer"> aparte del cuerpo, así que
  // reemplazar mod-downgrade-modal-body no los toca — sin esto quedaban
  // visibles pero deshabilitados para siempre, sin ninguna acción posible.
  document.getElementById('mod-downgrade-confirm').style.display = 'none';
  document.getElementById('mod-downgrade-reject-all').style.display = 'none';
}

// El modal "Subida de mods" (mod-upload-modal) se queda abierto DEBAJO de
// este todo el rato — nunca se cierra al abrir el de confirmación — así que
// si no se actualiza aquí, al volver a él (o si sigue visible detrás) seguía
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
