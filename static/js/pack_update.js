// -- Actualizar el servidor a otra versión de su modpack ---------------------------
// Diálogo #pack-update-modal (partials/modals/pack_update.html). Backend en
// routes/modpack_update.py y services/modpack_update.py.
var packUpdate = { modpack: null, info: null, selected: null, busy: false, searchSource: 'modrinth', searchTimer: null };

function packUpdateUrl(path) {
  return '/api/modpacks/' + encodeURIComponent(packUpdate.modpack) + path;
}

function setPackUpdateBody(html) {
  document.getElementById('pack-update-body').innerHTML = html;
}

function setPackUpdateFooter(state) {
  var go = document.getElementById('pack-update-go');
  go.hidden = state !== 'versions';
  go.disabled = !packUpdate.selected;
}

function openPackUpdate() {
  if (!currentModpack) {
    return;
  }
  packUpdate.modpack = currentModpack;
  packUpdate.selected = null;
  document.getElementById('pack-update-modal').classList.add('show');
  // Si ya hay una en marcha (se cerró el diálogo o se recargó la página), se sigue esa.
  apiJson(packUpdateUrl('/pack-update/running')).then(function(result) {
    if (result.ok && result.data.running) {
      runPackUpdate(true);
    } else {
      loadPackUpdateInfo();
    }
  });
}

function loadPackUpdateInfo() {
  setPackUpdateFooter('loading');
  setPackUpdateBody(modSearchSpinnerHtml(t('Buscando versiones del modpack…')));
  apiJson(packUpdateUrl('/pack-update')).then(function(result) {
    if (!result.ok) {
      setPackUpdateBody(modErrorHtml(result.data.detail || t('No se pudieron cargar las versiones')));
      setPackUpdateFooter('error');
      return;
    }
    packUpdate.info = result.data;
    if (!result.data.source) {
      renderPackLink();
    } else {
      renderPackVersions();
    }
  });
}

// -- Sin origen guardado: buscar el modpack para vincularlo -----------------------
function renderPackLink() {
  setPackUpdateFooter('link');
  setPackUpdateBody('<p class="pack-update-intro">' + t('El panel no sabe de qué modpack viene este servidor: se instaló antes de que lo guardara, o se subió a mano. Búscalo para vincularlo (solo hace falta una vez).') + '</p>'
    + '<div class="filter-row">'
    + '<select id="pack-link-source" class="btn-secondary btn-sm shrink-0">'
    + '<option value="modrinth"' + (packUpdate.searchSource === 'modrinth' ? ' selected' : '') + '>Modrinth</option>'
    + '<option value="curseforge"' + (packUpdate.searchSource === 'curseforge' ? ' selected' : '') + '>CurseForge</option>'
    + '</select>'
    + '<input type="text" id="pack-link-query" class="w-full" placeholder="' + escHtml(t('Nombre del modpack…')) + '" value="' + escHtml(packUpdate.modpack) + '">'
    + '</div><div id="pack-link-results" class="pack-link-results"></div>');
  searchPackToLink();
}

function searchPackToLink() {
  var query = document.getElementById('pack-link-query').value.trim();
  var box = document.getElementById('pack-link-results');
  packUpdate.searchSource = document.getElementById('pack-link-source').value;
  box.innerHTML = modSearchSpinnerHtml(t('Buscando…'));
  apiJson('/api/modpack-install/search?source=' + encodeURIComponent(packUpdate.searchSource) + '&query=' + encodeURIComponent(query))
    .then(function(result) {
      if (!document.getElementById('pack-link-results')) {
        return;
      }
      if (!result.ok) {
        box.innerHTML = modErrorHtml(result.data.detail || t('No se pudo buscar'));
        return;
      }
      var items = (result.data.results || []).slice(0, 8);
      if (!items.length) {
        box.innerHTML = '<p class="pack-update-intro">' + t('No se ha encontrado ningún modpack con ese nombre.') + '</p>';
        return;
      }
      box.innerHTML = items.map(function(item) {
        var img = item.icon_url ? '<img src="' + escHtml(item.icon_url) + '" alt="" loading="lazy">' : '<span class="pack-link-noimg">' + icon('package') + '</span>';
        return '<div class="pack-link-item">' + img
          + '<div class="mod-deps-info"><div class="mod-updates-name">' + escHtml(item.title || '') + '</div>'
          + '<div class="mod-deps-owners">' + escHtml(item.author || '') + '</div></div>'
          + '<button type="button" class="btn-secondary btn-sm pack-link-btn" data-id="' + escHtml(String(item.id)) + '" data-title="' + escHtml(item.title || '') + '">' + t('Es este') + '</button>'
          + '</div>';
      }).join('');
    });
}

document.getElementById('pack-update-body').addEventListener('input', function(event) {
  if (event.target.id === 'pack-link-query') {
    clearTimeout(packUpdate.searchTimer);
    packUpdate.searchTimer = setTimeout(searchPackToLink, 400);
  }
});

document.getElementById('pack-update-body').addEventListener('change', function(event) {
  if (event.target.id === 'pack-link-source') {
    searchPackToLink();
  } else if (event.target.name === 'pack-version') {
    packUpdate.selected = event.target.value;
    renderPackVersionWarning();
    setPackUpdateFooter('versions');
  }
});

document.getElementById('pack-update-body').addEventListener('click', function(event) {
  var link = event.target.closest('.pack-link-btn');
  if (link) {
    busyWhile(link, function() {
      return apiJson(packUpdateUrl('/pack-source'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: packUpdate.searchSource, project_id: link.dataset.id, title: link.dataset.title })
      }).then(function(result) {
        if (!result.ok) {
          showToast(result.data.detail || t('No se pudo vincular'), 'error');
          return;
        }
        loadPackUpdateInfo();
      });
    });
    return;
  }
  if (event.target.closest('#pack-unlink')) {
    apiJson(packUpdateUrl('/pack-source'), { method: 'DELETE' }).then(function() {
      loadPackUpdateInfo();
    });
  }
});

// -- Con origen: elegir versión ------------------------------------------------------
function packCurrentMc() {
  return (currentModpackVersion && currentModpackVersion.mc_version) || (packUpdate.info.source || {}).mc_version || null;
}

function renderPackVersions() {
  var info = packUpdate.info;
  var source = info.source;
  var installedIndex = -1;
  info.versions.forEach(function(v, i) {
    if (v.installed) {
      installedIndex = i;
    }
  });
  var rows = info.versions.slice(0, 30).map(function(v, i) {
    var badge = '';
    if (v.installed) {
      badge = '<span class="mod-updates-tag ok">' + t('instalada') + '</span>';
    } else if (installedIndex !== -1 && i > installedIndex) {
      badge = '<span class="mod-updates-tag">' + t('más antigua') + '</span>';
    }
    var disabled = v.installed || !v.downloadable;
    return '<label class="pack-version-item' + (disabled ? ' disabled' : '') + '">'
      + '<input type="radio" name="pack-version" value="' + escHtml(v.version_id) + '"' + (disabled ? ' disabled' : '') + '>'
      + '<div class="mod-deps-info"><div class="mod-updates-name">' + escHtml(v.version_number || v.version_id) + badge
      + (!v.downloadable ? '<span class="mod-updates-tag warn">' + t('sin descarga') + '</span>' : '') + '</div>'
      + '<div class="mod-deps-owners">' + escHtml((v.game_versions || []).join(', ')) + '</div></div>'
      + '</label>';
  }).join('');
  var current = source.version_number
    ? t('Versión instalada: <b>{v}</b>', { v: escHtml(source.version_number) })
    : t('Versión instalada: desconocida (vinculado a mano).');
  setPackUpdateBody('<div class="pack-update-head">'
    + '<div><div class="mod-updates-name">' + escHtml(source.title || source.project_id) + ' <span class="mod-updates-tag">' + (source.source === 'curseforge' ? 'CurseForge' : 'Modrinth') + '</span></div>'
    + '<div class="mod-deps-owners">' + current + '</div></div>'
    + '<button type="button" class="btn-ghost btn-xs" id="pack-unlink">' + t('No es este modpack') + '</button>'
    + '</div>'
    + '<div class="mod-deps-summary info">' + t('Antes se hace una copia completa del servidor. El mundo, server.properties y las listas de jugadores no se tocan; la configuración que trae el modpack se sobrescribe y los mods que añadiste tú se conservan.') + '</div>'
    + '<div id="pack-version-warning"></div>'
    + '<div class="mod-deps-list">' + (rows || '<p class="pack-update-intro">' + t('Este modpack no tiene versiones publicadas.') + '</p>') + '</div>');
  setPackUpdateFooter('versions');
}

function renderPackVersionWarning() {
  var box = document.getElementById('pack-version-warning');
  var version = packUpdate.info.versions.filter(function(v) { return v.version_id === packUpdate.selected; })[0];
  var mc = packCurrentMc();
  var notes = [];
  if (version && mc && version.game_versions.length && version.game_versions.indexOf(mc) === -1) {
    notes.push(t('Esta versión es para Minecraft {to} y el servidor está en {from}: el mundo se convertirá al arrancar y ya no se podrá abrir con {from} (salvo restaurando la copia).', {
      to: escHtml(version.game_versions.join(', ')), from: escHtml(mc)
    }));
  }
  if (!packUpdate.info.source.version_number) {
    notes.push(t('Como no se sabe qué mods eran del modpack, se quedan solo los de la versión nueva; los que desaparezcan se enumeran al final y están en la copia.'));
  }
  box.innerHTML = notes.map(function(note) { return noticeHtml('warn', note); }).join('');
}

// -- Actualizar ----------------------------------------------------------------------
document.getElementById('pack-update-go').addEventListener('click', function() {
  if (!packUpdate.selected) {
    return;
  }
  var version = packUpdate.info.versions.filter(function(v) { return v.version_id === packUpdate.selected; })[0];
  showConfirm(t('¿Actualizar a {v}?', { v: version.version_number || version.version_id }),
    t('Tardará un rato (se descarga el modpack entero). El servidor tiene que estar parado.'), function() {
      runPackUpdate(false);
    }, { confirmLabel: t('Actualizar') });
});

// attach: seguir la que ya está en marcha en vez de empezar otra. La
// actualización corre en el servidor: aunque se corte la conexión, termina.
function runPackUpdate(attach) {
  var lines = [];
  packUpdate.busy = true;
  setPackUpdateFooter('working');
  function render(extra) {
    setPackUpdateBody('<div class="log-viewer log-viewer-inline mb-s" id="pack-update-log">' + lines.map(escHtml).join('\n') + '</div>' + (extra || ''));
    var log = document.getElementById('pack-update-log');
    log.scrollTop = log.scrollHeight;
  }
  render(modSearchSpinnerHtml(t('Actualizando…')));
  if (packUpdate.source) {
    packUpdate.source.close();
  }
  var source = new EventSource(packUpdateUrl('/pack-update/stream?' + (attach ? 'attach=1' : 'version_id=' + encodeURIComponent(packUpdate.selected))));
  packUpdate.source = source;
  source.onmessage = function(event) {
    var data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (data.type === 'log') {
      lines.push(t(data.message));
      if (lines.length > 300) {
        lines.splice(0, lines.length - 300);
      }
      render(modSearchSpinnerHtml(t('Actualizando…')));
    } else if (data.type === 'done') {
      source.close();
      finishPackUpdate(data, render);
    }
  };
  source.onerror = function() {
    source.close();
    packUpdate.busy = false;
    setPackUpdateFooter('done');
    render(noticeHtml('warn', t('Se ha perdido la conexión, pero la actualización sigue en el servidor. Vuelve a abrir «Actualizar modpack» dentro de un rato para ver cómo ha terminado.')));
  };
}

function packModList(title, names) {
  if (!names || !names.length) {
    return '';
  }
  return '<details class="pack-update-mods"><summary>' + escHtml(title) + ' (' + names.length + ')</summary><ul>'
    + names.map(function(n) { return '<li><code>' + escHtml(n) + '</code></li>'; }).join('') + '</ul></details>';
}

function finishPackUpdate(data, render) {
  packUpdate.busy = false;
  setPackUpdateFooter('done');
  if (!data.success) {
    render(modErrorHtml(t(data.detail || 'Error desconocido')));
    return;
  }
  var html = noticeHtml('ok', t('Servidor actualizado a <b>{v}</b>. La copia de antes se llama «{backup}» (en Copias).', {
    v: escHtml(data.version_number || ''), backup: escHtml(data.backup || '')
  }));
  if (data.previous_mc && data.mc_version && data.previous_mc !== data.mc_version) {
    html += noticeHtml('warn', t('Minecraft ha pasado de {from} a {to}.', { from: escHtml(data.previous_mc), to: escHtml(data.mc_version) }));
  }
  html += packModList(t('Mods que cambian de versión'), (data.replaced || []).map(function(r) { return r.old + ' → ' + r.new; }))
    + packModList(t('Mods tuyos que se han conservado'), data.kept)
    + packModList(t('Mods que ya no están en esta versión'), data.removed);
  render(html);
  loadModpackVersion();
  loadModsList();
  if (typeof loadModpacks === 'function') {
    loadModpacks();
  }
  unlockAchievement('new-season');
}

// Se puede cerrar aunque esté en marcha: sigue en el servidor y al volver a
// abrir el diálogo se retoma.
function closePackUpdate() {
  if (packUpdate.source) {
    packUpdate.source.close();
    packUpdate.source = null;
  }
  document.getElementById('pack-update-modal').classList.remove('show');
}

document.getElementById('btn-update-modpack').addEventListener('click', openPackUpdate);
document.getElementById('pack-update-close').addEventListener('click', closePackUpdate);
document.getElementById('pack-update-cancel').addEventListener('click', closePackUpdate);
document.getElementById('pack-update-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closePackUpdate();
  }
});
