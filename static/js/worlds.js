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
          if (bop) {
            bop.disabled = !data.has_biomesoplenty;
            bop.textContent = '🌺 Biomes O Plenty' + (data.has_biomesoplenty ? ' — detectado' : ' — mod no detectado');
          }
          if (terraForged) {
            terraForged.disabled = !data.has_terraforged;
            terraForged.textContent = '🏔️ TerraForged' + (data.has_terraforged ? ' — detectado' : ' — mod no detectado');
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
