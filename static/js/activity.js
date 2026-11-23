// -- Registro de actividad (página Usuarios, solo administrador) -------------------
// Datos de /api/activity (services/activity.py). Cada acción trae su texto en
// español con {parámetros}; aquí se traduce con t() y se resaltan los valores.
var activityState = { items: [], oldest: null, loading: false };

var ACTIVITY_ICONS = {
  server: 'server', players: 'users', mods: 'puzzle', files: 'file-text', install: 'package',
  backups: 'archive', automation: 'timer', users: 'user-cog', security: 'lock', config: 'settings'
};

function activityText(item) {
  var params = {};
  Object.keys(item.params || {}).forEach(function(key) {
    params[key] = '<b>' + escHtml(item.params[key]) + '</b>';
  });
  // El texto viene de services/activity.py (no del usuario); los valores ya van escapados.
  return t(item.label, params);
}

function activityDayLabel(date) {
  var today = new Date();
  var yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) {
    return t('Hoy');
  }
  if (date.toDateString() === yesterday.toDateString()) {
    return t('Ayer');
  }
  return date.toLocaleDateString(APP_LOCALE, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

function activityWho(item) {
  if (item.user) {
    return '<span class="activity-user">' + escHtml(item.user) + '</span>';
  }
  if (item.action === 'auth.login_failed') {
    return '<span class="activity-user unknown">' + t('Desconocido') + '</span>';
  }
  return '<span class="activity-user system">' + icon('timer') + t('Automático') + '</span>';
}

function renderActivity() {
  var list = document.getElementById('activity-list');
  if (!activityState.items.length) {
    list.innerHTML = '<div class="activity-empty">' + t('Aún no hay nada apuntado con estos filtros.') + '</div>';
    return;
  }
  var html = '';
  var lastDay = '';
  activityState.items.forEach(function(item) {
    var date = new Date(item.ts * 1000);
    var day = date.toDateString();
    if (day !== lastDay) {
      html += '<div class="activity-day">' + escHtml(activityDayLabel(date)) + '</div>';
      lastDay = day;
    }
    var title = date.toLocaleString(APP_LOCALE) + (item.ip ? ' · IP ' + item.ip : '');
    html += '<div class="activity-row ' + escHtml(item.category) + (item.action === 'auth.login_failed' ? ' failed' : '') + '" title="' + escHtml(title) + '">'
      + '<span class="activity-time">' + escHtml(date.toLocaleTimeString(APP_LOCALE, { hour: '2-digit', minute: '2-digit' })) + '</span>'
      + '<span class="activity-icon">' + icon(ACTIVITY_ICONS[item.category] || 'info') + '</span>'
      + '<div class="activity-body"><div class="activity-text">' + activityText(item) + '</div>'
      + (item.detail ? '<div class="activity-detail">' + escHtml(item.detail) + '</div>' : '')
      + '</div>' + activityWho(item) + '</div>';
  });
  list.innerHTML = html;
}

function loadActivity(reset) {
  if (currentRole !== 'admin' || activityState.loading) {
    return;
  }
  if (reset) {
    activityState.items = [];
    activityState.oldest = null;
    document.getElementById('activity-list').innerHTML = '<div class="skeleton-rows" role="status" aria-label="' + escHtml(t('Cargando')) + '"><div></div><div></div><div></div></div>';
  }
  var params = ['limit=100'];
  var user = document.getElementById('activity-user').value;
  var category = document.getElementById('activity-category').value;
  if (user !== '') {
    params.push('user=' + encodeURIComponent(user === '__system' ? '' : user));
  }
  if (category) {
    params.push('category=' + encodeURIComponent(category));
  }
  if (activityState.oldest !== null) {
    params.push('before=' + activityState.oldest);
  }
  activityState.loading = true;
  apiJson('/api/activity?' + params.join('&')).then(function(result) {
    activityState.loading = false;
    if (!result.ok) {
      document.getElementById('activity-list').innerHTML = modErrorHtml(result.data.detail || t('No se pudo cargar'));
      return;
    }
    activityState.items = activityState.items.concat(result.data.items);
    if (result.data.items.length) {
      activityState.oldest = result.data.items[result.data.items.length - 1].ts;
    }
    fillActivityUsers(result.data.users);
    document.getElementById('activity-more').hidden = !result.data.more;
    renderActivity();
  });
}

function fillActivityUsers(users) {
  var select = document.getElementById('activity-user');
  var current = select.value;
  var options = '<option value="">' + escHtml(t('Todas las personas')) + '</option>';
  users.forEach(function(user) {
    var value = user || '__system';
    options += '<option value="' + escHtml(value) + '">' + escHtml(user || t('Automático')) + '</option>';
  });
  select.innerHTML = options;
  select.value = current;
}

document.getElementById('activity-user').addEventListener('change', function() { loadActivity(true); });
document.getElementById('activity-category').addEventListener('change', function() { loadActivity(true); });
document.getElementById('btn-refresh-activity').addEventListener('click', function() { loadActivity(true); });
document.getElementById('activity-more').addEventListener('click', function() { loadActivity(false); });
