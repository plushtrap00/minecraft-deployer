// -- Config form parser -------------------------------------------------------
var cfgFormMode = 'form'; // 'form' or 'raw'
var cfgParsed = null;     // parsed sections when in form mode
var cfgRawText = '';      // original raw text

function isFormattable(filename) {
  var ext = filename.split('.').pop().toLowerCase();
  return ext === 'toml' || ext === 'cfg';
}

function parseConfigText(text) {
  var sections = [];
  var current = null;
  var comments = [];
  var lines = text.split('\n');
  lines.forEach(function(line) {
    var trimmedLine = line.trim();
    if (!trimmedLine) {
      comments = [];
      return;
    }
    var sectionMatch = trimmedLine.match(/^\[([^\]]+)\]$/);
    if (sectionMatch) {
      if (current) {
        sections.push(current);
      }
      current = { name: sectionMatch[1], fields: [] };
      comments = [];
      return;
    }
    if (trimmedLine.startsWith('#')) {
      comments.push(trimmedLine.substring(1).trim());
      return;
    }
    var keyValueMatch = trimmedLine.match(/^([\w.]+)\s*=\s*(.*)$/);
    if (keyValueMatch && current) {
      var key = keyValueMatch[1];
      var val = keyValueMatch[2].trim();
      var desc = [];
      var defVal = null;
      var range = null;
      comments.forEach(function(comment) {
        if (comment.startsWith('Default:')) {
          defVal = comment.substring(8).trim();
        } else if (comment.startsWith('Range:')) {
          range = comment.substring(6).trim();
        } else {
          desc.push(comment);
        }
      });
      var type;
      if (val === 'true' || val === 'false') {
        type = 'boolean';
      } else if (val.startsWith('[')) {
        type = 'list';
      } else if (/^-?\d+\.\d+$/.test(val)) {
        type = 'float';
      } else if (/^-?\d+$/.test(val)) {
        type = 'integer';
      } else {
        type = 'string';
      }
      current.fields.push({ key: key, value: val, type: type, desc: desc.join(' '), defVal: defVal, range: range });
      comments = [];
    }
  });
  if (current) {
    sections.push(current);
  }
  return sections;
}

function renderConfigForm(sections) {
  var el = document.getElementById('cfg-form-content');
  if (!sections || !sections.length) {
    el.innerHTML = '<p class="empty-msg">No se pudieron detectar campos en este archivo.</p>';
    return;
  }
  var html = '';
  sections.forEach(function(section, sectionIndex) {
    html += '<div class="cfg-section"><div class="cfg-section-title">[' + section.name + ']</div>';
    section.fields.forEach(function(field, fieldIndex) {
      var inputId = 'cfg_' + sectionIndex + '_' + fieldIndex;
      html += '<div class="cfg-field">';
      html += '<div class="cfg-field-header">'
        + '<span class="cfg-field-key">' + field.key + '</span>'
        + '<span class="cfg-field-type">' + field.type + '</span>'
        + '</div>';
      if (field.desc) {
        html += '<div class="cfg-field-desc">' + escHtml(field.desc) + '</div>';
      }
      if (field.type === 'boolean') {
        var isOn = field.value === 'true';
        var trackClass = isOn ? ' on' : '';
        var boolLabel = isOn ? 'true' : 'false';
        html += '<div class="cfg-toggle-row">'
          + '<div class="toggle-track' + trackClass + '" id="' + inputId + '"'
          + ' data-si="' + sectionIndex + '" data-fi="' + fieldIndex + '" data-cfgkey="' + field.key + '">'
          + '<div class="toggle-thumb"></div></div>'
          + '<span style="font-size:.83rem;color:var(--muted)">' + boolLabel + '</span>'
          + '</div>';
      } else if (field.type === 'list') {
        html += '<textarea class="cfg-list-input" id="' + inputId + '"'
          + ' data-si="' + sectionIndex + '" data-fi="' + fieldIndex + '">'
          + escHtml(field.value) + '</textarea>';
      } else {
        var inputType = (field.type === 'integer' || field.type === 'float') ? 'number' : 'text';
        var stepAttr = field.type === 'float' ? ' step="any"' : '';
        html += '<input type="' + inputType + '"'
          + ' class="cfg-input" id="' + inputId + '"'
          + ' data-si="' + sectionIndex + '" data-fi="' + fieldIndex + '"'
          + ' value="' + escHtml(field.value) + '"'
          + stepAttr + '>';
      }
      if (field.defVal || field.range) {
        html += '<div class="cfg-field-meta">';
        if (field.defVal) {
          html += 'Por defecto: <span>' + escHtml(field.defVal) + '</span> ';
        }
        if (field.range) {
          html += '&nbsp;·&nbsp; Rango: <span>' + escHtml(field.range) + '</span>';
        }
        html += '</div>';
      }
      html += '</div>';
    });
    html += '</div>';
  });
  el.innerHTML = html;
  el.querySelectorAll('.toggle-track[data-cfgkey]').forEach(function(track) {
    track.addEventListener('click', function() {
      this.classList.toggle('on');
      var label = this.nextElementSibling;
      if (label) {
        label.textContent = this.classList.contains('on') ? 'true' : 'false';
      }
      var sectionIndex = parseInt(this.dataset.si);
      var fieldIndex = parseInt(this.dataset.fi);
      if (cfgParsed && cfgParsed[sectionIndex] && cfgParsed[sectionIndex].fields[fieldIndex]) {
        cfgParsed[sectionIndex].fields[fieldIndex].value = this.classList.contains('on') ? 'true' : 'false';
      }
    });
  });
}

function formToRawText() {
  if (!cfgParsed) {
    return cfgRawText;
  }
  var newVals = {};
  cfgParsed.forEach(function(section, sectionIndex) {
    section.fields.forEach(function(field, fieldIndex) {
      var id = 'cfg_' + sectionIndex + '_' + fieldIndex;
      var el = document.getElementById(id);
      if (!el) {
        return;
      }
      var val = field.type === 'boolean' ? field.value : el.value;
      newVals[section.name + '::' + field.key] = val;
    });
  });
  var currentSec = null;
  var lines = cfgRawText.split('\n');
  return lines.map(function(line) {
    var trimmedLine = line.trim();
    var sectionMatch = trimmedLine.match(/^\[([^\]]+)\]$/);
    if (sectionMatch) {
      currentSec = sectionMatch[1];
      return line;
    }
    if (trimmedLine.startsWith('#') || !trimmedLine) {
      return line;
    }
    var keyValueMatch = trimmedLine.match(/^([\w.]+)\s*=\s*(.*)$/);
    if (keyValueMatch && currentSec) {
      var lookup = currentSec + '::' + keyValueMatch[1];
      if (newVals[lookup] !== undefined) {
        var indent = line.match(/^(\s*)/)[1];
        return indent + keyValueMatch[1] + ' = ' + newVals[lookup];
      }
    }
    return line;
  }).join('\n');
}

function setCfgMode(mode) {
  cfgFormMode = mode;
  var formView = document.getElementById('cfg-form-view');
  var rawView = document.getElementById('cfg-raw-view');
  var btnForm = document.getElementById('cfg-btn-form');
  var btnRaw = document.getElementById('cfg-btn-raw');
  if (mode === 'form') {
    formView.style.display = 'block';
    rawView.style.display = 'none';
    btnForm.classList.add('active');
    btnRaw.classList.remove('active');
    if (cfgParsed) {
      renderConfigForm(cfgParsed);
    }
  } else {
    if (cfgParsed) {
      document.getElementById('config-editor').value = formToRawText();
    }
    formView.style.display = 'none';
    rawView.style.display = 'flex';
    btnRaw.classList.add('active');
    btnForm.classList.remove('active');
    syncLines();
  }
}

document.getElementById('cfg-btn-form').addEventListener('click', function() { setCfgMode('form'); });
document.getElementById('cfg-btn-raw').addEventListener('click', function() { setCfgMode('raw'); });


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

document.getElementById('btn-refresh-packs').addEventListener('click', loadModpacks);

function loadModpacks() {
  var list = document.getElementById('modpack-list');
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderModpacks(data.modpacks); })
    .catch(function() {
      list.innerHTML = '<p class="empty-msg" style="color:var(--red)">Error</p>';
    });
}

function renderModpacks(packs) {
  var list = document.getElementById('modpack-list');
  if (!packs || !packs.length) {
    list.innerHTML = '<p class="empty-msg">No hay modpacks en ~/servers-minecraft</p>';
    return;
  }
  list.innerHTML = '';
  packs.forEach(function(pack) {
    var badges = '';
    if (pack.has_server_properties) {
      badges += '<span class="badge badge-props">server.properties</span> ';
    }
    if (pack.has_config) {
      badges += '<span class="badge badge-config">config/</span> ';
    }
    if (pack.has_kubejs) {
      badges += '<span class="badge badge-kjs">KubeJS</span> ';
    }
    if (!pack.start_script) {
      badges += '<span class="badge" style="background:rgba(248,81,73,.15);color:var(--red)">⚠ sin script arranque</span>';
    }
    if (pack.mc_version) {
      badges += ' <span class="badge" style="background:rgba(88,166,255,.1);color:var(--accent)">MC ' + pack.mc_version + '</span>';
    }
    if (pack.modloader) {
      badges += ' <span class="badge" style="background:rgba(210,153,34,.1);color:var(--yellow)">' + pack.modloader + '</span>';
    }
    var element = document.createElement('div');
    element.className = 'modpack-card';
    element.dataset.name = pack.name;
    element.innerHTML = '<span style="font-size:1.4rem">🗂️</span>'
      + '<div style="flex:1">'
      + '<div style="font-weight:600">' + pack.name + '</div>'
      + '<div style="margin-top:3px">' + badges + '</div>'
      + '</div>'
      + '<button class="btn-secondary" style="font-size:.78rem;padding:5px 10px">Gestionar →</button>';
    element.querySelector('button').addEventListener('click', function(event) {
      event.stopPropagation();
      selectModpack(pack.name);
    });
    element.addEventListener('click', function() { selectModpack(pack.name); });
    list.appendChild(element);
  });
}

function selectModpack(name) {
  if (currentModpack && currentModpack !== name) {
    cancelFetchesMatching('/api/modpacks/' + encodeURIComponent(currentModpack));
  }
  currentModpack = name;
  document.querySelectorAll('.modpack-card').forEach(function(card) {
    card.classList.toggle('selected', card.dataset.name === name);
  });
  document.getElementById('mgmt-title').textContent = name;
  document.getElementById('mgmt-panel').classList.add('show');
  activateMgmtTab('props');
  loadWorlds();
}

['props', 'configs', 'kubejs', 'logs', 'mods'].forEach(function(name) {
  document.getElementById('mtab-' + name).addEventListener('click', function() {
    activateMgmtTab(name);
  });
});

function activateMgmtTab(name) {
  document.querySelectorAll('.mgmt-tab').forEach(function(tab) {
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
  if (name === 'props') {
    loadServerProps();
  }
}


// -- server.properties form ---------------------------------------------------
var KNOWN_KEYS = [
  'motd', 'server-port', 'max-players', 'online-mode', 'white-list', 'enforce-whitelist',
  'level-name', 'level-seed', 'level-type', 'gamemode', 'difficulty', 'hardcore',
  'generate-structures', 'allow-nether', 'pvp', 'spawn-monsters', 'spawn-animals',
  'spawn-npcs', 'allow-flight', 'spawn-protection', 'view-distance', 'simulation-distance',
  'network-compression-threshold', 'max-tick-time', 'rate-limit', 'enable-rcon',
  'rcon.port', 'rcon.password', 'enable-query', 'query.port', 'broadcast-rcon-to-ops'
];

function parseProps(text) {
  var props = {};
  text.split('\n').forEach(function(line) {
    line = line.trim();
    if (!line || line.startsWith('#')) {
      return;
    }
    var eq = line.indexOf('=');
    if (eq === -1) {
      return;
    }
    props[line.substring(0, eq).trim()] = line.substring(eq + 1).trim();
  });
  return props;
}

function serializeProps(props) {
  return Object.keys(props).map(function(key) { return key + '=' + props[key]; }).join('\n');
}

function propsToForm(props) {
  document.querySelectorAll('.prop-input').forEach(function(el) {
    var key = el.dataset.key;
    var val = props[key];
    if (val === undefined) {
      return;
    }
    if (el.tagName === 'SELECT' || el.type === 'text' || el.type === 'number') {
      el.value = val;
    }
  });
  document.querySelectorAll('.toggle-track[data-key]').forEach(function(track) {
    var key = track.dataset.key;
    var val = props[key];
    if (val === undefined) {
      return;
    }
    track.classList.toggle('on', val === 'true');
  });
  var unknown = {};
  Object.keys(props).forEach(function(key) {
    if (KNOWN_KEYS.indexOf(key) === -1) {
      unknown[key] = props[key];
    }
  });
  document.getElementById('props-raw-editor').value = serializeProps(unknown);
}

function formToProps(originalText) {
  var props = parseProps(originalText);
  document.querySelectorAll('.prop-input').forEach(function(el) {
    var key = el.dataset.key;
    if (!key) {
      return;
    }
    props[key] = el.value;
  });
  document.querySelectorAll('.toggle-track[data-key]').forEach(function(track) {
    var key = track.dataset.key;
    if (!key) {
      return;
    }
    props[key] = track.classList.contains('on') ? 'true' : 'false';
  });
  var rawText = document.getElementById('props-raw-editor').value;
  var rawProps = parseProps(rawText);
  Object.assign(props, rawProps);
  return props;
}

function buildPropsText(props, originalText) {
  var lines = originalText.split('\n');
  var updated = {};
  var result = lines.map(function(line) {
    var trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      return line;
    }
    var eq = trimmed.indexOf('=');
    if (eq === -1) {
      return line;
    }
    var key = trimmed.substring(0, eq).trim();
    if (props[key] !== undefined) {
      updated[key] = true;
      return key + '=' + props[key];
    }
    return line;
  });
  Object.keys(props).forEach(function(key) {
    if (!updated[key]) {
      result.push(key + '=' + props[key]);
    }
  });
  return result.join('\n');
}

var originalPropsText = '';

function loadServerProps() {
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/server-properties')
    .then(function(response) {
      if (!response.ok) {
        throw new Error();
      }
      return response.json();
    })
    .then(function(data) {
      originalPropsText = data.content;
      document.getElementById('props-editor').value = data.content;
      propsToForm(parseProps(data.content));
    })
    .catch(function() {
      document.getElementById('props-editor').value = '# server.properties no encontrado';
    });
}

document.querySelectorAll('.props-section-header').forEach(function(header) {
  header.addEventListener('click', function() {
    var section = this.dataset.section;
    var body = document.getElementById('ps-' + section);
    var collapsed = body.style.display === 'none';
    body.style.display = collapsed ? '' : 'none';
    this.classList.toggle('collapsed', !collapsed);
  });
});

document.getElementById('props-form').addEventListener('click', function(event) {
  var track = event.target.closest('.toggle-track[data-key]');
  if (track) {
    track.classList.toggle('on');
  }
});

document.getElementById('save-props-btn').addEventListener('click', function() {
  var props = formToProps(originalPropsText);
  var newText = buildPropsText(props, originalPropsText);
  var form = new FormData();
  form.append('content', newText);
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/server-properties', {
    method: 'POST',
    body: form
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        originalPropsText = newText;
        showToast('✅ server.properties guardado', 'success');
      }
    })
    .catch(function() { showToast('❌ Error al guardar', 'error'); });
});


// -- Config de mods -----------------------------------------------------------
function loadModConfigs() {
  document.getElementById('mod-tree').innerHTML = '<p class="empty-msg" style="padding:12px">Cargando...</p>';
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
        '<p class="empty-msg" style="padding:12px;color:var(--red)">Error</p>';
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
    tree.innerHTML = '<p class="empty-msg" style="padding:12px">Sin resultados</p>';
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
      label = isKjs ? '📄 Raíz de kubejs' : '📄 Raíz de config';
    } else {
      label = '📁 ' + key;
    }
    var allFiles = data[key];
    var files = getFilteredFiles(allFiles, key, filter);
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
        var filterLower = filter.toLowerCase();
        var matchIndex = fname.toLowerCase().indexOf(filterLower);
        if (matchIndex !== -1) {
          display = fname.substring(0, matchIndex)
            + '<mark style="background:rgba(210,153,34,.35);color:var(--text);border-radius:2px">'
            + fname.substring(matchIndex, matchIndex + filter.length) + '</mark>'
            + fname.substring(matchIndex + filter.length);
        }
      }
      html += '<div class="' + itemClass + '" data-path="' + filePath + '" data-type="' + (isKjs ? 'kjs' : 'cfg') + '">'
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


// -- File click delegation ----------------------------------------------------
document.addEventListener('click', function(event) {
  var item = event.target.closest('.mod-file-item');
  if (!item) {
    return;
  }
  openFile(item.dataset.path, item.dataset.type);
});

function openFile(path, type) {
  selectedConfigPath = type + ':' + path;
  document.querySelectorAll('.mod-file-item').forEach(function(el) {
    el.classList.toggle('selected', el.dataset.path === path && el.dataset.type === type);
  });
  document.getElementById('modal-path').textContent = (type === 'kjs' ? 'kubejs/' : 'config/') + path;
  document.getElementById('config-editor').value = 'Cargando...';
  cfgParsed = null;
  cfgRawText = '';
  var canForm = type === 'cfg' && isFormattable(path);
  var toolbar = document.getElementById('cfg-toolbar');
  var hint = document.getElementById('cfg-mode-hint');
  toolbar.style.display = canForm ? 'flex' : 'none';
  if (!canForm) {
    document.getElementById('cfg-form-view').style.display = 'none';
    document.getElementById('cfg-raw-view').style.display = 'flex';
    document.getElementById('cfg-btn-form').classList.remove('active');
    document.getElementById('cfg-btn-raw').classList.add('active');
    hint.textContent = '';
  } else {
    hint.textContent = 'Mostrando formulario generado del archivo';
    setCfgMode('form');
  }
  document.getElementById('editor-modal').classList.add('show');
  var endpoint = type === 'kjs' ? '/kubejs-file' : '/config-file';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + endpoint + '?path=' + encodeURIComponent(path))
    .then(function(response) { return response.json(); })
    .then(function(data) {
      cfgRawText = data.content;
      document.getElementById('config-editor').value = data.content;
      if (canForm) {
        cfgParsed = parseConfigText(data.content);
        if (cfgFormMode === 'form') {
          renderConfigForm(cfgParsed);
        }
      }
      syncLines();
    })
    .catch(function() {
      document.getElementById('config-editor').value = '# Error al cargar';
      syncLines();
    });
}


// -- Modal editor -------------------------------------------------------------
function closeModal() {
  document.getElementById('editor-modal').classList.remove('show');
}

document.getElementById('modal-close-btn').addEventListener('click', closeModal);
document.getElementById('modal-close-btn2').addEventListener('click', closeModal);
document.getElementById('editor-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closeModal();
  }
});

document.getElementById('modal-save-btn').addEventListener('click', function() {
  if (!selectedConfigPath) {
    return;
  }
  var parts = selectedConfigPath.split(':');
  var type = parts[0];
  var path = parts.slice(1).join(':');
  var textToSave;
  if (cfgParsed && cfgFormMode === 'form') {
    textToSave = formToRawText();
  } else {
    textToSave = document.getElementById('config-editor').value;
  }
  var form = new FormData();
  form.append('path', path);
  form.append('content', textToSave);
  var endpoint = type === 'kjs' ? '/kubejs-file' : '/config-file';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + endpoint, {
    method: 'POST',
    body: form
  })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.success) {
        showToast('Archivo guardado', 'success');
      }
    })
    .catch(function() { showToast('Error al guardar', 'error'); });
});

var ta = document.getElementById('config-editor');
var ln = document.getElementById('line-numbers');

function syncLines() {
  if (!ta || !ln) {
    return;
  }
  var lines = ta.value.split('\n');
  var nums = '';
  for (var i = 1; i <= lines.length; i++) {
    nums += i + '\n';
  }
  ln.textContent = nums;
  var lineNum = ta.value.substring(0, ta.selectionStart).split('\n').length;
  document.getElementById('line-info').textContent = 'Línea ' + lineNum + ' de ' + lines.length;
}

ta.addEventListener('input', syncLines);
ta.addEventListener('click', syncLines);
ta.addEventListener('keyup', syncLines);
ta.addEventListener('scroll', function() { ln.scrollTop = ta.scrollTop; });


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
      showToast('✅ Archivo creado', 'success');
      apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/kubejs')
        .then(function(r) { return r.json(); })
        .then(function(kdata) {
          if (kdata.exists) {
            kubejsFiles = kdata.groups;
            filteredKjsKeys = sortedKeys(kubejsFiles, activeKjsFilter);
            renderTreePage('kjs');
            openFile(data.path, 'kjs');
          }
        });
    })
    .catch(function(err) {
      showToast('❌ ' + err.message, 'error');
    });
});
