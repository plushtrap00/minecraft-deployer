// -- Modpacks → Copias: copias del mundo y clonar el modpack -------------------
var backupBusy = false;

function backupUrl(modpack, rest) {
  return '/api/modpacks/' + encodeURIComponent(modpack) + '/backups' + (rest ? '/' + encodeURIComponent(rest) : '');
}

function loadBackups() {
  var modpack = currentModpack;
  var list = document.getElementById('backup-list');
  if (!modpack) {
    return;
  }
  list.innerHTML = loadingHtml();
  apiJson(backupUrl(modpack)).then(function(result) {
    if (modpack !== currentModpack) {
      return;
    }
    if (!result.ok) {
      list.innerHTML = noticeHtml('error', escHtml(result.data.detail || 'No se pudieron cargar las copias.'));
      return;
    }
    renderBackups(result.data);
  });
}

function formatBackupDate(iso) {
  var date = new Date(iso);
  return date.toLocaleString('es-ES', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function renderBackups(data) {
  var list = document.getElementById('backup-list');
  document.getElementById('backup-now-btn').disabled = !data.has_world || backupBusy;
  if (!data.backups.length) {
    list.innerHTML = data.has_world
      ? emptyArt('chest', 'Aún no hay copias', 'Haz la primera ahora: tarda poco y te puede salvar el mundo.', '', true)
      : emptyArt('map', 'No hay mundo que copiar', 'Este servidor todavía no tiene mundo. Se crea la primera vez que lo arrancas.', '', true);
    return;
  }
  var total = data.backups.reduce(function(sum, item) { return sum + item.size; }, 0);
  var html = '<div class="backup-summary">' + data.backups.length + (data.backups.length === 1 ? ' copia' : ' copias')
    + ', ' + formatBytes(total) + ' en total</div>'
    + '<div class="backup-table" role="table" aria-label="Copias de seguridad">'
    + '<div class="backup-row backup-row-head" role="row"><span role="columnheader">Fecha</span><span role="columnheader">Mundo</span>'
    + '<span role="columnheader">Tipo</span><span role="columnheader" class="num">Tamaño</span><span role="columnheader"><span class="visually-hidden">Acciones</span></span></div>';
  data.backups.forEach(function(item) {
    var created = new Date(item.created).getTime() / 1000;
    html += '<div class="backup-row" role="row" data-name="' + escHtml(item.name) + '">'
      + '<span role="cell" class="backup-date"><strong>' + escHtml(formatBackupDate(item.created)) + '</strong>'
      + '<span class="backup-ago">' + escHtml(formatRelativeDate(created)) + '</span></span>'
      + '<span role="cell" class="backup-world">' + escHtml(item.world) + '</span>'
      + '<span role="cell"><span class="backup-reason" data-reason="' + escHtml(item.reason) + '">' + escHtml(item.reason_label) + '</span></span>'
      + '<span role="cell" class="num">' + escHtml(formatBytes(item.size)) + '</span>'
      + '<span role="cell" class="backup-actions">'
      + '<a class="btn-ghost btn-xs" href="' + backupUrl(currentModpack, item.name) + '/download" download title="Descargar">' + icon('download') + '<span class="visually-hidden">Descargar</span></a>'
      + '<button class="btn-secondary btn-xs" data-action="restore">' + icon('rotate-ccw') + 'Restaurar</button>'
      + '<button class="btn-ghost btn-xs" data-action="delete" title="Borrar" aria-label="Borrar">' + icon('trash-2') + '</button>'
      + '</span></div>';
  });
  list.innerHTML = html + '</div>';
}

document.getElementById('backup-now-btn').addEventListener('click', function() {
  var btn = this;
  var modpack = currentModpack;
  backupBusy = true;
  btn.disabled = true;
  btn.innerHTML = icon('clock') + 'Copiando…';
  apiJson(backupUrl(modpack), { method: 'POST' }).then(function(result) {
    backupBusy = false;
    btn.innerHTML = icon('archive') + 'Hacer copia ahora';
    btn.disabled = false;
    if (!result.ok) {
      showToast(result.data.detail || 'No se pudo hacer la copia', 'error');
      return;
    }
    showToast('Copia hecha: ' + formatBytes(result.data.size) + ' en ' + String(result.data.seconds).replace('.', ',') + ' s', 'success');
    unlockAchievement('safe-keeper');
    if (modpack === currentModpack) {
      loadBackups();
    }
  });
});

document.getElementById('backup-list').addEventListener('click', function(event) {
  var button = event.target.closest('button[data-action]');
  var row = event.target.closest('.backup-row');
  if (!button || !row) {
    return;
  }
  var name = row.dataset.name;
  var modpack = currentModpack;
  var when = row.querySelector('.backup-date strong').textContent;
  if (button.dataset.action === 'delete') {
    showConfirm('¿Borrar esta copia?', 'La copia del ' + when + ' se borrará para siempre.', function() {
      busyWhile(button, function() {
        return apiJson(backupUrl(modpack, name), { method: 'DELETE' }).then(function(result) {
          showToast(result.ok ? 'Copia borrada' : (result.data.detail || 'No se pudo borrar'), result.ok ? 'success' : 'error');
          loadBackups();
        });
      });
    }, { confirmLabel: 'Borrar' });
    return;
  }
  showConfirm('¿Restaurar la copia del ' + when + '?',
    'El mundo actual se sustituye por el de la copia. Antes se guarda una copia del actual («Antes de restaurar»), por si quieres volver atrás. El servidor tiene que estar parado.',
    function() {
      button.disabled = true;
      button.innerHTML = icon('clock') + 'Restaurando…';
      apiJson(backupUrl(modpack, name) + '/restore', { method: 'POST' }).then(function(result) {
        if (result.ok) {
          showToast('Mundo restaurado' + (result.data.world ? ': ' + result.data.world : ''), 'success');
        } else {
          showToast(result.data.detail || 'No se pudo restaurar', 'error');
        }
        loadBackups();
      });
    }, { confirmLabel: 'Restaurar', tone: 'yellow', icon: 'rotate-ccw' });
});

// -- Clonar ------------------------------------------------------------------------
var cloneModal = document.getElementById('clone-modal');

function closeCloneModal() {
  if (!document.getElementById('clone-submit').disabled) {
    cloneModal.classList.remove('show');
  }
}

document.getElementById('btn-clone-modpack').addEventListener('click', function() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('clone-source').textContent = currentModpack;
  document.getElementById('clone-name').value = currentModpack + '_copia';
  document.getElementById('clone-world').checked = false;
  syncCloneHint();
  cloneModal.classList.add('show');
  setTimeout(function() { document.getElementById('clone-name').select(); }, 0);
});

function syncCloneHint() {
  document.getElementById('clone-hint').textContent = document.getElementById('clone-world').checked
    ? 'El mundo se copia tal como está ahora; si el servidor está encendido, el panel pausa el guardado mientras tanto.'
    : 'Sin el mundo, la copia empezará con uno nuevo la primera vez que la arranques.';
}

document.getElementById('clone-world').addEventListener('change', syncCloneHint);
document.getElementById('clone-close').addEventListener('click', closeCloneModal);
document.getElementById('clone-cancel').addEventListener('click', closeCloneModal);
cloneModal.addEventListener('click', function(event) {
  if (event.target === cloneModal) {
    closeCloneModal();
  }
});

document.getElementById('clone-form').addEventListener('submit', function(event) {
  event.preventDefault();
  var submit = document.getElementById('clone-submit');
  var source = currentModpack;
  var newName = document.getElementById('clone-name').value.trim();
  var form = new FormData();
  form.append('new_name', newName);
  form.append('include_world', document.getElementById('clone-world').checked ? '1' : '0');
  submit.disabled = true;
  submit.textContent = 'Clonando…';
  apiJson('/api/modpacks/' + encodeURIComponent(source) + '/clone', { method: 'POST', body: form }).then(function(result) {
    submit.disabled = false;
    submit.textContent = 'Clonar';
    if (!result.ok) {
      showToast(result.data.detail || 'No se pudo clonar', 'error');
      return;
    }
    cloneModal.classList.remove('show');
    showToast('«' + result.data.name + '» creado a partir de «' + source + '»', 'success');
    unlockAchievement('twins');
    loadModpacks();
    openModpack(result.data.name);
  });
});
