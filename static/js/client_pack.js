// -- Paquete para jugadores -------------------------------------------------------
// Diálogo #client-pack-modal (partials/modals/client_pack.html). Backend en
// routes/client_pack.py y services/client_pack.py: genera el modpack del
// servidor en formato CurseForge (.zip) o Modrinth (.mrpack) para que los
// jugadores lo instalen con los mismos mods que el servidor.
var clientPack = { modpack: null, data: null, poll: null };

var CLIENT_PACK_FORMATS = [
  { key: 'curseforge', name: 'CurseForge', ext: '.zip', apps: 'App de CurseForge, Prism Launcher o ATLauncher' },
  { key: 'mrpack', name: 'Modrinth', ext: '.mrpack', apps: 'Modrinth App o Prism Launcher' }
];

var CLIENT_PACK_STAGES = {
  hash: 'Leyendo los mods… ({done}/{total})',
  modrinth: 'Preguntando a Modrinth…',
  curseforge: 'Preguntando a CurseForge…',
  original: 'Descargando el modpack original…',
  write: 'Montando el paquete…'
};

function clientPackUrl(path) {
  return '/api/modpacks/' + encodeURIComponent(clientPack.modpack) + '/client-pack' + (path || '');
}

function openClientPack(modpack) {
  if (!modpack) {
    return;
  }
  clientPack.modpack = modpack;
  clientPack.data = null;
  document.getElementById('client-pack-title').textContent = '· ' + modpack;
  document.getElementById('client-pack-modal').classList.add('show');
  document.getElementById('client-pack-body').innerHTML = modSearchSpinnerHtml(t('Cargando…'));
  loadClientPack();
}

function loadClientPack() {
  clearTimeout(clientPack.poll);
  apiJson(clientPackUrl()).then(function(result) {
    if (!document.getElementById('client-pack-modal').classList.contains('show')) {
      return;
    }
    if (!result.ok) {
      document.getElementById('client-pack-body').innerHTML = modErrorHtml(result.data.detail || t('No se pudo cargar el paquete'));
      return;
    }
    showClientPack(result.data);
  });
}

function showClientPack(data) {
  clientPack.data = data;
  renderClientPack();
  var running = CLIENT_PACK_FORMATS.some(function(f) {
    var job = data.formats[f.key].job;
    return job && job.state === 'running';
  });
  if (running) {
    clientPack.poll = setTimeout(loadClientPack, 1000);
  }
}

function buildClientPack(format) {
  apiJson(clientPackUrl('?format=' + encodeURIComponent(format)), { method: 'POST' }).then(function(result) {
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo preparar el paquete'), 'error');
      return;
    }
    showClientPack(result.data);
  });
}

function clientPackNames(names) {
  var shown = names.slice(0, 8).join(', ');
  return names.length > 8 ? t('{names} y {n} más', { names: shown, n: names.length - 8 }) : shown;
}

function clientPackSummary(file) {
  var lines = [];
  if (!file.bundled.length) {
    lines.push(t('{mods} mods: todos los descarga el launcher.', { mods: file.mods }));
  } else if (!file.linked) {
    lines.push(t('{mods} mods, todos dentro del paquete.', { mods: file.mods }));
  } else {
    lines.push(t('{mods} mods: {linked} los descarga el launcher y {bundled} van dentro del paquete.',
      { mods: file.mods, linked: file.linked, bundled: file.bundled.length }));
  }
  if (file.extras) {
    lines.push(t('Y {n} cosas más del modpack original que el servidor no usa (mods solo de cliente, resource packs, shaders).', { n: file.extras }));
  }
  if (file.overrides) {
    lines.push(t('Con las configuraciones del modpack original ({n} archivos).', { n: file.overrides }));
  }
  if (file.excluded.length) {
    lines.push(t('Sin {n} mods que solo son para el servidor: {names}.', { n: file.excluded.length, names: clientPackNames(file.excluded) }));
  }
  var html = '<ul class="client-pack-summary">' + lines.map(function(line) {
    return '<li>' + escHtml(line) + '</li>';
  }).join('') + '</ul>';
  if (file.manual && file.manual.length) {
    html += noticeHtml('warn', escHtml(t('No se han podido meter y hay que instalarlos a mano: {names}.', { names: clientPackNames(file.manual) })));
  }
  if (file.original_error) {
    html += noticeHtml('warn', escHtml(t('No se ha podido usar el modpack original ({error}): el paquete lleva solo los mods del servidor.', { error: t(file.original_error) })));
  }
  return html;
}

function clientPackCard(format) {
  var entry = clientPack.data.formats[format.key];
  var file = entry.file;
  var job = entry.job;
  var running = job && job.state === 'running';
  // Solo se prepara uno a la vez por servidor (el backend no empieza otro).
  var busy = CLIENT_PACK_FORMATS.some(function(f) {
    var other = clientPack.data.formats[f.key].job;
    return other && other.state === 'running';
  });
  var status;
  if (running) {
    status = '<div class="client-pack-status">' + modSearchSpinnerHtml(t(CLIENT_PACK_STAGES[job.stage] || 'Preparando…', { done: job.done, total: job.total })) + '</div>';
  } else if (file) {
    status = '<div class="client-pack-status">' + escHtml(t('Preparado {when} · {size}', { when: formatRelativeDate(file.built_at), size: formatBytes(file.size) })) + '</div>';
    if (file.stale) {
      status += noticeHtml('warn', escHtml(t('Los mods del servidor han cambiado desde entonces: vuelve a prepararlo antes de pasarlo.')));
    }
  } else {
    status = '<div class="client-pack-status muted">' + escHtml(t('Aún no se ha preparado')) + '</div>';
  }
  if (job && job.state === 'error') {
    status += modErrorHtml(t('No se pudo preparar el paquete: {error}', { error: t(job.error || '') }));
  }
  var note = '';
  if (format.key === 'curseforge' && !clientPack.data.curseforge_key) {
    note = '<p class="client-pack-note">' + escHtml(t('CurseForge no está configurado en el panel: todos los mods irán dentro del paquete, así que pesará más.')) + '</p>';
  }
  var actions = '<div class="button-row">'
    + '<button type="button" class="btn-secondary btn-sm" data-client-pack-build="' + format.key + '"' + (busy ? ' disabled' : '') + '>'
    + icon('refresh-cw') + escHtml(file ? t('Volver a preparar') : t('Preparar')) + '</button>';
  if (file && !running) {
    actions += '<button type="button" class="btn-primary btn-sm" data-client-pack-download="' + format.key + '">'
      + icon('download') + escHtml(t('Descargar')) + '</button>';
  }
  actions += '</div>';
  var recommended = clientPack.data.recommended === format.key
    ? '<span class="mod-updates-tag ok">' + escHtml(t('Recomendado')) + '</span>' : '';
  return '<section class="client-pack-card' + (recommended ? ' recommended' : '') + '">'
    + '<div class="client-pack-head"><strong>' + escHtml(format.name) + '</strong><span class="client-pack-ext">' + format.ext + '</span>' + recommended + '</div>'
    + '<div class="client-pack-apps">' + escHtml(t(format.apps)) + '</div>'
    + note + status
    + (file && !running ? clientPackSummary(file) : '')
    + actions
    + '</section>';
}

function renderClientPack() {
  var html = '<p class="pack-update-intro">' + escHtml(t('El modpack de este servidor listo para instalarlo en tu ordenador, con los mismos mods y versiones que el servidor: así se puede entrar sin errores de mods que no coinciden. Elige el formato de tu launcher.')) + '</p>';
  if (!clientPack.data.linked) {
    html += noticeHtml('info', escHtml(t('Este servidor no está vinculado a su modpack original, así que el paquete lleva solo los mods del servidor: sin las configuraciones, los resource packs ni los mods solo de cliente del modpack. Para que vayan también, vincúlalo desde «Actualizar modpack».')));
  }
  html += '<div class="client-pack-cards">' + CLIENT_PACK_FORMATS.map(clientPackCard).join('') + '</div>';
  html += '<details class="client-pack-help"><summary>' + escHtml(t('Cómo instalarlo')) + '</summary><ul>'
    + '<li>' + escHtml(t('App de CurseForge: Crear perfil personalizado → Importar → elige el .zip.')) + '</li>'
    + '<li>' + escHtml(t('Modrinth App: arrastra el .mrpack a la ventana (o + → Importar desde archivo).')) + '</li>'
    + '<li>' + escHtml(t('Prism Launcher: Añadir instancia → Importar → elige cualquiera de los dos.')) + '</li>'
    + '</ul></details>';
  document.getElementById('client-pack-body').innerHTML = html;
}

function closeClientPack() {
  clearTimeout(clientPack.poll);
  document.getElementById('client-pack-modal').classList.remove('show');
}

document.getElementById('client-pack-body').addEventListener('click', function(event) {
  var button = event.target.closest('[data-client-pack-build]');
  if (button) {
    button.disabled = true;
    buildClientPack(button.dataset.clientPackBuild);
    return;
  }
  var download = event.target.closest('[data-client-pack-download]');
  if (download) {
    // La respuesta lleva Content-Disposition: el navegador lo baja sin salir del panel.
    window.location.href = clientPackUrl('/download?format=' + encodeURIComponent(download.dataset.clientPackDownload));
  }
});
document.getElementById('btn-client-pack').addEventListener('click', function() {
  openClientPack(currentModpack);
});
document.getElementById('hero-client-pack-btn').addEventListener('click', function() {
  openClientPack(document.getElementById('status-modpack').textContent);
});
document.getElementById('client-pack-close').addEventListener('click', closeClientPack);
document.getElementById('client-pack-cancel').addEventListener('click', closeClientPack);
document.getElementById('client-pack-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closeClientPack();
  }
});
