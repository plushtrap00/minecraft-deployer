// -- Mods list ---------------------------------------------------------------
var allMods = [];

var currentModpackVersion = {};

function loadModpackVersion() {
  if (!currentModpack) return;
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/version')
    .then(function(r){ return r.json(); })
    .then(function(d){
      currentModpackVersion = d;
      var badge = document.getElementById('modpack-version-badge');
      if (!badge) return;
      if (d.mc_version || d.modloader) {
        var ml = d.modloader || 'Unknown';
        var mlClass = ml.toLowerCase().replace('/', '-').split(' ')[0];
        badge.innerHTML = '<span class="version-badge '+mlClass+'">'
          + (d.mc_version ? 'MC '+d.mc_version : '')
          + (d.mc_version && d.modloader ? ' · ' : '')
          + (d.modloader ? d.modloader : '')
          + (d.modloader_version ? ' '+d.modloader_version : '')
          + '</span>';
      } else {
        badge.style.display = 'none';
      }
    }).catch(function(){});
}

function loadModsList() {
  if (!currentModpack) return;
  var list = document.getElementById('mods-list');
  if (!list) return;
  list.innerHTML = '<p class="empty-msg">Cargando...</p>';
  document.getElementById('mods-count').textContent = '';
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/mods')
    .then(function(r){ return r.json(); })
    .then(function(d){
      allMods = d.mods || [];
      if (!d.exists) {
        list.innerHTML = '<p class="empty-msg">No se encontró carpeta <code>mods/</code> en este modpack.</p>';
        return;
      }
      renderModsList(allMods);
    })
    .catch(function(){ list.innerHTML = '<p class="empty-msg" style="color:var(--red)">Error al cargar mods</p>'; });
}

function renderModsList(mods) {
  var list = document.getElementById('mods-list');
  var count = document.getElementById('mods-count');
  if (!list) return;
  if (count) count.textContent = mods.length + ' / ' + allMods.length + ' mods';
  if (!mods.length) {
    list.innerHTML = '<p class="empty-msg" style="padding:16px">Sin resultados</p>';
    return;
  }
  var html = '<div class="mods-table-wrap">';
  mods.forEach(function(m) {
    var icon = m.enabled ? '🧩' : '⬜';
    var style = m.enabled ? '' : ' style="opacity:.45"';
    html += '<div class="mod-list-item"'+style+'>'
      + '<span class="mod-icon">'+icon+'</span>'
      + '<div class="mod-info"><div class="mod-display">' + escHtml(m.name) + '</div></div>'
      + (m.enabled ? '' : '<span style="font-size:.72rem;color:var(--muted)">desactivado</span>')
      + '</div>';
  });
  html += '</div>';
  list.innerHTML = html;
}

document.getElementById('mods-search').addEventListener('input', function() {
  var q = this.value.toLowerCase().trim();
  if (!q) { renderModsList(allMods); return; }
  var filtered = allMods.filter(function(m) {
    return m.name.toLowerCase().indexOf(q) !== -1;
  });
  renderModsList(filtered);
});

// -- Mod upload ---------------------------------------------------------------
var modUploadZone = document.getElementById('mod-upload-zone');
var modFileInput = document.getElementById('mod-file-input');

modUploadZone.addEventListener('dragover', function(e){ e.preventDefault(); this.classList.add('drag-over'); });
modUploadZone.addEventListener('dragleave', function(){ this.classList.remove('drag-over'); });
modUploadZone.addEventListener('drop', function(e){
  e.preventDefault(); this.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) uploadMod(e.dataTransfer.files[0]);
});
modFileInput.addEventListener('change', function(){
  if (this.files[0]) uploadMod(this.files[0]);
});

function uploadMod(file) {
  if (!file.name.toLowerCase().endsWith('.jar')) {
    showAlert('Solo se aceptan archivos .jar');
    return;
  }
  var resultEl = document.getElementById('mod-upload-result');
  resultEl.style.display = 'block';
  resultEl.innerHTML = '<div style="color:var(--muted);font-size:.83rem">Subiendo y verificando '+escHtml(file.name)+'...</div>';

  var form = new FormData();
  form.append('file', file);
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/mods/upload', {method:'POST', body:form})
    .then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
    .then(function(res){
      modFileInput.value = '';
      if (res.ok && res.d.success) {
        var info = '';
        if (res.d.mod_id) info += ' · ID: '+escHtml(res.d.mod_id);
        if (res.d.mod_version) info += ' · v'+escHtml(res.d.mod_version);
        if (res.d.size_kb) info += ' · '+res.d.size_kb+' KB';
        resultEl.innerHTML = '<div style="background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--green)">✅ Mod instalado: '+escHtml(res.d.filename)+info+'</div>';
        loadModsList();
        setTimeout(function(){ resultEl.style.display='none'; }, 4000);
      } else {
        resultEl.innerHTML = '<div style="background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3);border-radius:6px;padding:8px 12px;font-size:.82rem;color:var(--red)">❌ '+escHtml(res.d.detail||'Error desconocido')+'</div>';
      }
    })
    .catch(function(e){
      modFileInput.value = '';
      resultEl.innerHTML = '<div style="color:var(--red);font-size:.82rem">❌ Error de red: '+escHtml(e.message)+'</div>';
    });
}
