// KubeJS: crear, borrar y mover/renombrar scripts.

// -- KubeJS: nuevo archivo ----------------------------------------------------
document.getElementById('btn-new-kjs-file').addEventListener('click', function() {
  document.getElementById('kjs-new-file-form').style.display = 'block';
  document.getElementById('kjs-new-filename').focus();
});

document.getElementById('kjs-cancel-new').addEventListener('click', function() {
  document.getElementById('kjs-new-file-form').style.display = 'none';
  document.getElementById('kjs-new-filename').value = '';
  document.getElementById('kjs-subfolder').value = 'startup_scripts';
  document.getElementById('kjs-custom-folder').value = '';
  document.getElementById('kjs-custom-folder-field').style.display = 'none';
});

document.getElementById('kjs-subfolder').addEventListener('change', function() {
  document.getElementById('kjs-custom-folder-field').style.display =
    this.value === '__custom__' ? '' : 'none';
});

document.getElementById('kjs-confirm-new').addEventListener('click', function() {
  var subfolderSel = document.getElementById('kjs-subfolder').value;
  var subfolder = subfolderSel;
  if (subfolderSel === '__custom__') {
    subfolder = document.getElementById('kjs-custom-folder').value.trim().replace(/\\/g, '/');
    if (!subfolder) {
      showToast('Escribe una ruta de carpeta', 'error');
      return;
    }
  }
  var filename = document.getElementById('kjs-new-filename').value.trim();
  if (!filename) {
    showToast('Escribe un nombre de archivo', 'error');
    return;
  }
  if (!filename.includes('.')) {
    filename += '.js';
  }
  var form = new FormData();
  form.append('subfolder', subfolder);
  form.append('filename', filename);
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs-new', {
    method: 'POST',
    body: form
  })
    .then(function(r) {
      if (!r.ok) {
        return r.json().then(function(err) { throw new Error(err.detail || 'Error al crear'); });
      }
      return r.json();
    })
    .then(function(data) {
      document.getElementById('kjs-new-file-form').style.display = 'none';
      document.getElementById('kjs-new-filename').value = '';
      showToast('Archivo creado', 'success');
      apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs')
        .then(function(r) { return r.json(); })
        .then(function(kdata) {
          if (kdata.exists) {
            kubejsFiles = kdata.groups;
            filteredKjsKeys = sortedKeys(kubejsFiles, activeKjsFilter);
            renderTree('kjs');
            openFile(data.path, 'kjs');
          }
        });
    })
    .catch(function(err) {
      showToast(err.message, 'error');
    });
});


// -- KubeJS: borrar archivo ----------------------------------------------------
document.getElementById('modal-kjs-delete-btn').addEventListener('click', function() {
  if (!selectedConfigPath || selectedConfigPath.indexOf('kjs:') !== 0) {
    return;
  }
  var path = selectedConfigPath.slice(4);
  var filename = path.split('/').pop();
  showConfirm('Borrar "' + filename + '"', 'Esta acción no se puede deshacer.', function() {
    apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs-file?path=' + encodeURIComponent(path), {
      method: 'DELETE'
    })
      .then(function(response) {
        return response.json().then(function(data) { return { ok: response.ok, data: data }; });
      })
      .then(function(result) {
        if (result.ok && result.data.success) {
          showToast('Archivo borrado', 'success');
          closeModal(true);
          loadKubejs();
        } else {
          showToast(result.data.detail || 'Error al borrar', 'error');
        }
      })
      .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
  });
});


// -- KubeJS: mover / renombrar archivo -----------------------------------------
var KJS_KNOWN_FOLDERS = ['startup_scripts', 'server_scripts', 'client_scripts', '__root__'];

document.getElementById('modal-kjs-move-btn').addEventListener('click', function() {
  if (!selectedConfigPath || selectedConfigPath.indexOf('kjs:') !== 0) {
    return;
  }
  var path = selectedConfigPath.slice(4);
  var parts = path.split('/');
  var filename = parts.pop();
  var folder = parts.length ? parts.join('/') : '__root__';

  var subfolderSelect = document.getElementById('kjs-move-subfolder');
  var customField = document.getElementById('kjs-move-custom-folder-field');
  if (KJS_KNOWN_FOLDERS.indexOf(folder) !== -1) {
    subfolderSelect.value = folder;
    customField.style.display = 'none';
  } else {
    subfolderSelect.value = '__custom__';
    document.getElementById('kjs-move-custom-folder').value = folder;
    customField.style.display = '';
  }
  document.getElementById('kjs-move-filename').value = filename;
  document.getElementById('kjs-move-form').style.display = 'block';
});

document.getElementById('kjs-move-subfolder').addEventListener('change', function() {
  document.getElementById('kjs-move-custom-folder-field').style.display =
    this.value === '__custom__' ? '' : 'none';
});

document.getElementById('kjs-move-cancel').addEventListener('click', function() {
  document.getElementById('kjs-move-form').style.display = 'none';
});

document.getElementById('kjs-move-confirm').addEventListener('click', function() {
  if (!selectedConfigPath || selectedConfigPath.indexOf('kjs:') !== 0) {
    return;
  }
  var fromPath = selectedConfigPath.slice(4);

  var subfolderSel = document.getElementById('kjs-move-subfolder').value;
  var subfolder = subfolderSel;
  if (subfolderSel === '__custom__') {
    subfolder = document.getElementById('kjs-move-custom-folder').value.trim().replace(/\\/g, '/');
    if (!subfolder) {
      showToast('Escribe una ruta de carpeta', 'error');
      return;
    }
  }
  var filename = document.getElementById('kjs-move-filename').value.trim();
  if (!filename) {
    showToast('Escribe un nombre de archivo', 'error');
    return;
  }
  var toPath = subfolder === '__root__' ? filename : subfolder.replace(/^\/+|\/+$/g, '') + '/' + filename;

  var form = new FormData();
  form.append('from_path', fromPath);
  form.append('to_path', toPath);
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs-move', {
    method: 'POST',
    body: form
  })
    .then(function(r) {
      if (!r.ok) {
        return r.json().then(function(err) { throw new Error(err.detail || 'Error al mover'); });
      }
      return r.json();
    })
    .then(function() {
      showToast('Archivo movido', 'success');
      document.getElementById('kjs-move-form').style.display = 'none';
      closeModal();
      loadKubejs();
    })
    .catch(function(err) {
      showToast(err.message, 'error');
    });
});
