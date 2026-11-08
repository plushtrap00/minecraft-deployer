// -- Players ------------------------------------------------------------------
// Cada lista es una cuadrícula de fichas con la cabeza del jugador (ver
// headHtml en appearance.js).
var PLAYER_EMPTY = {
  op: ['sign', 'Nadie tiene op todavía', 'Añade a quien deba poder usar los comandos de administrador.'],
  wl: ['sign', 'La whitelist está vacía', 'Si la activas en server.properties, solo podrán entrar los jugadores que estén aquí.'],
  player: ['shield', 'Ningún jugador baneado', 'Todo el mundo se porta bien. De momento.'],
  ip: ['shield', 'Ninguna IP baneada', 'Banear una IP impide entrar desde esa conexión, con cualquier cuenta.']
};

function playerEmptyHtml(type) {
  var empty = PLAYER_EMPTY[type];
  return emptyArt(empty[0], empty[1], empty[2], null, true);
}

function loadPlayers() {
  loadPlayerStats();
  apiFetch('/api/players')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      renderPlayerList('ops-list', data.ops, 'op', function(player) {
        return '<span class="pe-meta">Nivel ' + player.level + '</span>';
      });
      renderPlayerList('whitelist-list', data.whitelist, 'wl', null);
      renderBanList('banned-list', data.banned_players, 'player');
      renderBanList('banned-ips-list', data.banned_ips, 'ip');
    })
    .catch(function() { showToast('No se pudo cargar la lista de jugadores', 'error'); });
  loadOnlinePlayers();
}

// Quién está jugando ahora mismo, si hay un servidor en marcha.
function loadOnlinePlayers() {
  var card = document.getElementById('players-online-card');
  if (!serverRunning) {
    card.hidden = true;
    return;
  }
  apiFetch('/api/server/metrics')
    .then(function(response) { return response.json(); })
    .then(function(data) {
      var players = data.players_online || [];
      card.hidden = false;
      document.getElementById('players-online-server').textContent = 'en ' + document.getElementById('status-modpack').textContent;
      var grid = document.getElementById('players-online');
      if (!players.length) {
        grid.innerHTML = emptyArt('sapling', 'No hay nadie jugando', 'Cuando alguien entre al servidor aparecerá aquí.', null, true);
        return;
      }
      grid.innerHTML = players.map(function(name) {
        return '<div class="player-tile online">' + headHtml(name, null, 'lg')
          + '<div class="player-tile-info"><div class="pe-name">' + escHtml(name) + '</div>'
          + '<div class="pe-meta"><span class="online-dot"></span>Jugando</div></div></div>';
      }).join('');
    })
    .catch(function() { card.hidden = true; });
}

function renderPlayerList(containerId, players, type, extraFn) {
  var el = document.getElementById(containerId);
  if (!players || !players.length) {
    el.innerHTML = playerEmptyHtml(type);
    return;
  }
  var removeLabel = type === 'op' ? 'Quitar op' : 'Quitar';
  el.innerHTML = '<div class="player-grid">' + players.map(function(player) {
    var name = player.name || player.uuid || '?';
    return '<div class="player-tile">' + headHtml(player.name, player.uuid, 'lg')
      + '<div class="player-tile-info"><div class="pe-name">' + escHtml(name) + '</div>'
      + (extraFn ? extraFn(player) : '') + '</div>'
      + '<button class="btn-ghost btn-xs player-remove-btn" data-type="' + type + '" data-name="' + escHtml(name) + '"'
      + ' aria-label="' + escHtml(removeLabel + ': ' + name) + '">' + removeLabel + '</button>'
      + '</div>';
  }).join('') + '</div>';
}

function renderBanList(containerId, bans, type) {
  var el = document.getElementById(containerId);
  if (!bans || !bans.length) {
    el.innerHTML = playerEmptyHtml(type);
    return;
  }
  el.innerHTML = '<div class="player-grid">' + bans.map(function(ban) {
    var name = type === 'ip' ? ban.ip : (ban.name || ban.uuid || '?');
    var avatar = type === 'ip'
      ? '<span class="player-head lg ip-avatar" aria-hidden="true">' + icon('globe') + '</span>'
      : headHtml(ban.name, ban.uuid, 'lg');
    return '<div class="player-tile banned">' + avatar
      + '<div class="player-tile-info"><div class="pe-name">' + escHtml(name) + '</div>'
      + (ban.reason ? '<div class="pe-meta" title="' + escHtml(ban.reason) + '">' + escHtml(ban.reason) + '</div>' : '')
      + '</div>'
      + '<button class="btn-ghost btn-xs player-unban-btn" data-type="' + type + '" data-name="' + escHtml(name) + '"'
      + ' aria-label="' + escHtml('Desbanear: ' + name) + '">Desbanear</button>'
      + '</div>';
  }).join('') + '</div>';
}

document.addEventListener('click', function(event) {
  var removeBtn = event.target.closest('.player-remove-btn');
  if (removeBtn) {
    var type = removeBtn.dataset.type;
    var name = removeBtn.dataset.name;
    if (type === 'op') {
      removeOp(name);
    } else if (type === 'wl') {
      removeWhitelist(name);
    }
    return;
  }
  var unbanBtn = event.target.closest('.player-unban-btn');
  if (unbanBtn) {
    var unbanType = unbanBtn.dataset.type;
    var unbanName = unbanBtn.dataset.name;
    if (unbanType === 'player') {
      unbanPlayer(unbanName);
    } else if (unbanType === 'ip') {
      unbanIp(unbanName);
    }
  }
});

function apiCall(method, url, body, successMsg) {
  return apiFetch(url, { method: method, body: body })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      if (result.ok && result.data.success) {
        var syncedCount = result.data.synced ? result.data.synced.length : 0;
        showToast(successMsg + ' (' + syncedCount + (syncedCount === 1 ? ' servidor)' : ' servidores)'), 'success');
        loadPlayers();
        return true;
      }
      showToast(result.data.detail || 'No se pudo guardar el cambio', 'error');
      return false;
    })
    .catch(function(error) {
      showToast('No se pudo conectar con el panel: ' + error.message, 'error');
      return false;
    });
}

// Add op
document.getElementById('btn-add-op').addEventListener('click', function() {
  var name = document.getElementById('op-name-input').value.trim();
  if (!name) {
    showAlert('Escribe un nombre');
    return;
  }
  var form = new FormData();
  form.append('name', name);
  form.append('level', '4');
  apiCall('POST', '/api/players/op', form, 'Op añadido: ' + name)
    .then(function(ok) {
      document.getElementById('op-name-input').value = '';
      if (ok) {
        unlockAchievement('first-op');
      }
    });
});

document.getElementById('op-name-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    document.getElementById('btn-add-op').click();
  }
});

function removeOp(name) {
  showConfirm(
    'Quitar op a ' + name,
    'Se eliminará como operador en todos los servidores.',
    function() { doRemoveOp(name); }
  );
}

function doRemoveOp(name) {
  apiCall('DELETE', '/api/players/op/' + encodeURIComponent(name), null, 'Op eliminado: ' + name);
}

// Add whitelist
document.getElementById('btn-add-wl').addEventListener('click', function() {
  var name = document.getElementById('wl-name-input').value.trim();
  if (!name) {
    showAlert('Escribe un nombre');
    return;
  }
  var form = new FormData();
  form.append('name', name);
  apiCall('POST', '/api/players/whitelist', form, 'Añadido a la whitelist: ' + name)
    .then(function() { document.getElementById('wl-name-input').value = ''; });
});

document.getElementById('wl-name-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    document.getElementById('btn-add-wl').click();
  }
});

function removeWhitelist(name) {
  showConfirm(
    'Eliminar de whitelist',
    'Se eliminará a ' + name + ' de la whitelist global.',
    function() { doRemoveWhitelist(name); }
  );
}

function doRemoveWhitelist(name) {
  apiCall('DELETE', '/api/players/whitelist/' + encodeURIComponent(name), null, 'Quitado de la whitelist: ' + name);
}

// Ban player
document.getElementById('btn-ban-player').addEventListener('click', function() {
  var name = document.getElementById('ban-name-input').value.trim();
  if (!name) {
    showAlert('Escribe un nombre');
    return;
  }
  var reason = document.getElementById('ban-reason-input').value.trim() || '';
  var form = new FormData();
  form.append('name', name);
  form.append('reason', reason);
  apiCall('POST', '/api/players/ban', form, 'Baneado: ' + name).then(function(ok) {
    if (ok) {
      unlockAchievement('iron-fist');
    }
    document.getElementById('ban-name-input').value = '';
    document.getElementById('ban-reason-input').value = '';
  });
});

function unbanPlayer(name) {
  showConfirm(
    'Desbanear a ' + name,
    'Se desbaneará en todos los servidores.',
    function() { doUnbanPlayer(name); }
  );
}

function doUnbanPlayer(name) {
  apiCall('DELETE', '/api/players/ban/' + encodeURIComponent(name), null, 'Desbaneado: ' + name).then(function(ok) {
    if (ok) {
      unlockAchievement('mercy');
    }
  });
}

// Ban IP
document.getElementById('btn-ban-ip').addEventListener('click', function() {
  var ip = document.getElementById('ban-ip-input').value.trim();
  if (!ip) {
    showAlert('Escribe una IP');
    return;
  }
  var reason = document.getElementById('ban-ip-reason-input').value.trim() || '';
  var form = new FormData();
  form.append('ip', ip);
  form.append('reason', reason);
  apiCall('POST', '/api/players/ban-ip', form, 'IP baneada: ' + ip).then(function(ok) {
    if (ok) {
      unlockAchievement('iron-fist');
    }
    document.getElementById('ban-ip-input').value = '';
    document.getElementById('ban-ip-reason-input').value = '';
  });
});

function unbanIp(ip) {
  showConfirm(
    'Desbanear IP ' + ip,
    'Se desbaneará en todos los servidores.',
    function() { doUnbanIp(ip); }
  );
}

function doUnbanIp(ip) {
  apiCall('DELETE', '/api/players/ban-ip/' + encodeURIComponent(ip), null, 'IP desbaneada: ' + ip).then(function(ok) {
    if (ok) {
      unlockAchievement('mercy');
    }
  });
}

// Sync all
document.getElementById('btn-sync-all').addEventListener('click', function() {
  apiFetch('/api/players/sync', { method: 'POST' })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      if (data.warning) {
        showToast(data.warning, '');
      } else {
        showToast('Sincronizado con todos los servidores', 'success');
      }
    })
    .catch(function() { showToast('No se pudo sincronizar con los servidores', 'error'); });
});

