// -- Pregenerar el mundo ---------------------------------------------------------
// Diálogo #pregen-modal (partials/modals/pregen.html). Backend en
// routes/pregen.py y services/pregen.py: instala Chunky si se pide, calcula
// el disco con los datos del propio mundo y lleva la tarea por la consola.
var pregen = { modpack: null, data: null, available: null, poll: null, estimateTimer: null, justInstalled: false };

var PREGEN_DIMENSIONS = {
  'minecraft:overworld': 'Overworld',
  'minecraft:the_nether': 'Nether',
  'minecraft:the_end': 'End'
};
var PREGEN_RADII = [1000, 2000, 3000, 5000];

function pregenUrl(path) {
  return '/api/modpacks/' + encodeURIComponent(pregen.modpack) + '/pregen' + (path || '');
}

function openPregen(modpack) {
  if (!modpack) {
    return;
  }
  pregen.modpack = modpack;
  pregen.data = null;
  pregen.available = null;
  pregen.justInstalled = false;
  document.getElementById('pregen-title').textContent = '· ' + modpack;
  document.getElementById('pregen-modal').classList.add('show');
  document.getElementById('pregen-body').innerHTML = modSearchSpinnerHtml(t('Cargando…'));
  document.getElementById('pregen-footer-left').innerHTML = '';
  loadPregen();
}

function pregenOpen() {
  return document.getElementById('pregen-modal').classList.contains('show');
}

function pregenActive(state) {
  return state && ['running', 'paused_players', 'waiting'].indexOf(state.status) !== -1;
}

function loadPregen() {
  clearTimeout(pregen.poll);
  apiJson(pregenUrl()).then(function(result) {
    if (!pregenOpen()) {
      return;
    }
    if (!result.ok) {
      document.getElementById('pregen-body').innerHTML = modErrorHtml(result.data.detail || t('No se pudo cargar'));
      return;
    }
    pregen.data = result.data;
    if (!result.data.chunky.filename && !pregen.available) {
      loadPregenAvailable();
    }
    renderPregen();
    if (pregenActive(result.data.state)) {
      pregen.poll = setTimeout(loadPregen, 5000);
    }
  });
}

function loadPregenAvailable() {
  apiJson(pregenUrl('/available')).then(function(result) {
    pregen.available = result.ok ? result.data : { ok: false, reason: result.data.detail || t('No se pudo consultar Modrinth') };
    if (pregenOpen()) {
      renderPregen();
    }
  });
}

function pregenDimName(dim) {
  return PREGEN_DIMENSIONS[dim] || dim;
}

function pregenInstallHtml() {
  var available = pregen.available;
  if (!available) {
    return modSearchSpinnerHtml(t('Buscando Chunky para este servidor…'));
  }
  if (!available.ok) {
    return noticeHtml('info', escHtml(t('No se puede pregenerar este servidor: {reason}', { reason: t(available.reason) })));
  }
  return '<div class="pregen-install">'
    + '<p>' + escHtml(t('Para pregenerar hace falta el mod Chunky (de pop4959, licencia GPL-3.0). Solo va en el servidor: los jugadores no lo necesitan y el paquete para jugadores no lo lleva.')) + '</p>'
    + '<p class="muted">' + escHtml(t('Se descargará Chunky {version} de Modrinth en la carpeta mods y se cargará la próxima vez que arranque el servidor. Puedes quitarlo cuando quieras desde aquí.', { version: available.version })) + '</p>'
    + (available.dependencies && available.dependencies.length
      ? '<p class="muted">' + escHtml(t('También necesita {mods}, que se instalará con él. Ese se queda aunque luego quites Chunky, porque otros mods pueden usarlo.', {
        mods: available.dependencies.map(function(dep) { return dep.title; }).join(', ')
      })) + '</p>'
      : '')
    + '<div class="button-row"><button type="button" class="btn-primary btn-sm" id="pregen-install">' + icon('download') + escHtml(t('Instalar Chunky')) + '</button></div>'
    + '</div>';
}

function pregenStatusText(state, data) {
  if (state.status === 'running') {
    return t('Pregenerando {dimension}…', { dimension: pregenDimName(state.current) });
  }
  if (state.status === 'paused_players') {
    return t('En pausa: hay jugadores conectados. Seguirá sola cuando se vayan.');
  }
  return data.server_running
    ? t('Empezará en cuanto el servidor termine de arrancar.')
    : t('Esperando a que arranque el servidor: seguirá sola entonces.');
}

function pregenProgressHtml(data) {
  var state = data.state;
  var progress = state.progress || {};
  var html = '<div class="pregen-progress">'
    + '<div class="pregen-progress-head"><strong>' + escHtml(pregenStatusText(state, data)) + '</strong>'
    + (typeof progress.percent === 'number' && state.current ? '<span>' + escHtml(progress.percent.toFixed(1)) + ' %</span>' : '') + '</div>'
    + '<div class="progress-wrap"><div class="progress-fill" id="pregen-fill"></div></div>';
  var facts = [];
  if (progress.chunks) {
    facts.push(t('{n} chunks', { n: progress.chunks.toLocaleString() }));
  }
  if (progress.rate) {
    facts.push(t('{n} chunks/s', { n: Math.round(progress.rate) }));
  }
  if (progress.eta_seconds) {
    facts.push(t('quedan unos {time}', { time: formatUptime(progress.eta_seconds) }));
  }
  if (facts.length) {
    html += '<div class="pregen-facts">' + escHtml(facts.join(' · ')) + '</div>';
  }
  var dims = state.dimensions.map(function(dim) {
    var done = (state.done || []).some(function(d) { return d.dimension === dim; });
    var mark = done ? '✓ ' : (dim === state.current ? '▸ ' : '');
    return mark + pregenDimName(dim);
  });
  html += '<div class="pregen-facts">' + escHtml(t('Radio de {radius} bloques: {dimensions}', { radius: state.radius, dimensions: dims.join(', ') })) + '</div>';
  if (state.only_when_empty) {
    html += '<div class="pregen-facts">' + escHtml(t('Solo con el servidor vacío: se pausa cuando entra alguien.')) + '</div>';
  }
  html += '<div class="button-row"><button type="button" class="btn-danger btn-sm" id="pregen-stop">' + icon('x') + escHtml(t('Cancelar pregeneración')) + '</button></div>'
    + '</div>';
  return html;
}

function pregenLastHtml(state) {
  if (!state || !state.status) {
    return '';
  }
  if (state.status === 'done') {
    var total = (state.done || []).reduce(function(sum, d) { return sum + d.chunks; }, 0);
    return noticeHtml('ok', escHtml(t('Última pregeneración terminada {when}: {n} chunks con radio de {radius} bloques.',
      { when: formatRelativeDate(state.finished_at), n: total.toLocaleString(), radius: state.radius })));
  }
  if (state.status === 'cancelled') {
    return noticeHtml('info', escHtml(t('La última pregeneración se canceló {when}.', { when: formatRelativeDate(state.finished_at) })));
  }
  if (state.status === 'error') {
    return noticeHtml('warn', escHtml(t('La última pregeneración se paró: {error}', { error: t(state.error || '') })));
  }
  return '';
}

function pregenFormHtml(data) {
  var radii = PREGEN_RADII.map(function(r) {
    return '<option value="' + r + '"' + (r === 2000 ? ' selected' : '') + '>' + escHtml(t('{n} bloques', { n: r.toLocaleString() })) + '</option>';
  }).join('') + '<option value="custom">' + escHtml(t('Otro…')) + '</option>';
  var dims = data.dimensions.map(function(dim) {
    return '<label class="pregen-check"><input type="checkbox" data-pregen-dim="' + escHtml(dim) + '"' + (dim === 'minecraft:overworld' ? ' checked' : '') + '> ' + escHtml(pregenDimName(dim)) + '</label>';
  }).join('');
  var html = pregenLastHtml(data.state)
    + '<div class="props-grid pregen-form">'
    + '<div class="prop-field"><label class="prop-label" for="pregen-radius">' + escHtml(t('Radio alrededor del spawn')) + '</label>'
    + '<select id="pregen-radius">' + radii + '</select>'
    + '<input type="number" id="pregen-radius-custom" min="' + data.limits.min + '" max="' + data.limits.max + '" step="100" value="2000" hidden></div>'
    + '<div class="prop-field"><span class="prop-label">' + escHtml(t('Dimensiones')) + '</span><div class="pregen-checks">' + dims + '</div></div>'
    + '</div>'
    + '<label class="pregen-check"><input type="checkbox" id="pregen-only-empty" checked> ' + escHtml(t('Solo con el servidor vacío (se pausa cuando entra alguien y sigue cuando se va)')) + '</label>'
    + '<div id="pregen-estimate" class="pregen-estimate"></div>';
  if (data.low_ram) {
    html += noticeHtml('warn', escHtml(t('Al equipo le queda poca memoria libre. Pregenerar exige mucho al servidor: mejor con el servidor vacío.')));
  }
  if (pregen.justInstalled && data.server_running) {
    html += noticeHtml('info', escHtml(t('Chunky se cargará cuando reinicies el servidor; hasta entonces la tarea esperará.')));
  }
  html += '<div class="button-row"><button type="button" class="btn-primary btn-sm" id="pregen-start">' + icon('play') + escHtml(t('Empezar a pregenerar')) + '</button></div>';
  return html;
}

function renderPregen() {
  var data = pregen.data;
  var html = '<p class="pack-update-intro">' + escHtml(t('Genera de antemano el terreno alrededor del spawn. Luego, explorar no obliga al servidor a crear el mundo sobre la marcha: menos tirones y menos riesgo de que se cuelgue generando.')) + '</p>';
  if (!data.chunky.filename) {
    html += pregenInstallHtml();
  } else if (pregenActive(data.state)) {
    html += pregenProgressHtml(data);
  } else {
    html += pregenFormHtml(data);
  }
  document.getElementById('pregen-body').innerHTML = html;
  var fill = document.getElementById('pregen-fill');
  if (fill) {
    setFill(fill, (data.state.progress || {}).percent || 0);
  }
  var footer = '';
  if (data.chunky.filename && data.chunky.by_panel && !pregenActive(data.state)) {
    footer = '<button type="button" class="btn-ghost btn-sm" id="pregen-uninstall">' + icon('trash-2') + escHtml(t('Quitar Chunky')) + '</button>';
  }
  document.getElementById('pregen-footer-left').innerHTML = footer;
  if (document.getElementById('pregen-estimate')) {
    updatePregenEstimate();
  }
}

function pregenChoice() {
  var select = document.getElementById('pregen-radius');
  var custom = document.getElementById('pregen-radius-custom');
  custom.hidden = select.value !== 'custom';
  var radius = parseInt(select.value === 'custom' ? custom.value : select.value, 10);
  var dims = Array.prototype.filter.call(document.querySelectorAll('[data-pregen-dim]'), function(box) {
    return box.checked;
  }).map(function(box) { return box.dataset.pregenDim; });
  return { radius: radius, dimensions: dims, onlyEmpty: document.getElementById('pregen-only-empty').checked };
}

function updatePregenEstimate() {
  clearTimeout(pregen.estimateTimer);
  pregen.estimateTimer = setTimeout(function() {
    var box = document.getElementById('pregen-estimate');
    var start = document.getElementById('pregen-start');
    if (!box) {
      return;
    }
    var choice = pregenChoice();
    var limits = pregen.data.limits;
    if (!choice.dimensions.length || !(choice.radius >= limits.min && choice.radius <= limits.max)) {
      box.innerHTML = '<span class="muted">' + escHtml(!choice.dimensions.length
        ? t('Elige al menos una dimensión.')
        : t('El radio tiene que estar entre {min} y {max} bloques.', limits)) + '</span>';
      start.disabled = true;
      return;
    }
    apiJson(pregenUrl('/estimate?radius=' + choice.radius + '&dimensions=' + encodeURIComponent(choice.dimensions.join(',')))).then(function(result) {
      if (!document.getElementById('pregen-estimate')) {
        return;
      }
      if (!result.ok) {
        box.innerHTML = modErrorHtml(result.data.detail || t('No se pudo calcular'));
        return;
      }
      var est = result.data;
      var text = t('{chunks} chunks ({existing} ya generados). Ocuparán unos {size} más; quedan {free} libres.', {
        chunks: est.chunks.toLocaleString(), existing: est.existing.toLocaleString(),
        size: formatBytes(est.bytes), free: formatBytes(est.free)
      });
      var html = '<span>' + escHtml(text) + '</span>';
      if (est.approx) {
        html += '<span class="muted"> ' + escHtml(t('Aproximado: el mundo aún tiene poco generado para medir cuánto ocupa cada chunk.')) + '</span>';
      }
      if (!est.enough) {
        html += noticeHtml('warn', escHtml(t('No hay espacio suficiente: tiene que quedar al menos {reserve} libre después. Prueba con un radio menor.', { reserve: formatBytes(est.reserve) })));
      }
      box.innerHTML = html;
      document.getElementById('pregen-start').disabled = !est.enough;
    });
  }, 250);
}

function startPregen(button) {
  var choice = pregenChoice();
  var form = new FormData();
  form.append('radius', choice.radius);
  form.append('dimensions', choice.dimensions.join(','));
  form.append('only_when_empty', choice.onlyEmpty ? '1' : '0');
  button.disabled = true;
  apiJson(pregenUrl('/start'), { method: 'POST', body: form }).then(function(result) {
    if (!result.ok) {
      button.disabled = false;
      showToast(result.data.detail || t('No se pudo empezar'), 'error');
      return;
    }
    showToast(t('Pregeneración en marcha'), 'success');
    loadPregen();
  });
}

function postPregen(path, button, done) {
  button.disabled = true;
  apiJson(pregenUrl(path), { method: 'POST' }).then(function(result) {
    if (!result.ok) {
      button.disabled = false;
      showToast(result.data.detail || t('No se pudo hacer'), 'error');
      return;
    }
    if (done) {
      done(result.data);
    }
    loadPregen();
  });
}

function closePregen() {
  clearTimeout(pregen.poll);
  clearTimeout(pregen.estimateTimer);
  document.getElementById('pregen-modal').classList.remove('show');
}

document.getElementById('pregen-modal').addEventListener('click', function(event) {
  if (event.target === this) {
    closePregen();
    return;
  }
  var target = event.target.closest('button');
  if (!target) {
    return;
  }
  if (target.id === 'pregen-install') {
    postPregen('/install', target, function(data) {
      pregen.justInstalled = true;
      showToast(t('Chunky {version} instalado', { version: data.version }), 'success');
    });
  } else if (target.id === 'pregen-start') {
    startPregen(target);
  } else if (target.id === 'pregen-stop') {
    showConfirm(t('¿Cancelar la pregeneración?'), t('Lo ya generado se queda; para seguir habría que empezar de nuevo (Chunky se salta lo que ya existe).'), function() {
      postPregen('/cancel', target);
    }, { icon: '🗺️', confirmLabel: t('Cancelar pregeneración'), cancelLabel: t('Seguir') });
  } else if (target.id === 'pregen-uninstall') {
    showConfirm(t('¿Quitar Chunky?'), t('Se borra su jar de la carpeta mods. El terreno ya generado se queda.'), function() {
      postPregen('/uninstall', target, function() {
        pregen.available = null;
        showToast(t('Chunky quitado'), 'success');
      });
    }, { icon: '🗑️', confirmLabel: t('Quitar') });
  }
});
document.getElementById('pregen-body').addEventListener('change', function(event) {
  if (event.target.closest('#pregen-radius, #pregen-radius-custom, [data-pregen-dim]')) {
    updatePregenEstimate();
  }
});
document.getElementById('pregen-body').addEventListener('input', function(event) {
  if (event.target.id === 'pregen-radius-custom') {
    updatePregenEstimate();
  }
});
document.getElementById('btn-pregen').addEventListener('click', function() {
  openPregen(currentModpack);
});
document.getElementById('pregen-close').addEventListener('click', closePregen);
document.getElementById('pregen-cancel').addEventListener('click', closePregen);
