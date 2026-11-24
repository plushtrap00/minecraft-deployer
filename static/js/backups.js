// -- Modpacks → Copias: copias del mundo o completas y clonar el modpack ------
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
      list.innerHTML = noticeHtml('error', escHtml(result.data.detail || t('No se pudieron cargar las copias.')));
      return;
    }
    renderBackups(result.data);
  });
}

function formatBackupDate(iso) {
  var date = new Date(iso);
  return date.toLocaleString(APP_LOCALE, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// Espacio libre y destino secundario, encima de la lista.
function renderBackupDisk(data) {
  var html = '';
  var disk = data.disk;
  if (disk && disk.low) {
    html += noticeHtml('warn', escHtml(t('Queda poco espacio en el disco de las copias: {free} libres de {total}. Borra copias antiguas o elige un destino secundario en Automatización.', {
      free: formatBytes(disk.free), total: formatBytes(disk.total)
    })));
  }
  var mirror = data.mirror;
  if (mirror && mirror.configured && (!mirror.available || mirror.last_error)) {
    html += noticeHtml('error', escHtml(mirror.available
      ? t('No se pudieron llevar las copias al destino secundario: {error}', { error: mirror.last_error })
      : t('El destino secundario ({path}) no está disponible: comprueba que el disco o la carpeta de red está montado.', { path: mirror.path })));
  }
  document.getElementById('backup-disk').innerHTML = html ? '<div class="mt-m">' + html + '</div>' : '';
}

function backupWhereHtml(item, mirrorOn) {
  if (!item.local) {
    return '<span class="backup-where only-mirror" title="' + escHtml(t('La copia del disco principal ya no está; esta es la del destino secundario.')) + '">'
      + icon('hard-drive') + escHtml(t('Solo en el destino secundario')) + '</span>';
  }
  if (mirrorOn) {
    return item.mirrored
      ? '<span class="backup-where">' + icon('hard-drive') + escHtml(t('También en el destino secundario')) + '</span>'
      : '<span class="backup-where">' + icon('clock') + escHtml(t('Pendiente de llevar al destino secundario')) + '</span>';
  }
  return '';
}

function renderBackups(data) {
  var list = document.getElementById('backup-list');
  document.getElementById('backup-now-btn').disabled = !data.has_world || backupBusy;
  document.getElementById('backup-full-btn').disabled = backupBusy;
  renderBackupDisk(data);
  var mirrorOn = !!(data.mirror && data.mirror.configured);
  if (!data.backups.length) {
    list.innerHTML = data.has_world
      ? emptyArt('chest', t('Aún no hay copias'), t('Haz la primera ahora: tarda poco y te puede salvar el mundo.'), '', true)
      : emptyArt('map', t('No hay mundo que copiar'), t('Este servidor todavía no tiene mundo. Se crea la primera vez que lo arrancas.'), '', true);
    return;
  }
  var total = data.backups.reduce(function(sum, item) { return sum + item.size; }, 0);
  var summary = data.backups.length === 1
    ? t('1 copia, {size} en total', { size: formatBytes(total) })
    : t('{n} copias, {size} en total', { n: data.backups.length, size: formatBytes(total) });
  if (data.disk) {
    summary += ' · ' + t('{free} libres en el disco', { free: formatBytes(data.disk.free) });
  }
  if (mirrorOn) {
    summary += ' · ' + t('se duplican en {path}', { path: data.mirror.path });
  }
  var html = '<div class="backup-summary">' + escHtml(summary) + '</div>'
    + '<div class="backup-table" role="table" aria-label="' + t('Copias de seguridad') + '">'
    + '<div class="backup-row backup-row-head" role="row"><span role="columnheader">' + t('Fecha') + '</span><span role="columnheader">' + t('Mundo') + '</span>'
    + '<span role="columnheader">' + t('Tipo') + '</span><span role="columnheader" class="num">' + t('Tamaño') + '</span><span role="columnheader"><span class="visually-hidden">' + t('Acciones') + '</span></span></div>';
  data.backups.forEach(function(item) {
    var created = new Date(item.created).getTime() / 1000;
    html += '<div class="backup-row" role="row" data-name="' + escHtml(item.name) + '" data-kind="' + escHtml(item.kind) + '">'
      + '<span role="cell" class="backup-date"><strong>' + escHtml(formatBackupDate(item.created)) + '</strong>'
      + '<span class="backup-ago">' + escHtml(formatRelativeDate(created)) + '</span>' + backupWhereHtml(item, mirrorOn) + '</span>'
      + '<span role="cell" class="backup-world">' + escHtml(item.world) + '</span>'
      + '<span role="cell"><span class="backup-reason" data-reason="' + escHtml(item.reason) + '">' + escHtml(t(item.reason_label)) + '</span>'
      + (item.kind === 'full' ? '<span class="backup-kind" title="' + escHtml(t('Mods, configuración y mundo')) + '">' + escHtml(t(item.kind_label)) + '</span>' : '') + '</span>'
      + '<span role="cell" class="num">' + escHtml(formatBytes(item.size)) + '</span>'
      + '<span role="cell" class="backup-actions">'
      + '<a class="btn-ghost btn-xs" href="' + backupUrl(currentModpack, item.name) + '/download" download title="' + t('Descargar') + '">' + icon('download') + '<span class="visually-hidden">' + t('Descargar') + '</span></a>'
      + '<button type="button" class="btn-secondary btn-xs" data-action="restore">' + icon('rotate-ccw') + t('Restaurar') + '</button>'
      + '<button type="button" class="btn-ghost btn-xs" data-action="delete" title="' + t('Borrar') + '" aria-label="' + t('Borrar') + '">' + icon('trash-2') + '</button>'
      + '</span></div>';
  });
  list.innerHTML = html + '</div>';
}

function makeBackup(btn, kind) {
  var modpack = currentModpack;
  var label = btn.innerHTML;
  var form = new FormData();
  form.append('kind', kind);
  backupBusy = true;
  document.getElementById('backup-now-btn').disabled = true;
  document.getElementById('backup-full-btn').disabled = true;
  btn.innerHTML = icon('clock') + t('Copiando…');
  apiJson(backupUrl(modpack), { method: 'POST', body: form }).then(function(result) {
    backupBusy = false;
    btn.innerHTML = label;
    document.getElementById('backup-now-btn').disabled = false;
    document.getElementById('backup-full-btn').disabled = false;
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo hacer la copia'), 'error');
      return;
    }
    showToast(t('Copia hecha: {size} en {seconds} s', { size: formatBytes(result.data.size), seconds: Number(result.data.seconds).toLocaleString(APP_LOCALE) }), 'success');
    unlockAchievement('safe-keeper');
    if (kind === 'full') {
      unlockAchievement('time-capsule');
    }
    if (modpack === currentModpack) {
      loadBackups();
    }
  });
}

document.getElementById('backup-now-btn').addEventListener('click', function() {
  makeBackup(this, 'world');
});

document.getElementById('backup-full-btn').addEventListener('click', function() {
  makeBackup(this, 'full');
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
    showConfirm(t('¿Borrar esta copia?'), t('La copia del {when} se borrará para siempre.', { when: when }), function() {
      busyWhile(button, function() {
        return apiJson(backupUrl(modpack, name), { method: 'DELETE' }).then(function(result) {
          showToast(result.ok ? t('Copia borrada') : (result.data.detail || t('No se pudo borrar')), result.ok ? 'success' : 'error');
          loadBackups();
        });
      });
    }, { confirmLabel: t('Borrar') });
    return;
  }
  var full = row.dataset.kind === 'full';
  showConfirm(t('¿Restaurar la copia del {when}?', { when: when }),
    full
      ? t('Los mods, la configuración, los scripts y el mundo se sustituyen por los de la copia. Antes se guarda una copia completa del estado actual («Antes de restaurar»), por si quieres volver atrás. El servidor tiene que estar parado.')
      : t('El mundo actual se sustituye por el de la copia. Antes se guarda una copia del actual («Antes de restaurar»), por si quieres volver atrás. El servidor tiene que estar parado.'),
    function() {
      button.disabled = true;
      button.innerHTML = icon('clock') + t('Restaurando…');
      apiJson(backupUrl(modpack, name) + '/restore', { method: 'POST' }).then(function(result) {
        if (result.ok && result.data.kind === 'full') {
          showToast(t('Servidor restaurado tal como estaba en la copia'), 'success');
        } else if (result.ok) {
          showToast(result.data.world ? t('Mundo restaurado: {world}', { world: result.data.world }) : t('Mundo restaurado'), 'success');
        } else {
          showToast(result.data.detail || t('No se pudo restaurar'), 'error');
        }
        loadBackups();
      });
    }, { confirmLabel: t('Restaurar'), tone: 'yellow', icon: 'rotate-ccw' });
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
    ? t('El mundo se copia tal como está ahora; si el servidor está encendido, el panel pausa el guardado mientras tanto.')
    : t('Sin el mundo, la copia empezará con uno nuevo la primera vez que la arranques.');
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
  submit.textContent = t('Clonando…');
  apiJson('/api/modpacks/' + encodeURIComponent(source) + '/clone', { method: 'POST', body: form }).then(function(result) {
    submit.disabled = false;
    submit.textContent = t('Clonar');
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo clonar'), 'error');
      return;
    }
    cloneModal.classList.remove('show');
    showToast(t('«{name}» creado a partir de «{source}»', { name: result.data.name, source: source }), 'success');
    unlockAchievement('twins');
    loadModpacks();
    openModpack(result.data.name);
  });
});
