// -- Mods que trae un modpack, antes de instalarlo -----------------------------
// Botón «Ver mods» del paso 2 de «Descargar modpack» (modpack_install.js lo
// actualiza con el recuento que devuelve la comprobación de duplicados). La
// lista sale de GET /api/modpack-install/mods, que lee el índice del pack sin
// bajar ningún mod y dice qué haría la instalación con cada uno.
var packModsState = { items: [], filter: 'all', query: '', token: 0 };

var PACK_MOD_STATUS = {
  client_only: [t('Solo cliente'), t('El propio mod indica que no funciona en un servidor: no se instala.')],
  not_in_server_pack: [t('Solo cliente'), t('El autor no lo incluye en su Server Pack: es un mod para los jugadores, el servidor no lo necesita.')],
  known_bad: [t('Rompe el servidor'), t('Se sabe que hace caer un servidor dedicado: no se instala.')],
  blocked: [t('A mano'), t('El autor no deja descargarlo desde otras aplicaciones: tendrás que subirlo tú después de instalar.')],
  not_needed: [t('No hace falta'), t('No es un mod (resource pack, shader…): el servidor no lo usa.')],
  unresolved: [t('No encontrado'), t('CurseForge ya no tiene este archivo.')]
};

var PACK_MOD_KINDS = { resourcepack: t('Resource pack'), shader: t('Shader'), datapack: t('Datapack'), other: t('Otro') };

// state: 'hidden' | 'loading' | 'ready'. summary: {mods, install, total} o null.
function setDlPackModsButton(state, summary) {
  var btn = document.getElementById('dl-pack-mods-btn');
  var label = document.getElementById('dl-pack-mods-btn-label');
  btn.hidden = state === 'hidden';
  btn.disabled = state === 'loading';
  if (state === 'loading') {
    label.textContent = t('Contando mods…');
  } else if (summary && summary.mods) {
    label.textContent = summary.mods === 1 ? t('Ver el mod que trae') : t('Ver los {n} mods que trae', { n: summary.mods.toLocaleString(APP_LOCALE) });
  } else {
    label.textContent = t('Ver mods');
  }
}

function packModSkipped(item) {
  return item.status !== 'install';
}

function packModsUrl(pack, versionId) {
  return '/api/modpack-install/mods?source=' + encodeURIComponent(pack.source)
    + '&project_id=' + encodeURIComponent(pack.id) + '&version_id=' + encodeURIComponent(versionId);
}

function openPackModsModal() {
  var versionSelect = document.getElementById('dl-version-select');
  var versionId = versionSelect.value;
  if (!dlSelectedPack || !versionId) {
    return;
  }
  var option = versionSelect.options[versionSelect.selectedIndex];
  var versionLabel = option ? option.textContent.replace(/\s*\(.*$/, '') : '';
  document.getElementById('pack-mods-title').textContent = (dlSelectedPack.title || t('Modpack')) + (versionLabel ? ' · ' + versionLabel : '');
  document.getElementById('pack-mods-summary').innerHTML = '';
  document.getElementById('pack-mods-filter').value = '';
  packModsState.items = [];
  packModsState.query = '';
  setPackModsFilter('all');
  var body = document.getElementById('pack-mods-body');
  body.innerHTML = modSearchSpinnerHtml(t('Abriendo el modpack…'));
  document.getElementById('pack-mods-modal').classList.add('show');

  var token = ++packModsState.token;
  apiFetch(packModsUrl(dlSelectedPack, versionId))
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      if (token !== packModsState.token) {
        return;
      }
      if (!result.ok) {
        body.innerHTML = modErrorHtml(result.data.detail || t('No se pudo leer el modpack'));
        return;
      }
      packModsState.items = result.data.mods || [];
      packModsState.serverPack = result.data.server_pack || null;
      renderPackModsSummary();
      renderPackMods();
    })
    .catch(function(error) {
      if (token === packModsState.token) {
        body.innerHTML = modErrorHtml(t('No se pudo conectar con el panel: {error}', { error: error.message }));
      }
    });
}

function renderPackModsSummary() {
  var items = packModsState.items;
  var mods = items.filter(function(m) { return m.kind === 'mod'; });
  var installing = mods.filter(function(m) { return m.status === 'install'; }).length;
  var skipped = items.filter(packModSkipped).length;
  var extras = items.filter(function(m) { return m.kind !== 'mod' && m.status === 'install'; }).length;
  var parts = [installing === 1
    ? t('<b>1</b> mod se instala en el servidor')
    : t('<b>{n}</b> mods se instalan en el servidor', { n: installing.toLocaleString(APP_LOCALE) })];
  if (extras) {
    parts.push(extras === 1
      ? t('<b>1</b> archivo más (resource packs, shaders…)')
      : t('<b>{n}</b> archivos más (resource packs, shaders…)', { n: extras }));
  }
  if (skipped) {
    parts.push(skipped === 1 ? t('<b>1</b> no se instala') : t('<b>{n}</b> no se instalan', { n: skipped }));
  }
  document.getElementById('pack-mods-summary').innerHTML = parts.join(' · ');

  var counts = { all: items.length, install: items.length - skipped, skip: skipped };
  Array.prototype.forEach.call(document.querySelectorAll('#pack-mods-tabs .segmented-btn'), function(btn) {
    var base = btn.dataset.label || btn.textContent;
    btn.dataset.label = base;
    btn.innerHTML = escHtml(base) + ' <span class="seg-count">' + counts[btn.dataset.filter] + '</span>';
  });
}

function packModRowHtml(item) {
  var slot = '<span class="search-slot pack-mod-slot">'
    + (isWebUrl(item.icon_url)
      ? '<img class="mod-search-icon" src="' + escHtml(item.icon_url) + '" alt="" loading="lazy" decoding="async">'
      : '<span class="mod-search-icon mod-search-icon-empty">' + icon(item.kind === 'mod' ? 'puzzle' : 'package') + '</span>')
    + '</span>';
  var name = isWebUrl(item.page_url)
    ? '<a href="' + escHtml(item.page_url) + '" target="_blank" rel="noopener" title="' + t('Ver la página del mod') + '">' + escHtml(item.name) + '</a>'
    : escHtml(item.name);
  var tags = '';
  if (PACK_MOD_KINDS[item.kind]) {
    tags += '<span class="search-chip">' + PACK_MOD_KINDS[item.kind] + '</span>';
  }
  if (item.embedded) {
    tags += '<span class="search-chip" title="' + t('Viene dentro del propio modpack, no se descarga aparte') + '">' + t('Incluido en el pack') + '</span>';
  }
  var status = PACK_MOD_STATUS[item.status];
  if (status) {
    tags += '<span class="pack-mod-status" data-status="' + item.status + '" title="' + escHtml(status[1]) + '">' + status[0] + '</span>';
  }
  var size = item.size ? '<span class="pack-mod-size">' + formatBytes(item.size) + '</span>' : '';
  return '<div class="pack-mod-row' + (packModSkipped(item) ? ' is-skipped' : '') + '"'
    + (item.description ? ' title="' + escHtml(item.description) + '"' : '') + '>'
    + slot
    + '<div class="pack-mod-info"><div class="pack-mod-name">' + name + '</div>'
    + (item.filename ? '<div class="pack-mod-file">' + escHtml(item.filename) + '</div>' : '')
    + '</div>'
    + (tags ? '<div class="pack-mod-tags">' + tags + '</div>' : '')
    + size
    + '</div>';
}

function renderPackMods() {
  var body = document.getElementById('pack-mods-body');
  var query = packModsState.query;
  var filter = packModsState.filter;
  var visible = packModsState.items.filter(function(item) {
    if (filter === 'install' && packModSkipped(item)) {
      return false;
    }
    if (filter === 'skip' && !packModSkipped(item)) {
      return false;
    }
    return !query
      || (item.name || '').toLowerCase().indexOf(query) !== -1
      || (item.filename || '').toLowerCase().indexOf(query) !== -1;
  });
  var notice = '';
  if (packModsState.serverPack === 'exact') {
    notice = '<div class="mb-s">' + noticeHtml('info', t('Esta versión trae «Server Files» oficiales, así que se instala ese paquete tal cual: esta es su lista de mods.')) + '</div>';
  } else if (packModsState.serverPack === 'approx') {
    notice = '<div class="mb-s">' + noticeHtml('info', t('Esta versión trae «Server Files» oficiales y se instalará ese paquete, pero no se ha podido leer su contenido: esta lista es la del modpack completo y el servidor puede llevar algunos mods menos (los de cliente).')) + '</div>';
  }
  if (!visible.length) {
    body.innerHTML = notice + (packModsState.items.length
      ? emptyArt('spyglass', t('Nada por aquí'), query ? t('Ningún mod coincide con «{query}».', { query: query }) : t('No hay nada en este grupo.'))
      : emptyArt('spyglass', t('Modpack vacío'), t('Esta versión no trae mods.')));
    return;
  }
  body.innerHTML = notice + '<div class="pack-mod-list">' + visible.map(packModRowHtml).join('') + '</div>';
}

function setPackModsFilter(filter) {
  packModsState.filter = filter;
  Array.prototype.forEach.call(document.querySelectorAll('#pack-mods-tabs .segmented-btn'), function(btn) {
    var active = btn.dataset.filter === filter;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

document.getElementById('pack-mods-tabs').addEventListener('click', function(event) {
  var btn = event.target.closest('.segmented-btn');
  if (!btn) {
    return;
  }
  setPackModsFilter(btn.dataset.filter);
  if (packModsState.items.length) {
    renderPackMods();
  }
});

document.getElementById('pack-mods-filter').addEventListener('input', function() {
  packModsState.query = this.value.trim().toLowerCase();
  if (packModsState.items.length) {
    renderPackMods();
  }
});

document.getElementById('dl-pack-mods-btn').addEventListener('click', openPackModsModal);

function closePackModsModal() {
  packModsState.token++; // si aún estaba cargando, su respuesta ya no pinta nada
  document.getElementById('pack-mods-modal').classList.remove('show');
}

document.getElementById('pack-mods-close').addEventListener('click', closePackModsModal);
document.getElementById('pack-mods-close2').addEventListener('click', closePackModsModal);
document.getElementById('pack-mods-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closePackModsModal();
  }
});
