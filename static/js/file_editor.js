// Modal de edición de archivos (config de mods, KubeJS, archivos de mundo):
// vista de formulario para .toml/.json/.properties, texto plano con números
// de línea, y abrir/guardar el archivo.

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
    html += '<div class="cfg-section"><div class="cfg-section-title">[' + escHtml(section.name) + ']</div>';
    section.fields.forEach(function(field, fieldIndex) {
      var inputId = 'cfg_' + sectionIndex + '_' + fieldIndex;
      html += '<div class="cfg-field">';
      html += '<div class="cfg-field-header">'
        + '<span class="cfg-field-key" id="' + inputId + '_label">' + escHtml(field.key) + '</span>'
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
          + ' data-si="' + sectionIndex + '" data-fi="' + fieldIndex + '" data-cfgkey="' + escHtml(field.key) + '"'
          + ' aria-labelledby="' + inputId + '_label">'
          + '<div class="toggle-thumb"></div></div>'
          + '<span class="text-muted text-sm">' + boolLabel + '</span>'
          + '</div>';
      } else if (field.type === 'list') {
        html += '<textarea class="cfg-list-input" id="' + inputId + '" aria-labelledby="' + inputId + '_label"'
          + ' data-si="' + sectionIndex + '" data-fi="' + fieldIndex + '">'
          + escHtml(field.value) + '</textarea>';
      } else {
        var inputType = (field.type === 'integer' || field.type === 'float') ? 'number' : 'text';
        var stepAttr = field.type === 'float' ? ' step="any"' : '';
        html += '<input type="' + inputType + '"'
          + ' class="cfg-input" id="' + inputId + '" aria-labelledby="' + inputId + '_label"'
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
  var pathPrefix = type === 'kjs' ? 'kubejs/' : (type === 'wf' ? selectedWfWorld + '/' : 'config/');
  document.getElementById('modal-path').textContent = pathPrefix + path;
  document.getElementById('config-editor').value = 'Cargando…';
  cfgParsed = null;
  cfgRawText = '';
  editorBaseline = null;
  var isKjsFile = type === 'kjs';
  document.getElementById('modal-kjs-delete-btn').style.display = isKjsFile ? '' : 'none';
  document.getElementById('modal-kjs-move-btn').style.display = isKjsFile ? '' : 'none';
  document.getElementById('kjs-move-form').style.display = 'none';

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
  var endpoint = type === 'kjs' ? '/kubejs-file' : (type === 'wf' ? '/world-file' : '/config-file');
  var extraQuery = type === 'wf' ? '&world_name=' + encodeURIComponent(selectedWfWorld) : '';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + endpoint + '?path=' + encodeURIComponent(path) + extraQuery)
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
      // Lo que se compara para saber si hay cambios: el texto tal cual lo
      // generaría ahora el editor, no el del disco (el formulario normaliza
      // espacios y daría «cambios» sin haber tocado nada).
      editorBaseline = currentEditorText();
      syncLines();
    })
    .catch(function() {
      document.getElementById('config-editor').value = '# Error al cargar';
      syncLines();
    });
}


// -- Modal editor -------------------------------------------------------------
// Texto del archivo tal y como se cargó o se guardó por última vez (null
// mientras carga): si el editor tiene otra cosa, hay cambios sin guardar.
var editorBaseline = null;

function currentEditorText() {
  if (cfgParsed && cfgFormMode === 'form') {
    return formToRawText();
  }
  return document.getElementById('config-editor').value;
}

function editorIsOpen() {
  return document.getElementById('editor-modal').classList.contains('show');
}

registerUnsaved('editor', 'el archivo abierto en el editor',
  function() { return editorIsOpen() && editorBaseline !== null && currentEditorText() !== editorBaseline; },
  function() { editorBaseline = null; });

// force: cerrar sin preguntar (p.ej. el archivo se acaba de borrar).
function closeModal(force) {
  var close = function() {
    editorBaseline = null;
    document.getElementById('editor-modal').classList.remove('show');
  };
  if (force === true) {
    close();
  } else {
    confirmLeave(close, ['editor']);
  }
}

document.getElementById('modal-close-btn').addEventListener('click', function() { closeModal(); });
document.getElementById('modal-close-btn2').addEventListener('click', function() { closeModal(); });
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
  var textToSave = currentEditorText();
  var form = new FormData();
  form.append('path', path);
  form.append('content', textToSave);
  if (type === 'wf') {
    form.append('world_name', selectedWfWorld);
  }
  var endpoint = type === 'kjs' ? '/kubejs-file' : (type === 'wf' ? '/world-file' : '/config-file');
  busyWhile(document.getElementById('modal-save-btn'), function() {
    return apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + endpoint, {
      method: 'POST',
      body: form
    })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (data.success) {
          cfgRawText = textToSave;
          editorBaseline = currentEditorText();
          showToast('Archivo guardado', 'success');
        flashDone(document.getElementById('modal-save-btn'));
        } else {
          showToast(data.detail || 'No se pudo guardar el archivo', 'error');
        }
      })
      .catch(function() { showToast('No se pudo guardar el archivo', 'error'); });
  });
});

// Ctrl+S (o Cmd+S) guarda el archivo abierto, como en cualquier editor.
document.addEventListener('keydown', function(event) {
  if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 's' && editorIsOpen()
      && topModal() === document.getElementById('editor-modal')) {
    event.preventDefault();
    document.getElementById('modal-save-btn').click();
  }
});

var ta = document.getElementById('config-editor');
var ln = document.getElementById('line-numbers');
enableCodeEditorTab(ta);
enableCodeEditorTab(document.getElementById('props-raw-editor'));

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
