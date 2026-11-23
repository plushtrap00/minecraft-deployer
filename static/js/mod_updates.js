// -- Actualizaciones de los mods instalados ---------------------------------------
// Diálogo #mod-updates-modal (partials/modals/mods.html). El backend
// (services/mod_updates.py) identifica cada jar por su hash en Modrinth y
// CurseForge; aquí se enseña la lista y se actualizan de uno en uno.
var modUpdates = { modpack: null, result: null, rows: [], busy: false, poll: null, batch: null };

var MOD_UPDATE_STAGES = {
  hash: 'Leyendo los mods… ({done}/{total})',
  modrinth: 'Preguntando a Modrinth…',
  fingerprint: 'Calculando las huellas para CurseForge… ({done}/{total})',
  curseforge: 'Preguntando a CurseForge…'
};

function modUpdatesUrl(path) {
  return '/api/modpacks/' + encodeURIComponent(modUpdates.modpack) + '/mods/updates' + (path || '');
}

function setModUpdatesBody(html) {
  document.getElementById('mod-updates-body').innerHTML = html;
}

function setModUpdatesFooter(state) {
  var apply = document.getElementById('mod-updates-apply');
  apply.hidden = state !== 'list';
  document.getElementById('mod-updates-undo').hidden = state !== 'done' || !modUpdates.batch;
  document.getElementById('mod-updates-cancel').disabled = state === 'working';
  document.getElementById('mod-updates-close').style.display = state === 'working' ? 'none' : '';
  if (state === 'list') {
    updateModUpdatesApplyLabel();
  }
}

function openModUpdates() {
  if (!currentModpack) {
    return;
  }
  modUpdates.modpack = currentModpack;
  modUpdates.result = null;
  modUpdates.batch = null;
  document.getElementById('mod-updates-modal').classList.add('show');
  setModUpdatesFooter('checking');
  setModUpdatesBody(modSearchSpinnerHtml(t('Buscando actualizaciones…')));
  apiJson(modUpdatesUrl('/check'), { method: 'POST' }).then(function(result) {
    if (!result.ok) {
      setModUpdatesBody(modErrorHtml(result.data.detail || t('No se pudieron buscar actualizaciones')));
      setModUpdatesFooter('error');
      return;
    }
    followModUpdatesCheck(result.data);
  });
}

function followModUpdatesCheck(status) {
  clearTimeout(modUpdates.poll);
  if (!document.getElementById('mod-updates-modal').classList.contains('show')) {
    return;
  }
  if (status.state === 'running') {
    var text = t(MOD_UPDATE_STAGES[status.stage] || 'Buscando actualizaciones…', { done: status.done, total: status.total });
    setModUpdatesBody(modSearchSpinnerHtml(text));
    modUpdates.poll = setTimeout(function() {
      apiJson(modUpdatesUrl()).then(function(result) {
        if (result.ok) {
          followModUpdatesCheck(result.data);
        } else {
          setModUpdatesBody(modErrorHtml(result.data.detail || t('No se pudieron buscar actualizaciones')));
          setModUpdatesFooter('error');
        }
      });
    }, 700);
    return;
  }
  if (status.state === 'error') {
    setModUpdatesBody(modErrorHtml(t('No se pudieron buscar actualizaciones: {error}', { error: t(status.error || '') })));
    setModUpdatesFooter('error');
    return;
  }
  modUpdates.result = status.result;
  modUpdates.rows = status.result.updates.map(function(update) {
    return { update: update, selected: update.downloadable, state: 'ready', reason: '' };
  });
  renderModUpdates();
  setModUpdatesFooter(modUpdates.rows.length ? 'list' : 'empty');
}

function modUpdatesSummary() {
  var result = modUpdates.result;
  var n = modUpdates.rows.length;
  var notes = [];
  if (result.unknown) {
    notes.push(result.unknown === 1
      ? t('1 mod no se ha podido identificar (no está en Modrinth ni en CurseForge, o es una versión hecha a mano): ese tendrás que revisarlo tú.')
      : t('{n} mods no se han podido identificar (no están en Modrinth ni en CurseForge, o son versiones hechas a mano): esos tendrás que revisarlos tú.', { n: result.unknown }));
  }
  if (!result.curseforge) {
    notes.push(t('Solo se ha mirado en Modrinth: añade CURSEFORGE_API_KEY en Configuración para comprobar también los de CurseForge.'));
  }
  var head;
  if (!n) {
    head = '<div class="mod-deps-empty"><div class="mod-deps-empty-icon">' + icon('circle-check') + '</div>'
      + '<div class="mod-deps-empty-title">' + t('Todo al día') + '</div>'
      + '<div class="mod-deps-empty-desc">' + t('Ninguno de los {n} mods que se han reconocido tiene una versión más nueva para {mc} ({loader}).', {
        n: result.known, mc: result.mc_version || '?', loader: result.loader || '?'
      }) + '</div></div>';
  } else {
    head = '<div class="mod-deps-summary info">' + (n === 1
      ? t('Hay <b>1</b> mod con una versión más nueva para {mc} ({loader}).', { mc: escHtml(result.mc_version || '?'), loader: escHtml(result.loader || '?') })
      : t('Hay <b>{n}</b> mods con una versión más nueva para {mc} ({loader}).', { n: n, mc: escHtml(result.mc_version || '?'), loader: escHtml(result.loader || '?') }))
      + ' ' + t('Los archivos antiguos se guardan para poder deshacerlo.') + '</div>';
  }
  return head + notes.map(function(note) { return '<p class="mod-updates-note">' + escHtml(note) + '</p>'; }).join('');
}

var MOD_UPDATE_ROW_STATES = {
  working: { icon: 'download', label: 'Actualizando…' },
  done: { icon: 'circle-check', label: 'Actualizado' },
  failed: { icon: 'triangle-alert', label: 'No se ha podido' },
  skipped: { icon: 'ban', label: 'Sin tocar' }
};

function renderModUpdates() {
  var rows = modUpdates.rows.map(function(row, index) {
    var u = row.update;
    var tags = '';
    if (u.release_type && u.release_type !== 'release') {
      tags += '<span class="mod-updates-tag warn">' + escHtml(u.release_type) + '</span>';
    }
    if (u.disabled) {
      tags += '<span class="mod-updates-tag">' + t('deshabilitado') + '</span>';
    }
    tags += '<span class="mod-updates-tag">' + (u.source === 'curseforge' ? 'CurseForge' : 'Modrinth') + '</span>';
    var name = u.page_url
      ? '<a href="' + escHtml(u.page_url) + '" target="_blank" rel="noopener noreferrer">' + escHtml(u.name) + '</a>'
      : escHtml(u.name);
    var side;
    if (row.state === 'ready') {
      side = u.downloadable
        ? '<input type="checkbox" class="mod-updates-check" data-index="' + index + '"' + (row.selected ? ' checked' : '') + ' aria-label="' + escHtml(t('Actualizar {name}', { name: u.name })) + '">'
        : '<span class="mod-deps-badge" title="' + escHtml(t('El autor no permite descargarlo desde otras aplicaciones: actualízalo a mano desde su página')) + '">' + t('Solo a mano') + '</span>';
    } else {
      var st = MOD_UPDATE_ROW_STATES[row.state];
      side = '<span class="mod-deps-badge ' + row.state + '">' + icon(st.icon) + t(st.label) + '</span>';
    }
    return '<div class="mod-updates-item ' + row.state + '">'
      + '<div class="mod-deps-info"><div class="mod-updates-name">' + name + tags + '</div>'
      + '<div class="mod-updates-versions"><span>' + escHtml(u.current_version || u.filename) + '</span> → <b>' + escHtml(u.new_version || u.new_filename) + '</b></div>'
      + (row.reason ? '<div class="mod-deps-reason">' + escHtml(t(row.reason)) + '</div>' : '')
      + '</div>' + side + '</div>';
  }).join('');
  var selectAll = '';
  if (modUpdates.rows.some(function(row) { return row.state === 'ready' && row.update.downloadable; })) {
    var all = modUpdates.rows.every(function(row) { return !row.update.downloadable || row.selected; });
    selectAll = '<label class="mod-updates-all"><input type="checkbox" id="mod-updates-all"' + (all ? ' checked' : '') + '> ' + t('Seleccionar todos') + '</label>';
  }
  setModUpdatesBody(modUpdatesSummary() + selectAll + '<div class="mod-deps-list">' + rows + '</div>');
}

function updateModUpdatesApplyLabel() {
  var n = modUpdates.rows.filter(function(row) { return row.selected && row.state === 'ready'; }).length;
  var apply = document.getElementById('mod-updates-apply');
  apply.disabled = !n;
  apply.textContent = n === 1 ? t('Actualizar 1 mod') : t('Actualizar {n} mods', { n: n });
}

document.getElementById('mod-updates-body').addEventListener('change', function(event) {
  if (event.target.id === 'mod-updates-all') {
    modUpdates.rows.forEach(function(row) {
      if (row.update.downloadable) {
        row.selected = event.target.checked;
      }
    });
    renderModUpdates();
  } else if (event.target.classList.contains('mod-updates-check')) {
    modUpdates.rows[Number(event.target.dataset.index)].selected = event.target.checked;
    var all = document.getElementById('mod-updates-all');
    if (all) {
      all.checked = modUpdates.rows.every(function(row) { return !row.update.downloadable || row.selected; });
    }
  }
  updateModUpdatesApplyLabel();
});

// De uno en uno: con muchos mods, una sola petición larga podría cortarla un
// proxy, y así se ve el progreso fila a fila.
function applyModUpdates() {
  var queue = modUpdates.rows.filter(function(row) { return row.selected && row.state === 'ready'; });
  if (!queue.length) {
    return;
  }
  modUpdates.rows.forEach(function(row) {
    if (row.state === 'ready' && !row.selected) {
      row.state = 'skipped';
    }
  });
  modUpdates.busy = true;
  setModUpdatesFooter('working');
  var done = 0;
  var failed = 0;

  function next() {
    var row = queue.shift();
    if (!row) {
      finish();
      return;
    }
    row.state = 'working';
    renderModUpdates();
    apiJson(modUpdatesUrl('/apply'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: row.update.filename })
    }).then(function(result) {
      if (result.ok) {
        row.state = 'done';
        modUpdates.batch = result.data.batch;
        done++;
      } else {
        row.state = 'failed';
        row.reason = result.data.detail || t('Error desconocido');
        failed++;
      }
      next();
    });
  }

  function finish() {
    modUpdates.busy = false;
    renderModUpdates();
    var summary;
    if (!failed) {
      summary = '<div class="mod-deps-summary ok">' + (done === 1 ? t('Se ha actualizado 1 mod.') : t('Se han actualizado {n} mods.', { n: done }));
    } else {
      summary = '<div class="mod-deps-summary warn">' + t('{ok} actualizados y {failed} sin poder actualizar (el motivo está en cada uno).', { ok: done, failed: failed });
    }
    if (serverRunning && done) {
      summary += ' ' + t('Se cargarán la próxima vez que arranque el servidor.');
    }
    summary += '</div>';
    document.getElementById('mod-updates-body').insertAdjacentHTML('afterbegin', summary);
    setModUpdatesFooter('done');
    loadModsList();
    if (done >= 10) {
      unlockAchievement('tune-up');
    }
  }

  next();
}

document.getElementById('mod-updates-apply').addEventListener('click', applyModUpdates);

document.getElementById('mod-updates-undo').addEventListener('click', function() {
  var button = this;
  showConfirm(t('¿Deshacer las actualizaciones?'), t('Se vuelven a poner los archivos que había antes y se quitan los nuevos.'), function() {
    busyWhile(button, function() {
      return apiJson(modUpdatesUrl('/undo'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch: modUpdates.batch })
      }).then(function(result) {
        if (!result.ok) {
          showToast(result.data.detail || t('No se pudo deshacer'), 'error');
          return;
        }
        var n = (result.data.restored || []).length;
        showToast(n === 1 ? t('Se ha vuelto a la versión anterior de 1 mod') : t('Se ha vuelto a la versión anterior de {n} mods', { n: n }), 'success');
        modUpdates.batch = null;
        loadModsList();
        closeModUpdates(true);
      });
    });
  }, { confirmLabel: t('Deshacer') });
});

function closeModUpdates(force) {
  if (modUpdates.busy && !force) {
    return;
  }
  clearTimeout(modUpdates.poll);
  document.getElementById('mod-updates-modal').classList.remove('show');
}

document.getElementById('mod-updates-btn').addEventListener('click', openModUpdates);
document.getElementById('mod-updates-close').addEventListener('click', function() { closeModUpdates(); });
document.getElementById('mod-updates-cancel').addEventListener('click', function() { closeModUpdates(); });
document.getElementById('mod-updates-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closeModUpdates();
  }
});
