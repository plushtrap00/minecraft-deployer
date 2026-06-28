//  Mundos
function loadWorlds(){
  var list=document.getElementById('worlds-list'); if(!list) return;
  list.innerHTML='<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/worlds')
    .then(function(r){ return r.json(); }).then(function(d){ renderWorlds(d); })
    .catch(function(){ list.innerHTML='<p class="empty-msg" style="color:var(--red)">Error al cargar mundos</p>'; });
}
function renderWorlds(d){
  var list=document.getElementById('worlds-list');
  var worlds=d.worlds;
  if (!worlds||!worlds.length){
    list.innerHTML='<p class="empty-msg">No se detectaron mundos generados aún.</p>'
      +'<p class="hint" style="margin-top:6px">Mundo configurado: <code>'+(d.active||'world')+'</code>'
      +' · Tipo: <code>'+(d.level_type||'minecraft:normal')+'</code></p>';
    return;
  }
  var html='';
  worlds.forEach(function(w){
    var activeBadge=w.active
      ? '<span style="font-size:.72rem;background:rgba(63,185,80,.15);color:var(--green);padding:2px 8px;border-radius:99px;font-weight:600">✓ Activo</span>'
      : '';
    var activateBtn=!w.active
      ? '<button class="btn-secondary wc-activate" data-world="'+w.name+'" style="font-size:.78rem;padding:5px 10px">Activar</button>'
      : '';
    var deleteBtn=!w.active
      ? '<button class="btn-danger wc-delete" data-world="'+w.name+'" style="font-size:.78rem;padding:5px 10px">🗑 Borrar</button>'
      : '';
    html+='<div class="world-card'+(w.active?' active-world':'')+'"><span style="font-size:1.5rem">'
      +(w.active?'🟢':'🌍')+'</span><div style="flex:1"><div style="font-weight:600">'
      +w.name+' '+activeBadge+'</div><div style="font-size:.78rem;color:var(--muted)">'
      +w.size_mb+' MB en disco</div></div>'
      +'<div class="wc-actions">'+activateBtn+deleteBtn+'</div></div>';
  });
  html+='<p class="hint" style="margin-top:8px">Tipo actual: <code>'+(d.level_type||'minecraft:normal')+'</code>'
    +(d.seed?' · Seed: <code>'+d.seed+'</code>':'')+'</p>';
  list.innerHTML=html;
}
document.addEventListener('click',function(e){
  var ab=e.target.closest('.wc-activate');
  if (ab){ activateWorld(ab.dataset.world); return; }
  var db=e.target.closest('.wc-delete');
  if (db){ deleteWorld(db.dataset.world); }
});
function activateWorld(name){
  showConfirm('Activar el mundo "'+name+'"', 'El servidor usará este mundo en el próximo inicio.', function(){ doActivateWorld(name); });
}
function doActivateWorld(name){
  var form=new FormData(); form.append('world_name',name);
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/worlds/activate',{method:'POST',body:form})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d.success){ showToast('Mundo activado','success'); loadWorlds(); loadServerProps(); } })
    .catch(function(){ showToast('Error','error'); });
}
function deleteWorld(name){
  showConfirm('Borrar "'+name+'"', 'Se borrarán también sus dimensiones nether y end. Esta acción no se puede deshacer.', function(){ doDeleteWorld(name); });
}
function doDeleteWorld(name){
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/worlds/'+encodeURIComponent(name),{method:'DELETE'})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d.success){ showToast('Mundo borrado','success'); loadWorlds(); } })
    .catch(function(){ showToast('Error al borrar','error'); });
}

// Modal nuevo mundo
var nwActivate=true;

var typeDescs={
  'minecraft:normal':'Mundo estándar con biomas variados, estructuras y terreno natural.',
  'minecraft:large_biomes':'Igual que el normal pero los biomas son mucho más grandes. Ideal para exploración.',
  'minecraft:amplified':'Terreno extremo: montañas gigantescas, ravines profundísimas y posibles islas flotantes.',
  'minecraft:flat':'Mundo completamente plano. Perfecto para construcciones y redstone a gran escala.',
  'biomesoplenty':'Añade más de 90 biomas nuevos. Requiere el mod Biomes O Plenty instalado.',
  'terraforged':'Generación de terreno realista y detallada. Requiere el mod TerraForged instalado.',
  'custom':'Introduce manualmente el identificador del tipo de mundo del mod que quieras usar.'
};


// New world inline form listeners
(function() {
  var btnNew = document.getElementById('btn-new-world');
  if (!btnNew) return;

  btnNew.addEventListener('click', function() {
    var form = document.getElementById('new-world-form');
    var open = form.style.display !== 'none';
    form.style.display = open ? 'none' : 'block';
    if (!open && currentModpack) {
      apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/detected-mods')
        .then(function(r){ return r.json(); })
        .then(function(d){
          var bop = document.getElementById('opt-bop');
          var tf  = document.getElementById('opt-tf');
          if (bop) { bop.disabled = !d.has_biomesoplenty; bop.textContent = '🌺 Biomes O Plenty' + (d.has_biomesoplenty ? ' — detectado' : ' — mod no detectado'); }
          if (tf)  { tf.disabled  = !d.has_terraforged;  tf.textContent  = '🏔️ TerraForged'    + (d.has_terraforged  ? ' — detectado' : ' — mod no detectado'); }
        }).catch(function(){});
      updateTypeDesc();
    }
  });

  document.getElementById('nw-cancel-inline').addEventListener('click', function() {
    document.getElementById('new-world-form').style.display = 'none';
  });

  document.getElementById('nw-type-select').addEventListener('change', updateTypeDesc);

  document.getElementById('nw-activate-toggle').addEventListener('click', function() {
    nwActivate = !nwActivate;
    this.classList.toggle('on', nwActivate);
  });

  document.getElementById('nw-confirm').addEventListener('click', function() {
    var name = document.getElementById('nw-name').value.trim();
    if (!name) { showAlert('Escribe un nombre para el mundo'); return; }
    var sel  = document.getElementById('nw-type-select');
    var type = sel.value === 'custom' ? document.getElementById('nw-type-custom').value.trim() : sel.value;
    if (!type) { showAlert('Escribe el tipo de mundo'); return; }
    var form = new FormData();
    form.append('world_name', name);
    form.append('level_type', type);
    form.append('seed', document.getElementById('nw-seed').value.trim());
    form.append('activate', nwActivate ? '1' : '0');
    apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/worlds/create', {method:'POST', body:form})
      .then(function(r){ return r.json().then(function(d){ return {ok:r.ok,d:d}; }); })
      .then(function(res){
        if (res.ok && res.d.success) {
          showToast(res.d.message, 'success');
          document.getElementById('new-world-form').style.display = 'none';
          document.getElementById('nw-name').value = '';
          document.getElementById('nw-seed').value = '';
          loadWorlds();
          if (nwActivate) loadServerProps();
        } else {
          showToast(res.d.detail || 'Error', 'error');
        }
      }).catch(function(){ showToast('Error al crear mundo', 'error'); });
  });
})();

function updateTypeDesc() {
  var sel = document.getElementById('nw-type-select');
  if (!sel) return;
  document.getElementById('nw-type-desc').textContent = typeDescs[sel.value] || '';
  document.getElementById('nw-type-custom').style.display = sel.value === 'custom' ? 'block' : 'none';
}
