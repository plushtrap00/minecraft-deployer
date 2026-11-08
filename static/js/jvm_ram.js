// -- RAM de la JVM --------------------------------------------------------------
// Reusa el mismo patrón visual (número + unidad G/M) que ya usan las páginas
// de crear servidor / instalar modpack / importar modpack, y el mismo aviso
// "supera el 80% de la RAM del sistema" (maxAllowedGb, global ya poblado por
// deploy.js desde /api/system-info en cuanto carga la página).
function parseRamValue(raw) {
  var m = /^(\d+)([MG])$/i.exec(raw || '');
  return m ? { val: m[1], unit: m[2].toUpperCase() } : { val: '4', unit: 'G' };
}

function loadRamConfig() {
  if (!currentModpack) {
    return;
  }
  var body = document.getElementById('ram-cfg-body');
  body.innerHTML = '<p class="empty-msg">Detectando configuración de RAM...</p>';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/ram')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderRamConfig(data); })
    .catch(function() {
      body.innerHTML = '<p class="empty-msg text-red">Error al detectar la configuración de RAM</p>';
    });
}

function renderRamConfig(data) {
  var body = document.getElementById('ram-cfg-body');
  if (!data.source) {
    body.innerHTML = '<div class="warn-box">No se pudo detectar dónde configura este modpack la RAM '
      + '(no tiene <code>user_jvm_args.txt</code>, <code>variables.txt</code>, ni <code>-Xms</code>/<code>-Xmx</code> '
      + 'en su script de arranque). Puede que use un lanzador propio — edítala a mano en la carpeta del servidor.</div>';
    return;
  }
  // Sin RAM todavía (plantilla del instalador con todo comentado): se
  // proponen 4 GB / 8 GB, lo normal para un modpack.
  var min = parseRamValue(data.unset ? '4G' : data.ram_min);
  var max = parseRamValue(data.unset ? '8G' : data.ram_max);
  var where = data.unset
    ? noticeHtml('warn', '<code>' + escHtml(data.source) + '</code> no tiene la RAM puesta (sus líneas están comentadas), así que '
      + 'Java usa lo que decide por defecto: una cuarta parte de la RAM del equipo. Elige cuánta darle y guarda.')
    : '<p class="hint mb-m">Detectado en <code>' + escHtml(data.source) + '</code>.</p>';
  body.innerHTML =
    where
    + '<div class="ram-grid">'
    + '<div><label class="field-label">RAM mínima <span class="text-accent">(-Xms)</span></label>'
    + '<div class="input-row"><input type="number" id="ram-cfg-min-val" value="' + escHtml(min.val) + '" min="1">'
    + '<select id="ram-cfg-min-unit"><option value="G"' + (min.unit === 'G' ? ' selected' : '') + '>GB</option>'
    + '<option value="M"' + (min.unit === 'M' ? ' selected' : '') + '>MB</option></select></div></div>'
    + '<div><label class="field-label">RAM máxima <span class="text-accent">(-Xmx)</span></label>'
    + '<div class="input-row"><input type="number" id="ram-cfg-max-val" value="' + escHtml(max.val) + '" min="1">'
    + '<select id="ram-cfg-max-unit"><option value="G"' + (max.unit === 'G' ? ' selected' : '') + '>GB</option>'
    + '<option value="M"' + (max.unit === 'M' ? ' selected' : '') + '>MB</option></select></div></div>'
    + '</div>'
    + '<p id="ram-cfg-warn" class="ram-warn" style="display:none"></p>'
    + '<button id="ram-cfg-save-btn" class="add-user-btn mt-m">Guardar RAM</button>';

  ['ram-cfg-min-val', 'ram-cfg-max-val', 'ram-cfg-min-unit', 'ram-cfg-max-unit'].forEach(function(id) {
    document.getElementById(id).addEventListener('input', checkRamCfg);
    document.getElementById(id).addEventListener('change', checkRamCfg);
  });
  checkRamCfg();
  document.getElementById('ram-cfg-save-btn').addEventListener('click', saveRamConfig);
}

function checkRamCfg() {
  var warningEl = document.getElementById('ram-cfg-warn');
  if (!warningEl) {
    return;
  }
  var maxVal = parseFloat(document.getElementById('ram-cfg-max-val').value) || 0;
  var maxUnit = document.getElementById('ram-cfg-max-unit').value;
  var minVal = parseFloat(document.getElementById('ram-cfg-min-val').value) || 0;
  var minUnit = document.getElementById('ram-cfg-min-unit').value;
  var maxGb = maxUnit === 'G' ? maxVal : maxVal / 1024;
  var minGb = minUnit === 'G' ? minVal : minVal / 1024;
  var msgs = [];
  if (typeof maxAllowedGb !== 'undefined' && maxAllowedGb && maxGb > maxAllowedGb) {
    msgs.push('La RAM máxima supera el 80% del sistema (' + maxAllowedGb + ' GB recomendado)');
  }
  if (minGb > maxGb) {
    msgs.push('La RAM mínima no puede ser mayor que la máxima');
  }
  warningEl.textContent = msgs.join(' · ');
  warningEl.style.display = msgs.length ? 'block' : 'none';
}

function saveRamConfig() {
  var btn = document.getElementById('ram-cfg-save-btn');
  var ramMin = document.getElementById('ram-cfg-min-val').value + document.getElementById('ram-cfg-min-unit').value;
  var ramMax = document.getElementById('ram-cfg-max-val').value + document.getElementById('ram-cfg-max-unit').value;

  btn.disabled = true;
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/ram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ram_min: ramMin, ram_max: ramMax })
  })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      btn.disabled = false;
      if (result.ok) {
        showToast('RAM guardada en ' + result.data.source + ' — reinicia el servidor para aplicarla', 'success');
        // Vuelve a leerla: si el archivo no tenía RAM, deja de salir el aviso.
        loadRamConfig();
      } else {
        showToast(result.data.detail || 'Error al guardar', 'error');
      }
    })
    .catch(function() {
      btn.disabled = false;
      showToast('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.', 'error');
    });
}
