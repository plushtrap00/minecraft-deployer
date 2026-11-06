// Limpieza de la carpeta de mods: duplicados y mods solo de cliente.

// -- Posibles mods duplicados ---------------------------------------------------
var DUPLICATE_CONFIDENCE_LABEL = {
  high: { cls: 'dup-high', text: 'Mismo ID interno' },
  medium: { cls: 'dup-medium', text: 'Nombre muy parecido' }
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
      document.getElementById('mod-duplicates-modal-body').innerHTML = modErrorHtml('No se pudo conectar con el panel: ' + error.message);
    });
}

function renderDuplicatesModal(groups) {
  var body = document.getElementById('mod-duplicates-modal-body');
  if (!groups.length) {
    body.innerHTML = '<p class="empty-msg">No se encontraron posibles duplicados.</p>';
    return;
  }
  body.innerHTML = groups.map(function(group) {
    var conf = DUPLICATE_CONFIDENCE_LABEL[group.confidence] || { cls: 'dup-medium', text: group.confidence };
    var modsHtml = group.mods.map(function(mod) {
      return '<div class="mod-modal-item">'
        + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.display_name) + '</div>'
        + '<div class="mod-modal-detail">' + escHtml(mod.filename) + (mod.mod_version ? ' · v' + escHtml(mod.mod_version) : '') + '</div></div>'
        + '<button type="button" class="btn-danger mod-delete" title="Borrar mod" data-filename="' + escHtml(mod.filename) + '" aria-label="Borrar mod" style="opacity:1;font-size:.78rem;padding:4px 8px;flex-shrink:0">' + icon('trash-2') + '</button>'
        + '</div>';
    }).join('');
    return '<div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px">'
      + '<div style="font-size:.8rem;color:var(--muted);margin-bottom:6px">' + '<span class="dup-dot ' + conf.cls + '"></span><b>' + escHtml(conf.text) + '</b> — ' + escHtml(group.reason) + '</div>'
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
      document.getElementById('mod-client-only-modal-body').innerHTML = modErrorHtml('No se pudo conectar con el panel: ' + error.message);
    });
}

function renderClientOnlyGroup(items) {
  return '<div class="mods-table-wrap" style="margin-bottom:8px">' + items.map(function(mod) {
    var opacityStyle = mod.enabled ? '' : ' style="opacity:.5"';
    var confidenceText = mod.confidence === 'high' ? ' · confianza alta' : (mod.confidence === 'medium' ? ' · confianza media' : '');
    var disabledNote = mod.enabled ? '' : ' · <span style="color:var(--yellow)">desactivado</span>';
    var reasonLine = mod.reason ? '<div class="mod-modal-detail">' + escHtml(mod.reason) + confidenceText + '</div>' : '';
    var toggleTitle = mod.enabled ? 'Deshabilitar mod' : 'Habilitar mod';
    var toggleIcon = mod.enabled ? icon('pause') : icon('play');
    return '<div class="mod-modal-item"' + opacityStyle + '>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(mod.display_name) + '</div>'
      + '<div class="mod-modal-detail">' + escHtml(mod.filename) + disabledNote + '</div>'
      + reasonLine
      + '</div>'
      + '<button type="button" class="btn-secondary client-only-toggle" title="' + toggleTitle + '" data-filename="' + escHtml(mod.filename) + '" style="font-size:.78rem;padding:4px 8px;flex-shrink:0">' + toggleIcon + '</button>'
      + '<button type="button" class="btn-danger client-only-delete" title="Borrar mod" data-filename="' + escHtml(mod.filename) + '" aria-label="Borrar mod" style="opacity:1;font-size:.78rem;padding:4px 8px;flex-shrink:0">' + icon('trash-2') + '</button>'
      + '</div>';
  }).join('') + '</div>';
}

function renderClientOnlyModal(data) {
  var body = document.getElementById('mod-client-only-modal-body');
  var clientOnly = data.client_only || [];
  var unknown = data.unknown || [];
  var server = data.server || [];

  var html = '<div style="font-size:.85rem;font-weight:600;margin:4px 0 8px">Solo cliente (' + clientOnly.length + ')</div>';
  html += clientOnly.length
    ? renderClientOnlyGroup(clientOnly)
    : '<p class="empty-msg" style="padding:8px 4px">No se detectó ningún mod solo-cliente.</p>';

  if (unknown.length) {
    html += '<div style="font-size:.85rem;font-weight:600;margin:16px 0 8px">Categoría desconocida (' + unknown.length + ')</div>'
      + '<p class="hint" style="margin-bottom:8px">Este mod no declara de forma clara si hace falta en el servidor — revísalo a mano si no estás seguro.</p>'
      + renderClientOnlyGroup(unknown);
  }

  html += '<div style="font-size:.8rem;color:var(--muted);margin-top:16px;padding-top:10px;border-top:1px solid var(--border)">'
    + server.length + ' mod(s) detectado(s) como necesarios en el servidor (no se listan aquí).</div>';

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
    .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
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
        .catch(function() { showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error'); });
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
