// Árboles de archivos de las pestañas Config de mods y KubeJS. Se pintan
// enteros dentro de la caja con scroll (.mod-tree-body): los grupos salen
// plegados, así que aunque haya cientos de mods no pesa, y paginar además
// del scroll solo obligaba a ir pasando páginas.

// -- Config de mods -----------------------------------------------------------
function loadModConfigs() {
  document.getElementById('mod-tree').innerHTML = loadingHtml();
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/configs')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      modConfigs = data.mods;
      filteredModKeys = sortedKeys(modConfigs, null);
      renderTree('mod');
    })
    .catch(function() {
      document.getElementById('mod-tree').innerHTML =
        '<p class="empty-msg error-msg pad-m">No se pudieron cargar los archivos de config. Vuelve a abrir la pestaña para reintentarlo.</p>';
    });
}

document.getElementById('mod-search').addEventListener('input', function() {
  activeModFilter = this.value;
  filteredModKeys = sortedKeys(modConfigs, this.value);
  renderTree('mod');
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
        renderTree('kjs');
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
  renderTree('kjs');
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

// Texto del pie del árbol: el total, o «X de Y» si hay un filtro puesto.
function treeCountText(shown, total, singular, plural, hasFilter) {
  var noun = total === 1 ? singular : plural;
  return hasFilter ? shown + ' de ' + total + ' ' + noun : total + ' ' + noun;
}

// Cuenta los archivos de los grupos dados (solo los que pasan el filtro, si hay).
function countTreeFiles(data, keys, filter, filterFn) {
  return keys.reduce(function(sum, key) {
    return sum + (filter ? filterFn(data[key], key, filter) : data[key]).length;
  }, 0);
}

function renderTree(which) {
  var isKjs = which === 'kjs';
  var keys = isKjs ? filteredKjsKeys : filteredModKeys;
  var data = isKjs ? kubejsFiles : modConfigs;
  var filter = isKjs ? activeKjsFilter : activeModFilter;
  var treeId = isKjs ? 'kubejs-tree' : 'mod-tree';
  var countId = isKjs ? 'kubejs-tree-count' : 'mod-tree-count';
  var itemClass = isKjs ? 'kjs-file-item mod-file-item' : 'cfg-file-item mod-file-item';
  var tree = document.getElementById(treeId);
  var count = document.getElementById(countId);
  var hasFilter = filter.length > 0;
  // Config cuenta mods (la raíz de config/ no es un mod); KubeJS cuenta
  // archivos, porque sus grupos son carpetas y no mods.
  if (isKjs) {
    count.textContent = treeCountText(countTreeFiles(data, keys, filter, getFilteredFiles),
      countTreeFiles(data, Object.keys(data), '', getFilteredFiles), 'archivo', 'archivos', hasFilter);
  } else {
    var notRoot = function(key) { return key !== '__root__'; };
    count.textContent = treeCountText(keys.filter(notRoot).length,
      Object.keys(data).filter(notRoot).length, 'mod', 'mods', hasFilter);
  }
  count.style.display = '';
  if (!keys.length) {
    tree.innerHTML = '<p class="empty-msg pad-m">Sin resultados</p>';
    return;
  }
  var html = '';
  keys.forEach(function(key) {
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
}
