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
    uploadMod(event.dataTransfer.files[0]);
  }
});

modFileInput.addEventListener('change', function() {
  if (this.files[0]) {
    uploadMod(this.files[0]);
  }
});

function uploadMod(file) {
  if (!file.name.toLowerCase().endsWith('.jar')) {
    showAlert('Solo se aceptan archivos .jar');
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
