// -- Players ------------------------------------------------------------------
function loadPlayers() {
  apiFetch('/api/players').then(function(r){ return r.json(); }).then(function(d){
    renderPlayerList('ops-list', d.ops, 'op', function(p){
      return '<span class="pe-meta">Nivel '+p.level+'</span>';
    });
    renderPlayerList('whitelist-list', d.whitelist, 'wl', null);
    renderBanList('banned-list', d.banned_players, 'player');
    renderBanList('banned-ips-list', d.banned_ips, 'ip');
  }).catch(function(){ showToast('Error al cargar jugadores','error'); });
}

function renderPlayerList(containerId, players, type, extraFn) {
  var el = document.getElementById(containerId);
  if (!players || !players.length) {
    el.innerHTML = '<p class="empty-msg">Sin entradas</p>';
    return;
  }
  var html = '';
  players.forEach(function(p) {
    var name = p.name || p.uuid || '?';
    var extra = extraFn ? extraFn(p) : '';
    html += '<div class="player-entry">'
      + '<span style="font-size:1.1rem">👤</span>'
      + '<span class="pe-name">'+name+'</span>'
      + extra
      + '<div class="pe-actions">'
      + '<button class="btn-danger player-remove-btn" data-type="'+type+'" data-name="'+name+'" style="padding:3px 10px;font-size:.75rem">'
      + (type==='op' ? 'Quitar op' : 'Eliminar') + '</button>'
      + '</div></div>';
  });
  el.innerHTML = html;
}

function renderBanList(containerId, bans, type) {
  var el = document.getElementById(containerId);
  if (!bans || !bans.length) {
    el.innerHTML = '<p class="empty-msg">Sin baneos</p>';
    return;
  }
  var html = '';
  bans.forEach(function(b) {
    var name = type === 'ip' ? b.ip : (b.name || b.uuid || '?');
    var reason = b.reason || '';
    html += '<div class="player-entry">'
      + '<span style="font-size:1.1rem">' + (type==='ip'?'🌐':'👤') + '</span>'
      + '<div style="flex:1"><div class="pe-name">'+name+'</div>'
      + (reason ? '<div class="pe-meta">'+reason+'</div>' : '')
      + '</div>'
      + '<div class="pe-actions">'
      + '<button class="btn-secondary player-unban-btn" data-type="'+type+'" data-name="'+name+'" style="padding:3px 10px;font-size:.75rem">Desbanear</button>'
      + '</div></div>';
  });
  el.innerHTML = html;
}

// Event delegation for remove/unban buttons
document.addEventListener('click', function(e) {
  var removeBtn = e.target.closest('.player-remove-btn');
  if (removeBtn) {
    var type = removeBtn.dataset.type;
    var name = removeBtn.dataset.name;
    if (type === 'op') removeOp(name);
    else if (type === 'wl') removeWhitelist(name);
    return;
  }
  var unbanBtn = e.target.closest('.player-unban-btn');
  if (unbanBtn) {
    var type2 = unbanBtn.dataset.type;
    var name2 = unbanBtn.dataset.name;
    if (type2 === 'player') unbanPlayer(name2);
    else if (type2 === 'ip') unbanIp(name2);
  }
});

function apiCall(method, url, body, successMsg) {
  return fetch(url, { method: method, body: body })
    .then(function(r) { return r.json().then(function(d){ return {ok:r.ok,d:d}; }); })
    .then(function(res) {
      if (res.ok && res.d.success) {
        var n = res.d.synced ? res.d.synced.length : 0;
        showToast(successMsg + ' ('+n+' servers)', 'success');
        loadPlayers();
      } else {
        showToast('Error: '+(res.d.detail||'desconocido'), 'error');
      }
    }).catch(function(e){ showToast('Error: '+e.message,'error'); });
}

// Add op
document.getElementById('btn-add-op').addEventListener('click', function() {
  var name = document.getElementById('op-name-input').value.trim();
  if (!name) { showAlert('Escribe un nombre'); return; }
  var form = new FormData(); form.append('name', name); form.append('level', '4');
  apiCall('POST', '/api/players/op', form, 'Op anadido: '+name)
    .then(function(){ document.getElementById('op-name-input').value=''; });
});
document.getElementById('op-name-input').addEventListener('keydown', function(e){
  if(e.key==='Enter') document.getElementById('btn-add-op').click();
});

function removeOp(name) {
  showConfirm('Quitar op a '+name, 'Se eliminará como operador en todos los servidores.', function(){ doRemoveOp(name); });
}
function doRemoveOp(name) {
  apiCall('DELETE', '/api/players/op/'+encodeURIComponent(name), null, 'Op eliminado: '+name);
}

// Add whitelist
document.getElementById('btn-add-wl').addEventListener('click', function() {
  var name = document.getElementById('wl-name-input').value.trim();
  if (!name) { showAlert('Escribe un nombre'); return; }
  var form = new FormData(); form.append('name', name);
  apiCall('POST', '/api/players/whitelist', form, 'Anadido a whitelist: '+name)
    .then(function(){ document.getElementById('wl-name-input').value=''; });
});
document.getElementById('wl-name-input').addEventListener('keydown', function(e){
  if(e.key==='Enter') document.getElementById('btn-add-wl').click();
});

function removeWhitelist(name) {
  showConfirm('Eliminar de whitelist', 'Se eliminará a '+name+' de la whitelist global.', function(){ doRemoveWhitelist(name); });
}
function doRemoveWhitelist(name) {
  apiCall('DELETE', '/api/players/whitelist/'+encodeURIComponent(name), null, 'Eliminado de whitelist: '+name);
}

// Ban player
document.getElementById('btn-ban-player').addEventListener('click', function() {
  var name = document.getElementById('ban-name-input').value.trim();
  if (!name) { showAlert('Escribe un nombre'); return; }
  var reason = document.getElementById('ban-reason-input').value.trim() || 'Banned by admin';
  var form = new FormData(); form.append('name', name); form.append('reason', reason);
  apiCall('POST', '/api/players/ban', form, 'Baneado: '+name).then(function(){
    document.getElementById('ban-name-input').value='';
    document.getElementById('ban-reason-input').value='';
  });
});

function unbanPlayer(name) {
  showConfirm('Desbanear a '+name, 'Se desbaneará en todos los servidores.', function(){ doUnbanPlayer(name); });
}
function doUnbanPlayer(name) {
  apiCall('DELETE', '/api/players/ban/'+encodeURIComponent(name), null, 'Desbaneado: '+name);
}

// Ban IP
document.getElementById('btn-ban-ip').addEventListener('click', function() {
  var ip = document.getElementById('ban-ip-input').value.trim();
  if (!ip) { showAlert('Escribe una IP'); return; }
  var reason = document.getElementById('ban-ip-reason-input').value.trim() || 'Banned by admin';
  var form = new FormData(); form.append('ip', ip); form.append('reason', reason);
  apiCall('POST', '/api/players/ban-ip', form, 'IP baneada: '+ip).then(function(){
    document.getElementById('ban-ip-input').value='';
    document.getElementById('ban-ip-reason-input').value='';
  });
});

function unbanIp(ip) {
  showConfirm('Desbanear IP '+ip, 'Se desbaneará en todos los servidores.', function(){ doUnbanIp(ip); });
}
function doUnbanIp(ip) {
  apiCall('DELETE', '/api/players/ban-ip/'+encodeURIComponent(ip), null, 'IP desbaneada: '+ip);
}

// Sync all
document.getElementById('btn-sync-all').addEventListener('click', function() {
  apiFetch('/api/players/sync', {method:'POST'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.warning) showToast(d.warning, '');
      else showToast('Sincronizado a todos los servers', 'success');
    })
    .catch(function(){ showToast('Error al sincronizar','error'); });
});

// Load when entering players tab
document.getElementById('tab-players').addEventListener('click', loadPlayers);
