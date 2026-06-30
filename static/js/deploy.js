// -- Disco --------------------------------------------------------------------
apiFetch('/api/disk-usage')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) {
      document.getElementById('disk-text').textContent = 'Error';
      return;
    }
    var f = document.getElementById('disk-fill');
    f.style.width = d.percent_used + '%';
    if (d.percent_used > 90) {
      f.classList.add('danger');
    } else if (d.percent_used > 70) {
      f.classList.add('warn');
    }
    document.getElementById('disk-text').textContent =
      d.free_gb + ' GB libres de ' + d.total_gb + ' GB (' + d.percent_used + '% usado)';
  })
  .catch(function() {
    document.getElementById('disk-text').textContent = 'No disponible';
  });


// -- RAM ----------------------------------------------------------------------
var maxAllowedGb = null;

apiFetch('/api/system-info')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    maxAllowedGb = d.ram_max_allowed_gb;
    document.getElementById('ram-info').textContent = d.ram_total_gb
      ? 'RAM: ' + d.ram_total_gb + ' GB (máx. recomendado: ' + d.ram_max_allowed_gb + ' GB)'
      : '';
  })
  .catch(function() {
    document.getElementById('ram-info').textContent = '';
  });

function checkRam() {
  if (!maxAllowedGb) return;
  var maxVal = parseFloat(document.getElementById('ram-max-val').value) || 0;
  var maxUnit = document.getElementById('ram-max-unit').value;
  var minVal = parseFloat(document.getElementById('ram-min-val').value) || 0;
  var minUnit = document.getElementById('ram-min-unit').value;
  var maxGb = maxUnit === 'G' ? maxVal : maxVal / 1024;
  var minGb = minUnit === 'G' ? minVal : minVal / 1024;
  var w = document.getElementById('ram-warn');
  var msgs = [];
  if (maxGb > maxAllowedGb) {
    msgs.push('La RAM máxima supera el 80% del sistema (' + maxAllowedGb + ' GB recomendado)');
  }
  if (minGb > maxGb) {
    msgs.push('La RAM mínima no puede ser mayor que la máxima');
  }
  w.textContent = msgs.join(' · ');
  w.style.display = msgs.length ? 'block' : 'none';
}

['ram-min-val', 'ram-max-val', 'ram-min-unit', 'ram-max-unit'].forEach(function(id) {
  document.getElementById(id).addEventListener('input', checkRam);
  document.getElementById(id).addEventListener('change', checkRam);
});

var ramEnabled = false;

document.getElementById('ram-toggle').addEventListener('click', function() {
  ramEnabled = !ramEnabled;
  this.classList.toggle('on', ramEnabled);
  document.getElementById('ram-inputs').style.display = ramEnabled ? 'block' : 'none';
});


// -- Archivo ------------------------------------------------------------------
var selectedFile = null;
var fileInput = document.getElementById('file-input');
var dropZone = document.getElementById('drop-zone');

fileInput.addEventListener('change', function() {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

dropZone.addEventListener('dragover', function(e) {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', function() {
  dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', function(e) {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});

function setFile(f) {
  selectedFile = f;
  document.getElementById('fb-name').textContent = f.name;
  document.getElementById('fb-size').textContent = fmtSize(f.size);
  document.getElementById('file-badge').classList.add('show');
  resetDeploy();
}

document.getElementById('fb-clear').addEventListener('click', function() {
  selectedFile = null;
  fileInput.value = '';
  document.getElementById('file-badge').classList.remove('show');
  resetDeploy();
});

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(1) + ' MB';
}


// -- Deploy -------------------------------------------------------------------
document.getElementById('deploy-btn').addEventListener('click', function() {
  if (!selectedFile) {
    showAlert('Selecciona un archivo primero');
    return;
  }
  var fn = document.getElementById('folder-name').value.trim();
  if (!fn) {
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

  var prog = 0;
  var timer = setInterval(function() {
    if (prog < 85) {
      prog += Math.random() * 8;
      fill.style.width = Math.min(prog, 85) + '%';
      status.textContent = prog < 40
        ? 'Subiendo ' + selectedFile.name + '...'
        : 'Descomprimiendo...';
    }
  }, 300);

  var form = new FormData();
  form.append('file', selectedFile);
  form.append('folder_name', fn);
  form.append('configure_ram', ramEnabled ? '1' : '0');
  if (ramEnabled) {
    form.append('ram_min',
      document.getElementById('ram-min-val').value + document.getElementById('ram-min-unit').value);
    form.append('ram_max',
      document.getElementById('ram-max-val').value + document.getElementById('ram-max-unit').value);
  }

  apiFetch('/api/upload-and-extract', { method: 'POST', body: form })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      fill.style.width = '100%';
      if (res.ok && res.d.success) {
        fill.classList.add('done');
        status.textContent = '✅ Completado';
        var items = [
          ['Archivo', res.d.filename],
          ['Tamaño', res.d.size_mb + ' MB'],
          ['Formato', res.d.format],
          ['Archivos', res.d.files_extracted === -1 ? '—' : res.d.files_extracted],
          ['Destino', res.d.destination]
        ];
        if (res.d.jvm_configured) items.push(['RAM', res.d.jvm_configured]);
        showResult('success', '¡Listo!', 'Modpack instalado correctamente', items);
      } else {
        fill.classList.add('error');
        status.textContent = '❌ Error';
        showResult('error', 'Error', res.d.detail || 'Error desconocido', []);
      }
    })
    .catch(function(e) {
      status.textContent = '❌ Error';
      showResult('error', 'Error de red', e.message, []);
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
  var g = '';
  items.forEach(function(i) {
    g += '<div class="result-item">' + i[0] + ': <span>' + i[1] + '</span></div>';
  });
  document.getElementById('result-grid').innerHTML = g;
}

function resetDeploy() {
  document.getElementById('progress-section').classList.remove('show');
  var f = document.getElementById('progress-fill');
  f.style.width = '0%';
  f.className = 'progress-fill';
  document.getElementById('result-box').className = 'result-box';
}
