// ── Monitor de sistema ────────────────────────────────────────────────────────
var sysmonOpen = false;
var sysmonTimer = null;

document.getElementById('btn-logout').addEventListener('click', function() {
  if (confirm('¿Cerrar sesión?')) logout();
});

document.getElementById('btn-sysmon').addEventListener('click', function() {
  sysmonOpen = !sysmonOpen;
  var panel = document.getElementById('sysmon-panel');
  if (sysmonOpen) {
    panel.classList.add('open');
    this.classList.add('active');
    fetchSysmon();
    if (!sysmonTimer) sysmonTimer = setInterval(fetchSysmon, 3000);
  } else {
    panel.classList.remove('open');
    this.classList.remove('active');
    if (sysmonTimer) { clearInterval(sysmonTimer); sysmonTimer = null; }
  }
});

document.getElementById('sysmon-close-btn').addEventListener('click', function() {
  sysmonOpen = false;
  document.getElementById('sysmon-panel').classList.remove('open');
  document.getElementById('btn-sysmon').classList.remove('active');
  if (sysmonTimer) { clearInterval(sysmonTimer); sysmonTimer = null; }
});

document.getElementById('sysmon-refresh-btn').addEventListener('click', fetchSysmon);

function fetchSysmon() {
  apiFetch('/api/system-stats')
    .then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
    .then(function(res){
      if (!res.ok || !res.d || !res.d.cpu) {
        var msg = (res.d && res.d.detail) ? res.d.detail : 'Respuesta inesperada del servidor';
        document.getElementById('sysmon-body').innerHTML = '<p style="color:var(--red);font-size:.82rem">Error: '+escHtml(msg)+'</p>';
        return;
      }
      renderSysmon(res.d);
    })
    .catch(function(e){ document.getElementById('sysmon-body').innerHTML = '<p style="color:var(--red);font-size:.82rem">Error de red: '+escHtml(e.message)+'</p>'; });
}

function sysColor(pct) { return pct < 60 ? 'ok' : pct < 85 ? 'warn' : 'bad'; }

function sysBar(label, pct, valLabel) {
  var cls = sysColor(pct);
  return '<div class="sysmon-bar-row">'
    + '<span class="sysmon-bar-label" title="'+escHtml(label)+'">'+escHtml(label)+'</span>'
    + '<div class="sysmon-bar-wrap"><div class="sysmon-bar-fill '+cls+'" style="width:'+Math.min(pct,100)+'%"></div></div>'
    + '<span class="sysmon-bar-val">'+escHtml(valLabel)+'</span>'
    + '</div>';
}

function renderSysmon(d) {
  var now = new Date();
  document.getElementById('sysmon-updated').textContent =
    now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0')+':'+now.getSeconds().toString().padStart(2,'0');

  var html = '';

  // CPU (solo global)
  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">⚙️ CPU</div>';
  html += sysBar('CPU', d.cpu.total_percent, d.cpu.total_percent.toFixed(0)+'%');
  html += '</div>';

  // RAM (solo usada)
  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">🧠 RAM</div>';
  html += sysBar('RAM', d.ram.percent, d.ram.used_gb.toFixed(1)+' / '+d.ram.total_gb.toFixed(1)+' GB');
  html += '</div>';

  // Temperaturas (media CPU + GPU)
  html += '<div class="sysmon-section">';
  html += '<div class="sysmon-section-title">🌡️ Temperatura</div>';
  var cpuTemps = [], gpuTemps = [];
  if (d.temps) {
    Object.keys(d.temps).forEach(function(chip) {
      var entries = d.temps[chip] || [];
      var chipLow = chip.toLowerCase();
      var isCpu = chipLow.includes('cpu') || chipLow.includes('core') || chipLow.includes('k10') || chipLow.includes('coretemp') || chipLow.includes('acpi') || chipLow.includes('pch');
      var isGpu = chipLow.includes('gpu') || chipLow.includes('amdgpu') || chipLow.includes('radeon') || chipLow.includes('nouveau') || chipLow.includes('nvidia');
      entries.forEach(function(t) {
        if (isGpu) gpuTemps.push(t.current);
        else if (isCpu) cpuTemps.push(t.current);
        else cpuTemps.push(t.current); // fallback: contar como CPU
      });
    });
  }
  var hasAny = cpuTemps.length || gpuTemps.length;
  if (hasAny) {
    if (cpuTemps.length) {
      var avgCpu = cpuTemps.reduce(function(a,b){return a+b;},0) / cpuTemps.length;
      html += sysBar('CPU', avgCpu, avgCpu.toFixed(1)+'°C');
    }
    if (gpuTemps.length) {
      var avgGpu = gpuTemps.reduce(function(a,b){return a+b;},0) / gpuTemps.length;
      html += sysBar('GPU', avgGpu, avgGpu.toFixed(1)+'°C');
    }
  } else {
    html += '<span class="sysmon-no-temps">Sin sensores detectados. '
      + 'Instala: <code>sudo apt install lm-sensors && sudo sensors-detect --auto</code></span>';
  }
  html += '</div>';

  document.getElementById('sysmon-body').innerHTML = html;
}
