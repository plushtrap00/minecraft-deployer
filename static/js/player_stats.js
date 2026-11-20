// -- Jugadores → Estadísticas: lo que guarda el propio mundo de cada jugador ---
// (world/stats/*.json). Se puede ordenar por cualquier columna.
var STAT_COLUMNS = [
  { key: 'play_seconds', label: t('Tiempo jugado'), format: formatPlayTime },
  { key: 'last_seen', label: t('Última vez'), format: function(v) { return v ? formatRelativeDate(v) : '—'; } },
  { key: 'deaths', label: t('Muertes') },
  { key: 'mob_kills', label: t('Bichos') },
  { key: 'player_kills', label: t('Jugadores') },
  { key: 'blocks_mined', label: t('Bloques picados') },
  { key: 'distance_km', label: t('Recorrido'), format: function(v) { return v.toLocaleString(APP_LOCALE, { maximumFractionDigits: 1 }) + ' km'; } },
  { key: 'jumps', label: t('Saltos') }
];
var statsData = null;
var statsSort = 'play_seconds';

function formatPlayTime(seconds) {
  var hours = Math.floor(seconds / 3600);
  var minutes = Math.floor((seconds % 3600) / 60);
  if (hours >= 1) {
    return hours.toLocaleString(APP_LOCALE) + ' h ' + minutes + ' min';
  }
  return minutes + ' min';
}

function loadPlayerStats() {
  var select = document.getElementById('stats-modpack');
  var previous = select.value;
  refreshServerPackInfo().then(function(packs) {
    if (!packs.length) {
      select.innerHTML = '';
      document.getElementById('stats-table').innerHTML = emptyArt('spyglass', t('Sin servidores'), t('Cuando instales uno y alguien juegue, aquí verás quién ha jugado más.'), '', true);
      return;
    }
    var running = serverRunning ? document.getElementById('console-modpack').textContent : '';
    var names = packs.map(function(pack) { return pack.name; });
    select.innerHTML = names.map(function(name) {
      return '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>';
    }).join('');
    select.value = names.indexOf(previous) !== -1 ? previous : (names.indexOf(running) !== -1 ? running : names[0]);
    fetchPlayerStats();
  }).catch(function() {});
}

function fetchPlayerStats() {
  var modpack = document.getElementById('stats-modpack').value;
  var holder = document.getElementById('stats-table');
  holder.innerHTML = loadingHtml();
  apiJson('/api/modpacks/' + encodeURIComponent(modpack) + '/player-stats').then(function(result) {
    if (modpack !== document.getElementById('stats-modpack').value) {
      return;
    }
    if (!result.ok) {
      holder.innerHTML = noticeHtml('error', escHtml(result.data.detail || t('No se pudieron leer las estadísticas.')));
      return;
    }
    statsData = result.data;
    // last_seen llega como fecha ISO: se pasa a segundos para ordenar y mostrarla.
    (statsData.players || []).forEach(function(player) {
      player.last_seen = player.last_seen ? new Date(player.last_seen).getTime() / 1000 : 0;
    });
    renderPlayerStats();
  });
}

function renderPlayerStats() {
  var holder = document.getElementById('stats-table');
  var players = (statsData.players || []).slice();
  if (!players.length) {
    holder.innerHTML = emptyArt('spyglass', t('Nadie ha jugado todavía'), t('Las estadísticas aparecen cuando alguien entra en este mundo.'), '', true);
    return;
  }
  players.sort(function(a, b) { return (b[statsSort] || 0) - (a[statsSort] || 0); });
  var best = players[0][statsSort];
  var html = '<div class="stats-scroll"><table class="stats-table"><thead><tr><th scope="col">' + t('Jugador') + '</th>';
  STAT_COLUMNS.forEach(function(col) {
    var active = col.key === statsSort;
    html += '<th scope="col" class="num"' + (active ? ' aria-sort="descending"' : '') + '>'
      + '<button type="button" class="stats-sort' + (active ? ' active' : '') + '" data-key="' + col.key + '">' + escHtml(col.label)
      + (active ? icon('chevron-down') : '') + '</button></th>';
  });
  html += '</tr></thead><tbody>';
  players.forEach(function(player) {
    var leader = best > 0 && player[statsSort] === best;
    html += '<tr><th scope="row"><span class="stats-player">' + headHtml(player.name, player.uuid, 'sm')
      + '<span>' + escHtml(player.name || player.uuid.slice(0, 8)) + '</span>'
      + (leader ? '<span class="stats-crown" title="' + t('El primero en esta columna') + '">' + icon('star') + '</span>' : '') + '</span></th>';
    STAT_COLUMNS.forEach(function(col) {
      var value = player[col.key] || 0;
      html += '<td class="num' + (col.key === statsSort ? ' active' : '') + '">'
        + escHtml(col.format ? col.format(value) : value.toLocaleString(APP_LOCALE)) + '</td>';
    });
    html += '</tr>';
  });
  holder.innerHTML = html + '</tbody></table></div>';
}

document.getElementById('stats-modpack').addEventListener('change', fetchPlayerStats);
document.getElementById('stats-table').addEventListener('click', function(event) {
  var button = event.target.closest('.stats-sort');
  if (button && statsData) {
    statsSort = button.dataset.key;
    renderPlayerStats();
  }
});
