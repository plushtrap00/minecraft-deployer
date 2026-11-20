// -- Configuración → Avisos (solo admin): Telegram y Discord -------------------
// Todo opcional. El token del bot y el webhook se guardan en el .env, pero el
// panel los lee en cada envío: guardar aquí se aplica al momento.
var notifyLoaded = false;

function loadNotifications() {
  var events = document.getElementById('notify-events');
  if (!notifyLoaded) {
    events.innerHTML = loadingHtml();
  }
  apiJson('/api/admin/notifications').then(function(result) {
    if (!result.ok) {
      events.innerHTML = noticeHtml('error', t('No se pudieron leer los avisos.'));
      return;
    }
    notifyLoaded = true;
    var data = result.data;
    var secretsSet = data.secrets_set || {};
    setSecretField('notify-telegram-token', !!secretsSet.telegram_token);
    setSecretField('notify-discord-url', !!secretsSet.discord_webhook);
    document.getElementById('notify-telegram-chat').value = data.telegram_chat_id || '';
    document.getElementById('notify-detect-hint').textContent = '';
    var enabled = data.events || [];
    events.innerHTML = Object.keys(data.available_events).map(function(key) {
      return '<label class="notify-event"><input type="checkbox" value="' + escHtml(key) + '"'
        + (enabled.indexOf(key) !== -1 ? ' checked' : '') + '> ' + escHtml(t(data.available_events[key])) + '</label>';
    }).join('');
  });
}

function notifyFormValues() {
  return {
    telegram_token: document.getElementById('notify-telegram-token').value.trim(),
    telegram_chat_id: document.getElementById('notify-telegram-chat').value.trim(),
    discord_webhook: document.getElementById('notify-discord-url').value.trim(),
    clear: secretsToClear(document.getElementById('cfg-content-notify')),
    events: Array.prototype.map.call(
      document.querySelectorAll('#notify-events input:checked'),
      function(box) { return box.value; }
    )
  };
}

function postNotify(url, body) {
  return apiJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

// Quitar el token deja Telegram sin configurar: el chat ID solo no sirve (y
// el servidor rechaza guardar uno sin el otro), así que se vacía también.
document.querySelector('[data-clear-secret="notify-telegram-token"]').addEventListener('click', function() {
  // Este clic llega antes que el de utils.js, que es el que lo marca: aquí
  // aún no está marcado si se va a quitar.
  if (document.getElementById('notify-telegram-token').dataset.clear !== '1') {
    document.getElementById('notify-telegram-chat').value = '';
  }
});

document.getElementById('notify-token-vis').addEventListener('click', function() {
  var input = document.getElementById('notify-telegram-token');
  input.type = input.type === 'password' ? 'text' : 'password';
  this.innerHTML = icon(input.type === 'password' ? 'eye' : 'eye-off');
});

document.getElementById('notify-detect-btn').addEventListener('click', function() {
  var btn = this;
  var hint = document.getElementById('notify-detect-hint');
  var tokenInput = document.getElementById('notify-telegram-token');
  var token = tokenInput.value.trim();
  // Vacío vale si ya hay uno guardado (y no se está quitando): lo usa el servidor.
  if (!token && !(tokenInput.dataset.secretSet === '1' && tokenInput.dataset.clear !== '1')) {
    showToast(t('Pega primero el token del bot'), 'error');
    return;
  }
  btn.disabled = true;
  hint.textContent = t('Buscando el último mensaje que le escribiste al bot…');
  postNotify('/api/admin/notifications/detect-chat', { telegram_token: token }).then(function(result) {
    btn.disabled = false;
    if (!result.ok) {
      hint.textContent = '';
      showToast(result.data.detail || t('No se pudo detectar el chat'), 'error');
      return;
    }
    document.getElementById('notify-telegram-chat').value = result.data.chat_id;
    hint.textContent = t('Encontrado: {name}. Guarda para empezar a recibir avisos.', { name: result.data.name || result.data.chat_id });
  });
});

document.getElementById('notify-test-btn').addEventListener('click', function() {
  var btn = this;
  btn.disabled = true;
  postNotify('/api/admin/notifications/test', notifyFormValues()).then(function(result) {
    btn.disabled = false;
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo enviar la prueba'), 'error');
      return;
    }
    var names = { telegram: 'Telegram', discord: 'Discord' };
    var failed = Object.keys(result.data.results).filter(function(channel) {
      return result.data.results[channel] !== 'ok';
    });
    if (!failed.length) {
      showToast(t('Prueba enviada. Mira tu {where}.', { where: Object.keys(result.data.results).map(function(c) { return names[c]; }).join(t(' y tu ')) }), 'success');
      unlockAchievement('messenger');
    } else {
      showToast(failed.map(function(c) { return names[c] + ': ' + result.data.results[c]; }).join('. '), 'error');
    }
  });
});

document.getElementById('notify-save-btn').addEventListener('click', function() {
  var btn = this;
  busyWhile(btn, function() {
    return postNotify('/api/admin/notifications', notifyFormValues()).then(function(result) {
      if (result.ok) {
        showToast(t('Avisos guardados'), 'success');
        flashDone(btn);
        loadNotifications();
      } else {
        showToast(result.data.detail || t('No se pudieron guardar los avisos'), 'error');
      }
    });
  });
});
