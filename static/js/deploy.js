// -- Disco y RAM del sistema -------------------------------------------------
// Se piden al entrar en la página (ver main.js), no al cargar el script:
// antes de iniciar sesión la petición daba 401 y la barra se quedaba vacía.
var maxAllowedGb = null;

function loadDeployPageData() {
  apiFetch('/api/disk-usage')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.error) {
        document.getElementById('disk-text').textContent = 'No disponible';
        return;
      }
      var fillBar = document.getElementById('disk-fill');
      fillBar.style.width = data.percent_used + '%';
      fillBar.classList.toggle('danger', data.percent_used > 90);
      fillBar.classList.toggle('warn', data.percent_used > 70 && data.percent_used <= 90);
      document.getElementById('disk-text').textContent =
        data.free_gb + ' GB libres de ' + data.total_gb + ' GB (' + data.percent_used + '% usado)';
    })
    .catch(function() {
      document.getElementById('disk-text').textContent = 'No disponible';
    });

  apiFetch('/api/system-info')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      maxAllowedGb = data.ram_max_allowed_gb;
      document.getElementById('ram-info').textContent = data.ram_total_gb
        ? 'RAM: ' + data.ram_total_gb + ' GB (máx. recomendado: ' + data.ram_max_allowed_gb + ' GB)'
        : '';
      RAM_FIELD_PREFIXES.forEach(checkRamFields);
    })
    .catch(function() {
      document.getElementById('ram-info').textContent = '';
    });
}


// -- Campos de RAM (los tres modos: subir, crear y descargar) ----------------
// Mismo bloque HTML (partials/ram-fields.html) con un prefijo en los ids.
var RAM_FIELD_PREFIXES = ['', 'create-', 'dl-'];

function ramFieldGb(prefix, which) {
  var value = parseFloat(document.getElementById(prefix + 'ram-' + which + '-val').value) || 0;
  return document.getElementById(prefix + 'ram-' + which + '-unit').value === 'G' ? value : value / 1024;
}

function ramFieldValue(prefix, which) {
  return document.getElementById(prefix + 'ram-' + which + '-val').value
    + document.getElementById(prefix + 'ram-' + which + '-unit').value;
}

// Texto del problema que bloquea la instalación, o '' si los valores valen.
function ramFieldsError(prefix) {
  var minGb = ramFieldGb(prefix, 'min');
  var maxGb = ramFieldGb(prefix, 'max');
  if (minGb <= 0 || maxGb <= 0) {
    return 'Indica la RAM mínima y la máxima';
  }
  if (minGb > maxGb) {
    return 'La RAM mínima no puede ser mayor que la máxima';
  }
  return '';
}

function checkRamFields(prefix) {
  var msgs = [];
  var error = ramFieldsError(prefix);
  if (error) {
    msgs.push(error);
  }
  if (maxAllowedGb && ramFieldGb(prefix, 'max') > maxAllowedGb) {
    msgs.push('La RAM máxima supera el 80% del sistema (' + maxAllowedGb + ' GB recomendado)');
  }
  var warningEl = document.getElementById(prefix + 'ram-warn');
  warningEl.textContent = msgs.join(' · ');
  warningEl.style.display = msgs.length ? 'block' : 'none';
}

RAM_FIELD_PREFIXES.forEach(function(prefix) {
  ['ram-min-val', 'ram-max-val', 'ram-min-unit', 'ram-max-unit'].forEach(function(id) {
    var el = document.getElementById(prefix + id);
    el.addEventListener('input', function() { checkRamFields(prefix); });
    el.addEventListener('change', function() { checkRamFields(prefix); });
  });
});

var ramEnabled = false;

document.getElementById('ram-toggle').addEventListener('click', function() {
  ramEnabled = !ramEnabled;
  this.classList.toggle('on', ramEnabled);
  if (ramEnabled) {
    document.getElementById('ram-inputs').style.display = 'block';
  } else {
    document.getElementById('ram-inputs').style.display = 'none';
  }
});


// -- Archivo ------------------------------------------------------------------
var selectedFile = null;
var fileInput = document.getElementById('file-input');
var dropZone = document.getElementById('drop-zone');

fileInput.addEventListener('change', function() {
  if (fileInput.files[0]) {
    setFile(fileInput.files[0]);
  }
});

dropZone.addEventListener('dragover', function(event) {
  event.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', function() {
  dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', function(event) {
  event.preventDefault();
  dropZone.classList.remove('drag-over');
  if (event.dataTransfer.files[0]) {
    setFile(event.dataTransfer.files[0]);
  }
});

function setFile(file) {
  selectedFile = file;
  document.getElementById('fb-name').textContent = file.name;
  document.getElementById('fb-size').textContent = fmtSize(file.size);
  document.getElementById('file-badge').classList.add('show');
  resetDeploy();
}

document.getElementById('fb-clear').addEventListener('click', function() {
  selectedFile = null;
  fileInput.value = '';
  document.getElementById('file-badge').classList.remove('show');
  resetDeploy();
});

function fmtSize(bytes) {
  if (bytes < 1024) {
    return bytes + ' B';
  }
  if (bytes < 1048576) {
    return (bytes / 1024).toFixed(1) + ' KB';
  }
  if (bytes < 1073741824) {
    return (bytes / 1048576).toFixed(1) + ' MB';
  }
  return (bytes / 1073741824).toFixed(2) + ' GB';
}


// -- Deploy -------------------------------------------------------------------
document.getElementById('deploy-btn').addEventListener('click', function() {
  if (!selectedFile) {
    showAlert('Elige primero el archivo del modpack.');
    return;
  }
  var folderName = document.getElementById('folder-name').value.trim();
  if (!folderName) {
    showAlert('Escribe un nombre para el servidor.');
    return;
  }
  if (ramEnabled && ramFieldsError('')) {
    showAlert(ramFieldsError('') + '.');
    return;
  }
  var btn = document.getElementById('deploy-btn');
  btn.disabled = true;
  resetDeploy();

  var section = document.getElementById('progress-section');
  var fill = document.getElementById('progress-fill');
  var status = document.getElementById('progress-status');
  section.classList.add('show');

  var progress = 0;
  var timer = setInterval(function() {
    if (progress < 85) {
      progress += Math.random() * 8;
      fill.style.width = Math.min(progress, 85) + '%';
      if (progress < 40) {
        status.textContent = 'Subiendo ' + selectedFile.name + '...';
      } else {
        status.textContent = 'Descomprimiendo...';
      }
    }
  }, 300);

  var form = new FormData();
  form.append('file', selectedFile);
  form.append('folder_name', folderName);
  form.append('configure_ram', ramEnabled ? '1' : '0');
  if (ramEnabled) {
    form.append('ram_min', ramFieldValue('', 'min'));
    form.append('ram_max', ramFieldValue('', 'max'));
  }

  apiFetch('/api/upload-and-extract', { method: 'POST', body: form })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      fill.style.width = '100%';
      if (result.ok && result.data.success) {
        fill.classList.add('done');
        status.textContent = 'Completado';
        var extractedCount = result.data.files_extracted === -1 ? '—' : result.data.files_extracted;
        var items = [
          ['Archivo', result.data.filename],
          ['Tamaño', result.data.size_mb + ' MB'],
          ['Formato', result.data.format],
          ['Archivos', extractedCount],
          ['Destino', result.data.destination]
        ];
        if (result.data.jvm_configured) {
          items.push(['RAM', result.data.jvm_configured]);
        }
        showResult('success', '¡Listo!', 'Modpack instalado correctamente', items);
        celebrate(document.getElementById('progress-fill'));
        unlockAchievement('first-install');
      } else {
        fill.classList.add('error');
        status.textContent = 'Error';
        showResult('error', 'Error', result.data.detail || 'Error desconocido', []);
      }
    })
    .catch(function(error) {
      status.textContent = 'Error';
      showResult('error', 'No se pudo conectar con el panel', error.message, []);
    })
    .finally(function() {
      clearInterval(timer);
      btn.disabled = false;
    });
});

function showResult(type, title, msg, items) {
  var box = document.getElementById('result-box');
  box.className = 'result-box show ' + type;
  document.getElementById('result-title').textContent = title;
  document.getElementById('result-msg').textContent = msg;
  var gridHtml = '';
  items.forEach(function(item) {
    gridHtml += '<div class="result-item">' + escHtml(item[0]) + ': <span>' + escHtml(item[1]) + '</span></div>';
  });
  document.getElementById('result-grid').innerHTML = gridHtml;
}

function resetDeploy() {
  document.getElementById('progress-section').classList.remove('show');
  var fillBar = document.getElementById('progress-fill');
  fillBar.style.width = '0%';
  fillBar.className = 'progress-fill';
  document.getElementById('result-box').className = 'result-box';
}
