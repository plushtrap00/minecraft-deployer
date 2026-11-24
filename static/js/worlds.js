// -- Mundos -------------------------------------------------------------------
function loadWorlds() {
  var list = document.getElementById('worlds-list');
  if (!list) {
    return;
  }
  list.innerHTML = loadingHtml();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderWorlds(data); })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg text-red">' + t('Error al cargar mundos') + '</p>';
    });
}

function renderWorlds(data) {
  var list = document.getElementById('worlds-list');
  var worlds = data.worlds;
  if (!worlds || !worlds.length) {
    list.innerHTML = emptyArt('map', t('Aún no hay mundo'), t('Se genera la primera vez que arranca el servidor.'), null, true)
      + '<p class="hint mt-s">' + t('Mundo configurado:') + ' <code>' + escHtml(data.active || 'world') + '</code>'
      + ' · Tipo: <code>' + escHtml(data.level_type || 'minecraft:normal') + '</code></p>';
    return;
  }
  var html = '';
  worlds.forEach(function(world) {
    var activeBadge = world.active
      ? '<span class="world-active-badge">' + t('Activo') + '</span>'
      : '';
    var activateBtn = !world.active
      ? '<button type="button" class="btn-secondary wc-activate btn-xs" data-world="' + escHtml(world.name) + '">' + icon('check') + t('Activar') + '</button>'
      : '';
    var deleteBtn = !world.active
      ? '<button type="button" class="btn-danger wc-delete btn-xs" data-world="' + escHtml(world.name) + '">' + icon('trash-2') + t('Borrar') + '</button>'
      : '';
    var downloadUrl = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/' + encodeURIComponent(world.name) + '/download';
    var downloadBtn = '<a href="' + downloadUrl + '" download="' + escHtml(world.name) + '.zip" class="btn-secondary btn-xs no-underline wc-download">' + icon('download') + t('Descargar') + '</a>';
    var worldIcon = icon('map');
    var activeClass = world.active ? ' active-world' : '';
    html += '<div class="world-card' + activeClass + freshClass('world', world.name) + '">'
      + '<span class="world-icon">' + worldIcon + '</span>'
      + '<div class="flex-1">'
      + '<div class="fw-semibold">' + escHtml(world.name) + ' ' + activeBadge + '</div>'
      + '<div class="text-muted text-xs">' + escHtml(t('{size} MB en disco', { size: world.size_mb })) + '</div>'
      + '</div>'
      + '<div class="wc-actions">' + activateBtn + downloadBtn + deleteBtn + '</div>'
      + '</div>';
  });
  var seedHint = data.seed ? ' · Seed: <code>' + escHtml(data.seed) + '</code>' : '';
  html += '<p class="hint mt-s">' + t('Tipo actual:') + ' <code>' + escHtml(data.level_type || 'minecraft:normal') + '</code>'
    + seedHint + '</p>';
  list.innerHTML = html;
}

document.addEventListener('click', function(event) {
  var activateBtn = event.target.closest('.wc-activate');
  if (activateBtn) {
    activateWorld(activateBtn.dataset.world, activateBtn);
    return;
  }
  var deleteBtn = event.target.closest('.wc-delete');
  if (deleteBtn) {
    deleteWorld(deleteBtn.dataset.world, deleteBtn);
    return;
  }
  if (event.target.closest('.wc-download')) {
    unlockAchievement('backup');
  }
});

function activateWorld(name, button) {
  showConfirm(
    t('Activar el mundo «{name}»', { name: name }),
    t('El servidor usará este mundo en el próximo inicio.'),
    function() { doActivateWorld(name, button); }
  );
}

function doActivateWorld(name, button) {
  var form = new FormData();
  form.append('world_name', name);
  busyWhile(button, function() {
    return apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/activate', {
      method: 'POST',
      body: form
    })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (data.success) {
          showToast(t('Mundo activado'), 'success');
          loadWorlds();
          loadServerProps();
        }
      })
      .catch(function() { showToast(t('No se pudo activar el mundo'), 'error'); });
  });
}

function deleteWorld(name, button) {
  showConfirm(
    t('Borrar «{name}»', { name: name }),
    t('Se borrarán también sus dimensiones nether y end. Esta acción no se puede deshacer.'),
    function() { doDeleteWorld(name, button); }
  );
}

function doDeleteWorld(name, button) {
  busyWhile(button, function() {
    return apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/' + encodeURIComponent(name), {
      method: 'DELETE'
    })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (data.success) {
          showToast(t('Mundo borrado'), 'success');
          unlockAchievement('tnt');
          loadWorlds();
        }
      })
      .catch(function() { showToast(t('No se pudo borrar el mundo'), 'error'); });
  });
}


// -- Nuevo mundo (formulario inline) ------------------------------------------
var nwActivate = true;

var typeDescs = {
  'minecraft:normal':      t('Mundo estándar con biomas variados, estructuras y terreno natural.'),
  'minecraft:large_biomes':t('Igual que el normal pero los biomas son mucho más grandes. Ideal para exploración.'),
  'minecraft:amplified':   t('Terreno extremo: montañas gigantescas, ravines profundísimas y posibles islas flotantes.'),
  'minecraft:flat':        t('Mundo completamente plano. Perfecto para construcciones y redstone a gran escala.'),
  'biomesoplenty':         t('Añade más de 90 biomas nuevos. Requiere el mod Biomes O Plenty instalado.'),
  'terraforged':           t('Generación de terreno realista y detallada. Requiere el mod TerraForged instalado.'),
  'skyblockbuilder:skyblock': t('Mundo skyblock (islas vacías) generado por SkyblockBuilder — necesario para que el mod cree equipo/isla al unirse; "Normal" genera terreno vanilla normal aunque el mod esté instalado.'),
  'custom':                t('Introduce manualmente el identificador del tipo de mundo del mod que quieras usar.')
};

(function() {
  var btnNew = document.getElementById('btn-new-world');
  if (!btnNew) {
    return;
  }

  btnNew.addEventListener('click', function() {
    var form = document.getElementById('new-world-form');
    var uploadForm = document.getElementById('upload-world-form');
    var isOpen = form.style.display !== 'none';
    if (!isOpen && uploadForm) {
      uploadForm.style.display = 'none';
    }
    form.style.display = isOpen ? 'none' : 'block';
    if (!isOpen && currentModpack) {
      apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/detected-mods')
        .then(function(response) { return response.json(); })
        .then(function(data) {
          var bop = document.getElementById('opt-bop');
          var terraForged = document.getElementById('opt-tf');
          var skyblock = document.getElementById('opt-sky');
          if (bop) {
            bop.disabled = !data.has_biomesoplenty;
            bop.textContent = 'Biomes O Plenty' + ' — ' + (data.has_biomesoplenty ? t('detectado') : t('mod no detectado'));
          }
          if (terraForged) {
            terraForged.disabled = !data.has_terraforged;
            terraForged.textContent = 'TerraForged' + ' — ' + (data.has_terraforged ? t('detectado') : t('mod no detectado'));
          }
          if (skyblock) {
            skyblock.disabled = !data.has_skyblockbuilder;
            skyblock.textContent = 'Skyblock (SkyblockBuilder)' + ' — ' + (data.has_skyblockbuilder ? t('detectado') : t('mod no detectado'));
            // A diferencia de BOP/TerraForged (cosméticos, cualquiera de los
            // dos sirve como terreno "normal" si se elige mal), elegir el
            // tipo equivocado aquí no es solo distinto: SkyblockBuilder
            // simplemente no crea equipo/isla y el jugador aparece en
            // terreno vanilla sin ningún aviso — visto de primera mano con
            // este modpack. Si el mod está instalado, no tiene sentido que
            // "Normal" siga siendo el valor por defecto.
            if (data.has_skyblockbuilder) {
              document.getElementById('nw-type-select').value = 'skyblockbuilder:skyblock';
              updateTypeDesc();
            }
          }
        })
        .catch(function() {});
      updateTypeDesc();
    }
  });

  document.getElementById('nw-cancel-inline').addEventListener('click', function() {
    document.getElementById('new-world-form').style.display = 'none';
  });

  document.getElementById('nw-type-select').addEventListener('change', updateTypeDesc);

  document.getElementById('nw-activate-toggle').addEventListener('click', function() {
    nwActivate = !nwActivate;
    this.classList.toggle('on', nwActivate);
  });

  document.getElementById('nw-confirm').addEventListener('click', function() {
    var name = document.getElementById('nw-name').value.trim();
    if (!name) {
      flagField(document.getElementById('nw-name'), t('Escribe un nombre para el mundo'));
      return;
    }
    var sel = document.getElementById('nw-type-select');
    var worldType;
    if (sel.value === 'custom') {
      worldType = document.getElementById('nw-type-custom').value.trim();
    } else {
      worldType = sel.value;
    }
    if (!worldType) {
      flagField(document.getElementById('nw-type-custom'), t('Escribe el tipo de mundo'));
      return;
    }
    markFresh('world', name);
    var form = new FormData();
    form.append('world_name', name);
    form.append('level_type', worldType);
    form.append('seed', document.getElementById('nw-seed').value.trim());
    form.append('activate', nwActivate ? '1' : '0');
    busyWhile(document.getElementById('nw-confirm'), function() {
      return apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/create', {
        method: 'POST',
        body: form
      })
        .then(function(response) {
          return response.json().then(function(data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function(result) {
          if (result.ok && result.data.success) {
            showToast(result.data.message, 'success');
            unlockAchievement('new-world');
            document.getElementById('new-world-form').style.display = 'none';
            document.getElementById('nw-name').value = '';
            document.getElementById('nw-seed').value = '';
            loadWorlds();
            if (nwActivate) {
              loadServerProps();
            }
          } else {
            showToast(result.data.detail || t('Error'), 'error');
          }
        })
        .catch(function() { showToast(t('No se pudo preparar el mundo'), 'error'); });
    });
  });
})();

// -- Subir mundo existente (inline, sin modal) --------------------------------
var uwActivate = true;

(function() {
  var btnUpload = document.getElementById('btn-upload-world');
  if (!btnUpload) {
    return;
  }

  btnUpload.addEventListener('click', function() {
    var form = document.getElementById('upload-world-form');
    var newWorldForm = document.getElementById('new-world-form');
    var isOpen = form.style.display !== 'none';
    if (!isOpen) {
      newWorldForm.style.display = 'none';
    }
    form.style.display = isOpen ? 'none' : 'block';
  });

  document.getElementById('uw-cancel-inline').addEventListener('click', function() {
    document.getElementById('upload-world-form').style.display = 'none';
  });

  document.getElementById('uw-activate-toggle').addEventListener('click', function() {
    uwActivate = !uwActivate;
    this.classList.toggle('on', uwActivate);
  });

  document.getElementById('uw-file').addEventListener('change', function() {
    if (!this.files.length) {
      return;
    }
    var nameField = document.getElementById('uw-name');
    if (!nameField.value.trim()) {
      var base = this.files[0].name.replace(/\.(zip|tar\.gz|tgz|tar\.bz2|tar|rar)$/i, '');
      nameField.value = base.replace(/[^a-zA-Z0-9_\-]/g, '_');
    }
  });

  document.getElementById('uw-confirm').addEventListener('click', function() {
    var fileInput = document.getElementById('uw-file');
    var file = fileInput.files[0];
    if (!file) {
      showAlert(t('Selecciona un archivo de mundo (.zip, .tar.gz…)'));
      return;
    }
    if (!checkUploadSize(file)) {
      return;
    }
    var worldName = document.getElementById('uw-name').value.trim();
    if (!worldName) {
      flagField(document.getElementById('uw-name'), t('Escribe un nombre para el mundo'));
      return;
    }
    markFresh('world', worldName);

    var confirmBtn = document.getElementById('uw-confirm');
    var progress = document.getElementById('uw-progress');
    confirmBtn.disabled = true;
    progress.style.display = 'block';
    progress.style.color = 'var(--muted)';
    progress.textContent = t('Subiendo {file}…', { file: file.name }) + ' 0%';

    var form = new FormData();
    form.append('file', file);
    form.append('world_name', worldName);
    form.append('activate', uwActivate ? '1' : '0');

    xhrPostFormData(
      '/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/upload',
      form,
      function(loaded) {
        var pct = Math.min(100, Math.round((loaded / file.size) * 100));
        progress.textContent = t('Subiendo {file}…', { file: file.name }) + ' ' + pct + '%';
      }
    )
      .then(function(result) {
        confirmBtn.disabled = false;
        if (result.ok && result.data.success) {
          progress.textContent = '';
          progress.style.display = 'none';
          showToast(t('Mundo subido ({size} MB)', { size: result.data.size_mb }), 'success');
          unlockAchievement('new-world');
          document.getElementById('upload-world-form').style.display = 'none';
          fileInput.value = '';
          document.getElementById('uw-name').value = '';
          loadWorlds();
          if (uwActivate) {
            loadServerProps();
          }
        } else {
          progress.style.color = 'var(--red)';
          progress.textContent = result.data.detail || t('Error al subir el mundo');
        }
      })
      .catch(function() {
        confirmBtn.disabled = false;
        progress.style.color = 'var(--red)';
        progress.textContent = t('Error de red al subir el mundo');
      });
  });
})();


function updateTypeDesc() {
  var sel = document.getElementById('nw-type-select');
  if (!sel) {
    return;
  }
  document.getElementById('nw-type-desc').textContent = typeDescs[sel.value] || '';
  if (sel.value === 'custom') {
    document.getElementById('nw-type-custom').style.display = 'block';
  } else {
    document.getElementById('nw-type-custom').style.display = 'none';
  }
}


// -- Archivos de mundo ---------------------------------------------------------
var worldFiles = {};
var filteredWfKeys = [];
var activeWfFilter = '';
var selectedWfWorld = null;

function loadWorldFilesTab() {
  var select = document.getElementById('wf-world-select');
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var worlds = data.worlds || [];
      var prev = select.value;
      select.innerHTML = '<option value="">' + t('Selecciona un mundo…') + '</option>' + worlds.map(function(w) {
        return '<option value="' + escHtml(w.name) + '">' + escHtml(w.name) + (w.active ? ' (' + t('activo') + ')' : '') + '</option>';
      }).join('');
      var keepPrev = worlds.some(function(w) { return w.name === prev; });
      if (keepPrev) {
        select.value = prev;
      } else if (worlds.length) {
        select.value = data.active_world || worlds[0].name;
      }
      if (select.value) {
        loadWorldFiles(select.value);
      } else {
        document.getElementById('wf-tree').innerHTML = '<p class="empty-msg pad-m">' + t('No hay mundos detectados') + '</p>';
        document.getElementById('wf-tree-count').style.display = 'none';
      }
    })
    .catch(function() {
      document.getElementById('wf-tree').innerHTML = '<p class="empty-msg pad-m text-red">' + t('Error al cargar mundos') + '</p>';
    });
}

document.getElementById('wf-world-select').addEventListener('change', function() {
  if (this.value) {
    loadWorldFiles(this.value);
  }
});

function loadWorldFiles(worldName) {
  selectedWfWorld = worldName;
  document.getElementById('wf-tree').innerHTML = loadingHtml();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/world-files?world_name=' + encodeURIComponent(worldName))
    .then(function(response) { return response.json(); })
    .then(function(data) {
      worldFiles = data.groups;
      filteredWfKeys = wfSortedKeys(activeWfFilter);
      renderWfTree();
    })
    .catch(function() {
      document.getElementById('wf-tree').innerHTML = '<p class="empty-msg pad-m text-red">' + t('Error al cargar archivos') + '</p>';
    });
}

document.getElementById('wf-search').addEventListener('input', function() {
  activeWfFilter = this.value;
  filteredWfKeys = wfSortedKeys(activeWfFilter);
  renderWfTree();
});

function wfSortedKeys(filter) {
  var keys = Object.keys(worldFiles).sort(function(a, b) {
    if (a === '__root__') {
      return -1;
    }
    if (b === '__root__') {
      return 1;
    }
    return a.localeCompare(b);
  });
  if (filter) {
    var filterLower = filter.toLowerCase();
    keys = keys.filter(function(key) {
      if (key === '__root__') {
        return worldFiles[key].some(function(f) { return f.toLowerCase().indexOf(filterLower) !== -1; });
      }
      return key.toLowerCase().indexOf(filterLower) !== -1
        || worldFiles[key].some(function(f) { return f.toLowerCase().indexOf(filterLower) !== -1; });
    });
  }
  return keys;
}

function wfGetFilteredFiles(files, groupKey, filter) {
  if (!filter) {
    return files;
  }
  var filterLower = filter.toLowerCase();
  if (groupKey !== '__root__' && groupKey.toLowerCase().indexOf(filterLower) !== -1) {
    return files;
  }
  return files.filter(function(f) { return f.toLowerCase().indexOf(filterLower) !== -1; });
}

// Mismo árbol que Config/KubeJS (ver file_tree.js): entero, sin paginar.
function renderWfTree() {
  var tree = document.getElementById('wf-tree');
  var count = document.getElementById('wf-tree-count');
  var hasFilter = activeWfFilter.length > 0;
  count.textContent = treeCountText(
    countTreeFiles(worldFiles, filteredWfKeys, activeWfFilter, wfGetFilteredFiles),
    countTreeFiles(worldFiles, Object.keys(worldFiles), '', wfGetFilteredFiles),
    'archivo', 'archivos', hasFilter);
  count.style.display = '';
  if (!filteredWfKeys.length) {
    tree.innerHTML = '<p class="empty-msg pad-m">' + t('Sin resultados') + '</p>';
    return;
  }
  var html = '';
  filteredWfKeys.forEach(function(key) {
    var label = key === '__root__' ? t('Raíz del mundo') : key;
    var allFiles = worldFiles[key];
    var files = wfGetFilteredFiles(allFiles, key, activeWfFilter);
    var openClass = hasFilter ? ' open' : '';
    html += '<div class="mod-group">'
      + '<div class="mod-group-header' + openClass + '"><span>' + escHtml(label)
      + ' <span class="text-muted fw-normal">(' + files.length
      + (allFiles.length !== files.length ? '/' + allFiles.length : '') + ')</span></span>'
      + '<svg class="icon mg-arrow" aria-hidden="true"><use href="#i-chevron-right"/></svg></div>'
      + '<div class="mod-file-list' + openClass + '">';
    files.forEach(function(filePath) {
      var fname = filePath.split('/').pop();
      var display = escHtml(fname);
      if (hasFilter) {
        var filterLower = activeWfFilter.toLowerCase();
        var matchIndex = fname.toLowerCase().indexOf(filterLower);
        if (matchIndex !== -1) {
          display = escHtml(fname.substring(0, matchIndex))
            + '<mark class="hl">'
            + escHtml(fname.substring(matchIndex, matchIndex + activeWfFilter.length)) + '</mark>'
            + escHtml(fname.substring(matchIndex + activeWfFilter.length));
        }
      }
      html += '<div class="cfg-file-item mod-file-item" data-path="' + escHtml(filePath) + '" data-type="wf">'
        + display + '</div>';
    });
    html += '</div></div>';
  });
  tree.innerHTML = html;
  tree.querySelectorAll('.mod-group-header').forEach(function(header) {
    header.addEventListener('click', function() {
      this.classList.toggle('open');
      this.nextElementSibling.classList.toggle('open');
    });
  });
}
