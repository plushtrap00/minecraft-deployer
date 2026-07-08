// -- Mundos -------------------------------------------------------------------
function loadWorlds() {
  var list = document.getElementById('worlds-list');
  if (!list) {
    return;
  }
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderWorlds(data); })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg" style="color:var(--red)">Error al cargar mundos</p>';
    });
}

function renderWorlds(data) {
  var list = document.getElementById('worlds-list');
  var worlds = data.worlds;
  if (!worlds || !worlds.length) {
    list.innerHTML = '<p class="empty-msg">No se detectaron mundos generados aún.</p>'
      + '<p class="hint" style="margin-top:6px">Mundo configurado: <code>' + (data.active || 'world') + '</code>'
      + ' · Tipo: <code>' + (data.level_type || 'minecraft:normal') + '</code></p>';
    return;
  }
  var html = '';
  worlds.forEach(function(world) {
    var activeBadge = world.active
      ? '<span style="font-size:.72rem;background:rgba(63,185,80,.15);color:var(--green);padding:2px 8px;border-radius:99px;font-weight:600">✓ Activo</span>'
      : '';
    var activateBtn = !world.active
      ? '<button class="btn-secondary wc-activate" data-world="' + world.name + '" style="font-size:.78rem;padding:5px 10px">Activar</button>'
      : '';
    var deleteBtn = !world.active
      ? '<button class="btn-danger wc-delete" data-world="' + world.name + '" style="font-size:.78rem;padding:5px 10px">🗑 Borrar</button>'
      : '';
    var downloadUrl = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/' + encodeURIComponent(world.name) + '/download?token=' + encodeURIComponent(authToken);
    var downloadBtn = '<a href="' + downloadUrl + '" download="' + world.name + '.zip" class="btn-secondary" style="font-size:.78rem;padding:5px 10px;text-decoration:none">⬇ Descargar</a>';
    var worldIcon = world.active ? '🟢' : '🌍';
    var activeClass = world.active ? ' active-world' : '';
    html += '<div class="world-card' + activeClass + '">'
      + '<span style="font-size:1.5rem">' + worldIcon + '</span>'
      + '<div style="flex:1">'
      + '<div style="font-weight:600">' + world.name + ' ' + activeBadge + '</div>'
      + '<div style="font-size:.78rem;color:var(--muted)">' + world.size_mb + ' MB en disco</div>'
      + '</div>'
      + '<div class="wc-actions">' + activateBtn + downloadBtn + deleteBtn + '</div>'
      + '</div>';
  });
  var seedHint = data.seed ? ' · Seed: <code>' + data.seed + '</code>' : '';
  html += '<p class="hint" style="margin-top:8px">Tipo actual: <code>' + (data.level_type || 'minecraft:normal') + '</code>'
    + seedHint + '</p>';
  list.innerHTML = html;
}

document.addEventListener('click', function(event) {
  var activateBtn = event.target.closest('.wc-activate');
  if (activateBtn) {
    activateWorld(activateBtn.dataset.world);
    return;
  }
  var deleteBtn = event.target.closest('.wc-delete');
  if (deleteBtn) {
    deleteWorld(deleteBtn.dataset.world);
  }
});

function activateWorld(name) {
  showConfirm(
    'Activar el mundo "' + name + '"',
    'El servidor usará este mundo en el próximo inicio.',
    function() { doActivateWorld(name); }
  );
}

function doActivateWorld(name) {
  var form = new FormData();
  form.append('world_name', name);
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/activate', {
    method: 'POST',
    body: form
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        showToast('Mundo activado', 'success');
        loadWorlds();
        loadServerProps();
      }
    })
    .catch(function() { showToast('Error', 'error'); });
}

function deleteWorld(name) {
  showConfirm(
    'Borrar "' + name + '"',
    'Se borrarán también sus dimensiones nether y end. Esta acción no se puede deshacer.',
    function() { doDeleteWorld(name); }
  );
}

function doDeleteWorld(name) {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/' + encodeURIComponent(name), {
    method: 'DELETE'
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        showToast('Mundo borrado', 'success');
        loadWorlds();
      }
    })
    .catch(function() { showToast('Error al borrar', 'error'); });
}


// -- Nuevo mundo (formulario inline) ------------------------------------------
var nwActivate = true;

var typeDescs = {
  'minecraft:normal':      'Mundo estándar con biomas variados, estructuras y terreno natural.',
  'minecraft:large_biomes':'Igual que el normal pero los biomas son mucho más grandes. Ideal para exploración.',
  'minecraft:amplified':   'Terreno extremo: montañas gigantescas, ravines profundísimas y posibles islas flotantes.',
  'minecraft:flat':        'Mundo completamente plano. Perfecto para construcciones y redstone a gran escala.',
  'biomesoplenty':         'Añade más de 90 biomas nuevos. Requiere el mod Biomes O Plenty instalado.',
  'terraforged':           'Generación de terreno realista y detallada. Requiere el mod TerraForged instalado.',
  'skyblockbuilder:skyblock': 'Mundo skyblock (islas vacías) generado por SkyblockBuilder — necesario para que el mod cree equipo/isla al unirse; "Normal" genera terreno vanilla normal aunque el mod esté instalado.',
  'custom':                'Introduce manualmente el identificador del tipo de mundo del mod que quieras usar.'
};

(function() {
  var btnNew = document.getElementById('btn-new-world');
  if (!btnNew) {
    return;
  }

  btnNew.addEventListener('click', function() {
    var form = document.getElementById('new-world-form');
    var isOpen = form.style.display !== 'none';
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
            bop.textContent = '🌺 Biomes O Plenty' + (data.has_biomesoplenty ? ' — detectado' : ' — mod no detectado');
          }
          if (terraForged) {
            terraForged.disabled = !data.has_terraforged;
            terraForged.textContent = '🏔️ TerraForged' + (data.has_terraforged ? ' — detectado' : ' — mod no detectado');
          }
          if (skyblock) {
            skyblock.disabled = !data.has_skyblockbuilder;
            skyblock.textContent = '🏝️ Skyblock (SkyblockBuilder)' + (data.has_skyblockbuilder ? ' — detectado' : ' — mod no detectado');
            // A diferencia de BOP/TerraForged (cosméticos, cualquiera de los
            // dos sirve como terreno "normal" si se elige mal), elegir el
            // tipo equivocado acá no es solo distinto: SkyblockBuilder
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
      showAlert('Escribe un nombre para el mundo');
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
      showAlert('Escribe el tipo de mundo');
      return;
    }
    var form = new FormData();
    form.append('world_name', name);
    form.append('level_type', worldType);
    form.append('seed', document.getElementById('nw-seed').value.trim());
    form.append('activate', nwActivate ? '1' : '0');
    apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds/create', {
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
          document.getElementById('new-world-form').style.display = 'none';
          document.getElementById('nw-name').value = '';
          document.getElementById('nw-seed').value = '';
          loadWorlds();
          if (nwActivate) {
            loadServerProps();
          }
        } else {
          showToast(result.data.detail || 'Error', 'error');
        }
      })
      .catch(function() { showToast('Error al crear mundo', 'error'); });
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
var wfPage = 0;
var activeWfFilter = '';
var selectedWfWorld = null;

function loadWorldFilesTab() {
  var select = document.getElementById('wf-world-select');
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/worlds')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var worlds = data.worlds || [];
      var prev = select.value;
      select.innerHTML = '<option value="">Selecciona un mundo...</option>' + worlds.map(function(w) {
        return '<option value="' + w.name + '">' + w.name + (w.active ? ' (activo)' : '') + '</option>';
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
        document.getElementById('wf-tree').innerHTML = '<p class="empty-msg" style="padding:12px">No hay mundos detectados</p>';
        document.getElementById('wf-pagination').style.display = 'none';
      }
    })
    .catch(function() {
      document.getElementById('wf-tree').innerHTML = '<p class="empty-msg" style="padding:12px;color:var(--red)">Error al cargar mundos</p>';
    });
}

document.getElementById('wf-world-select').addEventListener('change', function() {
  if (this.value) {
    loadWorldFiles(this.value);
  }
});

function loadWorldFiles(worldName) {
  selectedWfWorld = worldName;
  document.getElementById('wf-tree').innerHTML = '<p class="empty-msg" style="padding:12px">Cargando...</p>';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/world-files?world_name=' + encodeURIComponent(worldName))
    .then(function(response) { return response.json(); })
    .then(function(data) {
      worldFiles = data.groups;
      filteredWfKeys = wfSortedKeys(activeWfFilter);
      wfPage = 0;
      renderWfTreePage();
    })
    .catch(function() {
      document.getElementById('wf-tree').innerHTML = '<p class="empty-msg" style="padding:12px;color:var(--red)">Error al cargar archivos</p>';
    });
}

document.getElementById('wf-search').addEventListener('input', function() {
  activeWfFilter = this.value;
  filteredWfKeys = wfSortedKeys(activeWfFilter);
  wfPage = 0;
  renderWfTreePage();
});

document.getElementById('wfpg-prev').addEventListener('click', function() {
  wfPage--;
  renderWfTreePage();
});

document.getElementById('wfpg-next').addEventListener('click', function() {
  wfPage++;
  renderWfTreePage();
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

function renderWfTreePage() {
  var tree = document.getElementById('wf-tree');
  var pg = document.getElementById('wf-pagination');
  var total = filteredWfKeys.length;
  if (!total) {
    tree.innerHTML = '<p class="empty-msg" style="padding:12px">Sin resultados</p>';
    pg.style.display = 'none';
    return;
  }
  var hasFilter = activeWfFilter.length > 0;
  var start = wfPage * PAGE_SIZE;
  var end = Math.min(start + PAGE_SIZE, total);
  var html = '';
  filteredWfKeys.slice(start, end).forEach(function(key) {
    var label = key === '__root__' ? '📄 Raíz del mundo' : '📁 ' + key;
    var allFiles = worldFiles[key];
    var files = wfGetFilteredFiles(allFiles, key, activeWfFilter);
    var openClass = hasFilter ? ' open' : '';
    html += '<div class="mod-group">'
      + '<div class="mod-group-header' + openClass + '"><span>' + label
      + ' <span style="color:var(--muted);font-weight:400">(' + files.length
      + (allFiles.length !== files.length ? '/' + allFiles.length : '') + ')</span></span>'
      + '<span class="mg-arrow">▶</span></div>'
      + '<div class="mod-file-list' + openClass + '">';
    files.forEach(function(filePath) {
      var fname = filePath.split('/').pop();
      var display = fname;
      if (hasFilter) {
        var filterLower = activeWfFilter.toLowerCase();
        var matchIndex = fname.toLowerCase().indexOf(filterLower);
        if (matchIndex !== -1) {
          display = fname.substring(0, matchIndex)
            + '<mark style="background:rgba(210,153,34,.35);color:var(--text);border-radius:2px">'
            + fname.substring(matchIndex, matchIndex + activeWfFilter.length) + '</mark>'
            + fname.substring(matchIndex + activeWfFilter.length);
        }
      }
      html += '<div class="cfg-file-item mod-file-item" data-path="' + filePath + '" data-type="wf">'
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
  var totalPages = Math.ceil(total / PAGE_SIZE);
  pg.style.display = 'flex';
  if (totalPages > 1) {
    document.getElementById('wfpg-info').textContent = 'Pág.' + (wfPage + 1) + '/' + totalPages + ' (' + total + ')';
  } else {
    document.getElementById('wfpg-info').textContent = total + ' archivos';
  }
  document.getElementById('wfpg-prev').disabled = wfPage === 0;
  document.getElementById('wfpg-next').disabled = wfPage >= totalPages - 1;
}
