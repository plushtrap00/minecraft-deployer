// Árboles de archivos paginados de las pestañas Config de mods y KubeJS.

// -- Config de mods -----------------------------------------------------------
function loadModConfigs() {
  document.getElementById('mod-tree').innerHTML = loadingHtml();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/configs')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      modConfigs = data.mods;
      filteredModKeys = sortedKeys(modConfigs, null);
      modPage = 0;
      renderTreePage('mod');
    })
    .catch(function() {
      document.getElementById('mod-tree').innerHTML =
        '<p class="empty-msg error-msg pad-m">No se pudieron cargar los archivos de config. Vuelve a abrir la pestaña para reintentarlo.</p>';
    });
}

document.getElementById('mod-search').addEventListener('input', function() {
  activeModFilter = this.value;
  filteredModKeys = sortedKeys(modConfigs, this.value);
  modPage = 0;
  renderTreePage('mod');
});

document.getElementById('pg-prev').addEventListener('click', function() {
  modPage--;
  renderTreePage('mod');
});

document.getElementById('pg-next').addEventListener('click', function() {
  modPage++;
  renderTreePage('mod');
});


// -- KubeJS -------------------------------------------------------------------
function loadKubejs() {
  var tab = document.getElementById('mtab-kubejs');
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.exists) {
        tab.style.display = 'inline-block';
        kubejsFiles = data.groups;
        filteredKjsKeys = sortedKeys(kubejsFiles, null);
        kjsPage = 0;
        renderTreePage('kjs');
        var downloadBtn = document.getElementById('btn-download-kjs');
        downloadBtn.href = '/api/modpacks/' + encodeURIComponent(currentModpack)
          + '/kubejs/download';
        downloadBtn.setAttribute('download', currentModpack + '-kubejs.zip');
      } else {
        tab.style.display = 'none';
      }
    })
    .catch(function() { tab.style.display = 'none'; });
}

document.getElementById('kubejs-search').addEventListener('input', function() {
  activeKjsFilter = this.value;
  filteredKjsKeys = sortedKeys(kubejsFiles, this.value);
  kjsPage = 0;
  renderTreePage('kjs');
});

document.getElementById('kpg-prev').addEventListener('click', function() {
  kjsPage--;
  renderTreePage('kjs');
});

document.getElementById('kpg-next').addEventListener('click', function() {
  kjsPage++;
  renderTreePage('kjs');
});


// -- Tree renderer ------------------------------------------------------------
var activeModFilter = '';
var activeKjsFilter = '';

function sortedKeys(data, filter) {
  var keys = Object.keys(data).sort(function(a, b) {
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
        return data[key].some(function(filename) { return filename.toLowerCase().indexOf(filterLower) !== -1; });
      }
      return key.toLowerCase().indexOf(filterLower) !== -1
        || data[key].some(function(filename) { return filename.toLowerCase().indexOf(filterLower) !== -1; });
    });
  }
  return keys;
}

function getFilteredFiles(files, groupKey, filter) {
  if (!filter) {
    return files;
  }
  var filterLower = filter.toLowerCase();
  if (groupKey !== '__root__' && groupKey.toLowerCase().indexOf(filterLower) !== -1) {
    return files;
  }
  return files.filter(function(filename) { return filename.toLowerCase().indexOf(filterLower) !== -1; });
}

function renderTreePage(which) {
  var isKjs = which === 'kjs';
  var keys = isKjs ? filteredKjsKeys : filteredModKeys;
  var data = isKjs ? kubejsFiles : modConfigs;
  var page = isKjs ? kjsPage : modPage;
  var filter = isKjs ? activeKjsFilter : activeModFilter;
  var treeId = isKjs ? 'kubejs-tree' : 'mod-tree';
  var pgId = isKjs ? 'kubejs-pagination' : 'mod-pagination';
  var prevId = isKjs ? 'kpg-prev' : 'pg-prev';
  var nextId = isKjs ? 'kpg-next' : 'pg-next';
  var infoId = isKjs ? 'kpg-info' : 'pg-info';
  var itemClass = isKjs ? 'kjs-file-item mod-file-item' : 'cfg-file-item mod-file-item';
  var tree = document.getElementById(treeId);
  var pg = document.getElementById(pgId);
  var total = keys.length;
  if (!total) {
    tree.innerHTML = '<p class="empty-msg pad-m">Sin resultados</p>';
    pg.style.display = 'none';
    return;
  }
  var hasFilter = filter.length > 0;
  var start = page * PAGE_SIZE;
  var end = Math.min(start + PAGE_SIZE, total);
  var html = '';
  keys.slice(start, end).forEach(function(key) {
    var label;
    if (key === '__root__') {
      label = isKjs ? 'Raíz de kubejs' : 'Raíz de config';
    } else {
      label = key;
    }
    var allFiles = data[key];
    var files = getFilteredFiles(allFiles, key, filter);
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
        var filterLower = filter.toLowerCase();
        var matchIndex = fname.toLowerCase().indexOf(filterLower);
        if (matchIndex !== -1) {
          display = escHtml(fname.substring(0, matchIndex))
            + '<mark class="hl">'
            + escHtml(fname.substring(matchIndex, matchIndex + filter.length)) + '</mark>'
            + escHtml(fname.substring(matchIndex + filter.length));
        }
      }
      html += '<div class="' + itemClass + '" data-path="' + escHtml(filePath) + '" data-type="' + (isKjs ? 'kjs' : 'cfg') + '">'
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
    document.getElementById(infoId).textContent = 'Pág.' + (page + 1) + '/' + totalPages + ' (' + total + ')';
  } else {
    document.getElementById(infoId).textContent = total + ' mods';
  }
  document.getElementById(prevId).disabled = page === 0;
  document.getElementById(nextId).disabled = page >= totalPages - 1;
}
