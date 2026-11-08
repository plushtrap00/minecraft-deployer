// Página Modpacks: tabla de modpacks instalados, selección, borrado y
// pestañas del panel de gestión. Cada pestaña tiene su propio archivo
// (server_props.js, jvm_ram.js, file_tree.js, kubejs.js, logs.js, mods.js...).

// -- Gestión de modpacks ------------------------------------------------------
var currentModpack = null;
var modConfigs = {};
var kubejsFiles = {};
var selectedConfigPath = null;
var filteredModKeys = [];
var filteredKjsKeys = [];
var modPage = 0;
var kjsPage = 0;
var PAGE_SIZE = 25;
// Último /api/modpacks por nombre: la cabecera del modpack que se gestiona
// lo usa para el logo y el color del modloader.
var modpackInfo = {};

document.getElementById('btn-refresh-packs').addEventListener('click', loadModpacks);

function loadModpacks() {
  var list = document.getElementById('modpack-list');
  list.innerHTML = '<div class="skeleton-rows"><div></div><div></div><div></div></div>';
  apiFetch('/api/modpacks')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderModpacks(data.modpacks); })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg error-msg">No se pudo cargar la lista de modpacks. Pulsa «Actualizar» para reintentarlo.</p>';
    });
}

// Una fila por modpack, en tabla, para poder comparar de un vistazo
// modloader, versión, mods y cuándo se usó por última vez. El tamaño se pide
// aparte (puede tardar con mundos grandes) y se rellena cuando llega.
function renderModpacks(packs) {
  var list = document.getElementById('modpack-list');
  // La URL puede apuntar a un modpack que ya no existe (borrado, renombrado).
  if (currentModpack && !(packs || []).some(function(pack) { return pack.name === currentModpack; })) {
    closeModpackPanel();
    replaceRoute();
  }
  if ((packs || []).length >= 5) {
    unlockAchievement('collector');
  }
  modpackInfo = {};
  (packs || []).forEach(function(pack) {
    modpackInfo[pack.name] = pack;
  });
  if (currentModpack && modpackInfo[currentModpack]) {
    renderMgmtHeader(currentModpack);
  }
  if (!packs || !packs.length) {
    list.innerHTML = emptyArt('chest', 'El cofre está vacío',
      'Todavía no hay modpacks instalados. Sube uno, créalo desde cero o búscalo en Modrinth o CurseForge.',
      '<button class="btn-go" id="packs-empty-install">' + icon('package-plus') + 'Instalar un modpack</button>');
    document.getElementById('packs-empty-install').addEventListener('click', function() {
      document.getElementById('tab-deploy').click();
    });
    return;
  }
  var table = document.createElement('div');
  table.className = 'pack-table';
  table.setAttribute('role', 'table');
  table.innerHTML = '<div class="pack-row pack-row-head" role="row">'
    + '<span role="columnheader">Nombre</span>'
    + '<span role="columnheader">Versión</span>'
    + '<span role="columnheader">Mods</span>'
    + '<span role="columnheader">Último arranque</span>'
    + '<span role="columnheader">Tamaño</span>'
    + '<span role="columnheader"><span class="visually-hidden">Acciones</span></span>'
    + '</div>';
  packs.forEach(function(pack) {
    var flags = [];
    if (!pack.start_script) {
      flags.push('<span class="pack-flag pack-flag-bad">No tiene script de arranque</span>');
    }
    if (pack.pending_mods && pack.pending_mods.length) {
      flags.push('<span class="pack-flag pack-flag-warn" title="' + escHtml(pack.pending_mods.join(', ')) + '">'
        + pack.pending_mods.length + (pack.pending_mods.length === 1 ? ' mod pendiente' : ' mods pendientes') + '</span>');
    }
    var row = document.createElement('div');
    row.className = 'pack-row modpack-card' + (pack.name === currentModpack ? ' selected' : '');
    row.setAttribute('role', 'row');
    row.dataset.name = pack.name;
    if (pack.modloader) {
      row.dataset.loader = pack.modloader.toLowerCase();
    }
    row.innerHTML = '<span class="pack-name" role="cell">' + packIconHtml(pack, 'sm')
      + '<span class="pack-name-text">' + escHtml(pack.name) + '</span>' + flags.join('') + '</span>'
      + '<span class="pack-version" role="cell">' + loaderTag(pack.modloader)
      + (pack.mc_version ? ' <span>' + escHtml(pack.mc_version) + '</span>' : '') + '</span>'
      + '<span class="pack-num" role="cell" data-label="Mods">' + (pack.mods_count === null || pack.mods_count === undefined ? '—' : pack.mods_count) + '</span>'
      + '<span class="pack-muted" role="cell" data-label="Último arranque">' + (pack.last_played ? formatRelativeDate(pack.last_played) : 'Nunca') + '</span>'
      + '<span class="pack-num pack-size" role="cell" data-label="Tamaño">…</span>'
      + '<span class="pack-actions" role="cell"><button class="btn-secondary btn-sm">Gestionar</button></span>';
    row.querySelector('button').addEventListener('click', function(event) {
      event.stopPropagation();
      openModpack(pack.name);
    });
    row.addEventListener('click', function() { openModpack(pack.name); });
    table.appendChild(row);
    loadModpackSize(pack.name, row.querySelector('.pack-size'));
  });
  list.innerHTML = '';
  list.appendChild(table);
}

function loadModpackSize(name, cell) {
  apiFetch('/api/modpacks/' + encodeURIComponent(name) + '/size')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      cell.textContent = data.size_bytes === undefined ? '—' : fmtSize(data.size_bytes);
    })
    .catch(function() {
      cell.textContent = '—';
    });
}

// Abrir un modpack desde la tabla: pasa por la navegación (URL, cambios sin
// guardar...); la ruta luego llama a selectModpack().
function openModpack(name) {
  navigate({ page: 'manage', modpack: name, tab: 'props' });
}

function selectModpack(name, tab) {
  if (guardModOperationNav()) {
    return;
  }
  if (currentModpack && currentModpack !== name) {
    cancelFetchesMatching('/api/modpacks/' + encodeURIComponent(currentModpack));
  }
  currentModpack = name;
  document.querySelectorAll('.modpack-card').forEach(function(card) {
    card.classList.toggle('selected', card.dataset.name === name);
  });
  document.getElementById('mgmt-title').textContent = name;
  renderMgmtHeader(name);
  document.getElementById('mgmt-panel').classList.add('show');
  activateMgmtTab(tab || 'props');
  loadWorlds();
  loadKubejs();
}

// Cabecera del modpack que se gestiona: logo y una franja del color de su
// modloader. Si la lista aún no ha llegado, se completa cuando llegue.
function renderMgmtHeader(name) {
  var pack = modpackInfo[name] || { name: name };
  var card = document.getElementById('mgmt-card');
  if (pack.modloader) {
    card.dataset.loader = pack.modloader.toLowerCase();
  } else {
    delete card.dataset.loader;
  }
  document.getElementById('mgmt-icon').innerHTML = packIconHtml(pack);
}

// -- Borrar modpack completo (triple confirmación) -----------------------------
// Es la acción más destructiva de todo el panel (mundos, config de mods y
// KubeJS, todo) — de ahí las tres confirmaciones seguidas en vez de la
// habitual showConfirm() única que usa el resto del panel para borrar un
// mundo o un archivo suelto.
document.getElementById('btn-delete-modpack').addEventListener('click', function() {
  if (!currentModpack) {
    return;
  }
  var name = currentModpack;
  showConfirm(
    '¿Borrar "' + name + '"?',
    'Se borrará la carpeta del modpack por completo.',
    function() {
      showConfirm(
        '¿Estás seguro?',
        'Los mundos se perderán, y la configuración de mods y KubeJS también.',
        function() {
          showConfirm(
            'Última oportunidad',
            '¿Estás seguro de que quieres borrar "' + name + '"? Esta acción no se puede deshacer.',
            function() { deleteModpack(name); },
            { confirmLabel: 'Sí, borrar definitivamente' }
          );
        }
      );
    }
  );
});

function deleteModpack(name) {
  apiFetch('/api/modpacks/' + encodeURIComponent(name), { method: 'DELETE' })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (result.ok) {
        showToast('Modpack "' + name + '" borrado', 'success');
        if (currentModpack === name) {
          closeModpackPanel();
          replaceRoute();
        }
        loadModpacks();
      } else {
        showToast(result.data.detail || 'No se pudo borrar', 'error');
      }
    })
    .catch(function() {
      showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error');
    });
}

['props', 'ram', 'configs', 'kubejs', 'worldfiles', 'logs', 'mods', 'backups'].forEach(function(name) {
  document.getElementById('mtab-' + name).addEventListener('click', function() {
    if (name === activeMgmtTab()) {
      activateMgmtTab(name);  // pulsar la pestaña en la que ya estás la recarga
      return;
    }
    navigate({ page: 'manage', modpack: currentModpack, tab: name });
  });
});

function closeModpackPanel() {
  currentModpack = null;
  document.querySelectorAll('.modpack-card').forEach(function(card) {
    card.classList.remove('selected');
  });
  document.getElementById('mgmt-panel').classList.remove('show');
}

function activateMgmtTab(name) {
  // Acotado a #mgmt-panel-tabs: .mgmt-tab también se usa (con otro
  // significado) en las sub-pestañas de la página de despliegue y en el
  // modal de búsqueda de mods — sin este scope, esta función también les
  // quitaba el estado "active" a esos botones por compartir la misma clase.
  document.querySelectorAll('#mgmt-panel-tabs .mgmt-tab').forEach(function(tab) {
    tab.classList.remove('active');
  });
  document.querySelectorAll('.mgmt-content').forEach(function(content) {
    content.classList.remove('active');
  });
  document.getElementById('mtab-' + name).classList.add('active');
  document.getElementById('mgmt-' + name).classList.add('active');
  if (name === 'mods') {
    loadModsList();
    loadModpackVersion();
  }
  if (name === 'logs') {
    loadLogList();
  }
  if (name === 'configs') {
    loadModConfigs();
  }
  if (name === 'kubejs') {
    loadKubejs();
  }
  if (name === 'worldfiles') {
    loadWorldFilesTab();
  }
  if (name === 'props') {
    loadServerProps();
  }
  if (name === 'ram') {
    loadRamConfig();
  }
  if (name === 'backups') {
    loadBackups();
  }
}
