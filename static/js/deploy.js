// -- Disco --------------------------------------------------------------------
apiFetch('/api/disk-usage')
  .then(function(response) { return response.json(); })
  .then(function(data) {
    if (data.error) {
      document.getElementById('disk-text').textContent = 'Error';
      return;
    }
    var fillBar = document.getElementById('disk-fill');
    fillBar.style.width = data.percent_used + '%';
    if (data.percent_used > 90) {
      fillBar.classList.add('danger');
    } else if (data.percent_used > 70) {
      fillBar.classList.add('warn');
    }
    document.getElementById('disk-text').textContent =
      data.free_gb + ' GB libres de ' + data.total_gb + ' GB (' + data.percent_used + '% usado)';
  })
  .catch(function() {
    document.getElementById('disk-text').textContent = 'No disponible';
  });


// -- RAM ----------------------------------------------------------------------
var maxAllowedGb = null;

apiFetch('/api/system-info')
  .then(function(response) { return response.json(); })
  .then(function(data) {
    maxAllowedGb = data.ram_max_allowed_gb;
    if (data.ram_total_gb) {
      document.getElementById('ram-info').textContent =
        'RAM: ' + data.ram_total_gb + ' GB (máx. recomendado: ' + data.ram_max_allowed_gb + ' GB)';
    } else {
      document.getElementById('ram-info').textContent = '';
    }
  })
  .catch(function() {
    document.getElementById('ram-info').textContent = '';
  });

function checkRam() {
  if (!maxAllowedGb) {
    return;
  }
  var maxVal = parseFloat(document.getElementById('ram-max-val').value) || 0;
  var maxUnit = document.getElementById('ram-max-unit').value;
  var minVal = parseFloat(document.getElementById('ram-min-val').value) || 0;
  var minUnit = document.getElementById('ram-min-unit').value;
  var maxGb = maxUnit === 'G' ? maxVal : maxVal / 1024;
  var minGb = minUnit === 'G' ? minVal : minVal / 1024;
  var warningEl = document.getElementById('ram-warn');
  var msgs = [];
  if (maxGb > maxAllowedGb) {
    msgs.push('La RAM máxima supera el 80% del sistema (' + maxAllowedGb + ' GB recomendado)');
  }
  if (minGb > maxGb) {
    msgs.push('La RAM mínima no puede ser mayor que la máxima');
  }
  warningEl.textContent = msgs.join(' · ');
  if (msgs.length) {
    warningEl.style.display = 'block';
  } else {
    warningEl.style.display = 'none';
  }
}

['ram-min-val', 'ram-max-val', 'ram-min-unit', 'ram-max-unit'].forEach(function(id) {
  document.getElementById(id).addEventListener('input', checkRam);
  document.getElementById(id).addEventListener('change', checkRam);
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
  return (bytes / 1048576).toFixed(1) + ' MB';
}


// -- Deploy -------------------------------------------------------------------
document.getElementById('deploy-btn').addEventListener('click', function() {
  if (!selectedFile) {
    showAlert('Selecciona un archivo primero');
    return;
  }
  var folderName = document.getElementById('folder-name').value.trim();
  if (!folderName) {
    showAlert('Escribe el nombre de carpeta del modpack');
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
    form.append('ram_min',
      document.getElementById('ram-min-val').value + document.getElementById('ram-min-unit').value);
    form.append('ram_max',
      document.getElementById('ram-max-val').value + document.getElementById('ram-max-unit').value);
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
        status.textContent = '✅ Completado';
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
      } else {
        fill.classList.add('error');
        status.textContent = '❌ Error';
        showResult('error', 'Error', result.data.detail || 'Error desconocido', []);
      }
    })
    .catch(function(error) {
      status.textContent = '❌ Error';
      showResult('error', 'Error de red', error.message, []);
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
    gridHtml += '<div class="result-item">' + item[0] + ': <span>' + item[1] + '</span></div>';
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
