// -- Cuándo se juega (página Jugadores) --------------------------------------------
// Datos de /api/players/activity (services/sessions.py): racha de días seguidos
// con alguien jugando, resumen de los últimos 7 días y mapa de calor por día de
// la semana y hora. El mapa usa un solo tono (el del tema) de claro a oscuro.
var PLAY_LEVELS = 5;

function playWeekdayName(index, style) {
  // 5 de enero de 2026 fue lunes: igual que DAY_NAMES de automation.js.
  return new Date(2026, 0, 5 + index).toLocaleDateString(APP_LOCALE, { weekday: style || 'long' });
}

function playHours(minutes) {
  var hours = minutes / 60;
  return hours >= 10 ? Math.round(hours).toLocaleString(APP_LOCALE) : (Math.round(hours * 10) / 10).toLocaleString(APP_LOCALE);
}

function playStreakHtml(streak) {
  var text;
  if (streak.current >= 2) {
    text = t('{n} días seguidos con alguien jugando', { n: streak.current });
  } else if (streak.current === 1) {
    text = streak.today ? t('Hoy ya ha jugado alguien') : t('Ayer jugó alguien: si hoy entra alguien, empieza una racha');
  } else {
    text = t('Sin racha ahora mismo');
  }
  var hot = streak.current >= 3 ? ' is-hot' : '';
  return '<div class="play-streak' + hot + '">'
    + '<span class="play-streak-num">' + icon('flame') + streak.current + '</span>'
    + '<div><div class="play-streak-text">' + escHtml(text) + '</div>'
    + (streak.best ? '<div class="play-streak-best">' + escHtml(t('Mejor racha: {n} días', { n: streak.best })) + '</div>' : '')
    + (!streak.today && streak.current ? '<div class="play-streak-best">' + escHtml(t('Hoy todavía no ha jugado nadie: ¡que no se corte!')) + '</div>' : '')
    + '</div></div>';
}

function playStat(label, value) {
  return '<div class="play-stat"><div class="play-stat-value">' + escHtml(String(value)) + '</div>'
    + '<div class="play-stat-label">' + escHtml(label) + '</div></div>';
}

function playWeekHtml(week) {
  if (!week.players) {
    return '<p class="play-week-empty">' + escHtml(t('En los últimos 7 días no ha jugado nadie.')) + '</p>';
  }
  var html = '<div class="play-stats">'
    + playStat(t('Jugadores'), week.players)
    + playStat(t('Horas jugadas'), playHours(week.hours * 60))
    + playStat(t('Partidas'), week.sessions)
    + playStat(t('Día con más juego'), capitalizeFirst(playWeekdayName(week.busiest_weekday)))
    + '</div>';
  var notes = [];
  if (week.top.length) {
    notes.push(icon('trophy') + escHtml(t('Quien más ha jugado: {player} ({hours} h)', { player: week.top[0].player, hours: playHours(week.top[0].minutes) })));
  }
  if (week.new_players.length) {
    notes.push(icon('users') + escHtml(t('Caras nuevas: {names}', { names: joinList(week.new_players) })));
  }
  if (notes.length) {
    html += '<div class="play-notes">' + notes.map(function(note) { return '<span>' + note + '</span>'; }).join('') + '</div>';
  }
  return html;
}

function playLevel(value, max) {
  if (!value || !max) {
    return 0;
  }
  return Math.max(1, Math.ceil(value / max * PLAY_LEVELS));
}

function playHeatmapHtml(heatmap) {
  var weeks = heatmap.days / 7;
  if (!heatmap.max) {
    return emptyArt('map', t('Aún no hay partidas apuntadas'),
      t('Cada vez que alguien entra y sale del servidor se apunta aquí. En unos días verás a qué horas se juega más.'), '', true);
  }
  var hours = '<div class="heat-corner"></div>';
  for (var h = 0; h < 24; h++) {
    hours += '<div class="heat-hour">' + (h % 3 === 0 ? h : '') + '</div>';
  }
  var rows = '';
  var table = [];
  heatmap.grid.forEach(function(row, day) {
    var dayName = playWeekdayName(day);
    rows += '<div class="heat-day" title="' + escHtml(dayName) + '">' + escHtml(playWeekdayName(day, 'short')) + '</div>';
    var busiest = 0;
    row.forEach(function(minutes, hour) {
      var average = minutes / 60 / weeks;
      var label = dayName + ', ' + String(hour).padStart(2, '0') + ':00–' + String((hour + 1) % 24).padStart(2, '0') + ':00 · '
        + (minutes ? t('{n} jugadores de media', { n: (Math.round(average * 10) / 10).toLocaleString(APP_LOCALE) }) : t('nadie'));
      rows += '<div class="heat-cell" data-level="' + playLevel(minutes, heatmap.max) + '" title="' + escHtml(label) + '" aria-label="' + escHtml(label) + '"></div>';
      if (minutes > row[busiest]) {
        busiest = hour;
      }
    });
    table.push(dayName + ': ' + (row[busiest] ? t('sobre todo a las {hour}', { hour: busiest + ':00' }) : t('nadie')));
  });
  var legend = '<div class="heat-legend" aria-hidden="true"><span>' + t('Menos') + '</span>';
  for (var level = 0; level <= PLAY_LEVELS; level++) {
    legend += '<span class="heat-cell" data-level="' + level + '"></span>';
  }
  legend += '<span>' + t('Más') + '</span></div>';
  return '<div class="heat-wrap"><div class="heat-grid" role="img" aria-label="' + escHtml(t('Mapa de calor: a qué horas se juega cada día de la semana')) + '">' + hours + rows + '</div></div>'
    + '<div class="heat-foot">' + legend
    + '<details class="heat-table"><summary>' + t('Verlo en texto') + '</summary><ul>'
    + table.map(function(line) { return '<li>' + escHtml(line) + '</li>'; }).join('') + '</ul></details></div>';
}

function fillPlayModpacks(modpacks) {
  var select = document.getElementById('play-modpack');
  var current = select.value;
  select.innerHTML = '<option value="">' + escHtml(t('Todos los servidores')) + '</option>'
    + modpacks.map(function(name) { return '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>'; }).join('');
  select.value = modpacks.indexOf(current) !== -1 ? current : '';
}

function loadPlayActivity() {
  var params = 'weeks=' + document.getElementById('play-weeks').value
    + '&modpack=' + encodeURIComponent(document.getElementById('play-modpack').value);
  apiJson('/api/players/activity?' + params).then(function(result) {
    var box = document.getElementById('play-activity');
    if (!result.ok) {
      box.innerHTML = noticeHtml('error', escHtml(result.data.detail || t('No se pudo cargar')));
      return;
    }
    var data = result.data;
    fillPlayModpacks(data.modpacks);
    box.innerHTML = '<div class="play-top">' + playStreakHtml(data.streak)
      + '<div class="play-week"><div class="block-label">' + t('Últimos 7 días') + '</div>' + playWeekHtml(data.week) + '</div></div>'
      + playHeatmapHtml(data.heatmap);
    if (data.streak.best >= 7) {
      unlockAchievement('on-fire');
    }
  });
}

document.getElementById('play-weeks').addEventListener('change', loadPlayActivity);
document.getElementById('play-modpack').addEventListener('change', loadPlayActivity);

function capitalizeFirst(text) {
  return text.charAt(0).toLocaleUpperCase(APP_LOCALE) + text.slice(1);
}
