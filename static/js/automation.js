// -- Automatización: reinicio tras caída, copias automáticas y tareas ----------
// Los ajustes se guardan en cuanto se cambian (no hay botón de guardar); las
// tareas se crean y editan en el formulario de la tarjeta.
// Iniciales y nombres de los días (de lunes a domingo) en el idioma del panel.
// El 5 de enero de 2026 es lunes.
var DAY_LETTERS = [0, 1, 2, 3, 4, 5, 6].map(function(i) {
  return new Date(2026, 0, 5 + i).toLocaleDateString(APP_LOCALE, { weekday: 'narrow' });
});
var DAY_NAMES = [0, 1, 2, 3, 4, 5, 6].map(function(i) {
  return new Date(2026, 0, 5 + i).toLocaleDateString(APP_LOCALE, { weekday: 'long' });
});
var TASK_ICONS = { restart: 'refresh-cw', stop: 'square', start: 'play', command: 'terminal', backup: 'archive' };
var automationData = null;
var editingTaskId = null;

function loadAutomation() {
  apiJson('/api/automation').then(function(result) {
    if (!result.ok) {
      document.getElementById('task-list').innerHTML = noticeHtml('error', escHtml(result.data.detail || t('No se pudo cargar la automatización.')));
      return;
    }
    automationData = result.data;
    renderAutomationSettings();
    renderTaskKinds();
    renderTasks();
    document.getElementById('auto-server-time').textContent = t('Hora del servidor: {time}', { time: result.data.server_time });
  });
}

// -- Ajustes: se guardan al cambiar --------------------------------------------
function renderAutomationSettings() {
  var restart = automationData.auto_restart;
  var backups = automationData.backups;
  document.getElementById('auto-restart-toggle').classList.toggle('on', restart.enabled);
  document.getElementById('auto-restart-attempts').value = restart.max_attempts;
  document.getElementById('auto-restart-window').value = restart.window_minutes;
  document.getElementById('auto-backup-toggle').classList.toggle('on', backups.enabled);
  document.getElementById('auto-backup-interval').value = backups.interval_hours;
  document.getElementById('auto-backup-keep').value = backups.keep;
  document.getElementById('auto-backup-full-toggle').classList.toggle('on', !!backups.full);
  var idle = automationData.idle_stop || { enabled: false, minutes: 30 };
  document.getElementById('auto-idle-toggle').classList.toggle('on', idle.enabled);
  document.getElementById('auto-idle-minutes').value = idle.minutes;
  document.getElementById('auto-idle-fields').classList.toggle('is-off', !idle.enabled);
  renderMirror();
  document.getElementById('auto-restart-fields').classList.toggle('is-off', !restart.enabled);
  document.getElementById('auto-backup-fields').classList.toggle('is-off', !backups.enabled);
}

function saveAutomationSettings() {
  var body = {
    auto_restart: {
      enabled: document.getElementById('auto-restart-toggle').classList.contains('on'),
      max_attempts: parseInt(document.getElementById('auto-restart-attempts').value, 10),
      window_minutes: parseInt(document.getElementById('auto-restart-window').value, 10)
    },
    backups: {
      enabled: document.getElementById('auto-backup-toggle').classList.contains('on'),
      interval_hours: parseInt(document.getElementById('auto-backup-interval').value, 10),
      keep: parseInt(document.getElementById('auto-backup-keep').value, 10),
      full: document.getElementById('auto-backup-full-toggle').classList.contains('on')
    },
    idle_stop: {
      enabled: document.getElementById('auto-idle-toggle').classList.contains('on'),
      minutes: parseInt(document.getElementById('auto-idle-minutes').value, 10)
    }
  };
  apiJson('/api/automation/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function(result) {
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo guardar'), 'error');
      return;
    }
    automationData.auto_restart = result.data.auto_restart;
    automationData.backups = result.data.backups;
    automationData.idle_stop = result.data.idle_stop;
    // Los números fuera de rango vuelven a lo que de verdad se guardó.
    renderAutomationSettings();
    showToast(t('Guardado'), 'success');
  });
}

// -- Destino secundario de las copias (solo lo cambia un administrador) -----------
function renderMirror() {
  var mirror = automationData.mirror || {};
  var input = document.getElementById('auto-mirror-path');
  var isAdmin = currentRole === 'admin';
  if (document.activeElement !== input) {
    input.value = automationData.backups.mirror_dir || '';
  }
  input.disabled = !isAdmin;
  document.getElementById('auto-mirror-save').hidden = !isAdmin;
  var html = '';
  if (!isAdmin) {
    html = '<p class="field-hint">' + escHtml(t('Solo un administrador puede cambiarlo.')) + '</p>';
  }
  if (mirror.configured) {
    if (!mirror.available) {
      html += noticeHtml('error', escHtml(t('El destino secundario ({path}) no está disponible: comprueba que el disco o la carpeta de red está montado.', { path: mirror.path })));
    } else if (mirror.last_error) {
      html += noticeHtml('error', escHtml(t('No se pudieron llevar las copias al destino secundario: {error}', { error: mirror.last_error })));
    } else if (mirror.disk) {
      html += noticeHtml('ok', escHtml(t('Funcionando: {free} libres en el destino secundario.', { free: formatBytes(mirror.disk.free) })));
    }
  }
  document.getElementById('auto-mirror-status').innerHTML = html;
}

document.getElementById('auto-mirror-save').addEventListener('click', function() {
  var button = this;
  var path = document.getElementById('auto-mirror-path').value.trim();
  busyWhile(button, function() {
    return apiJson('/api/automation/backup-mirror', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    }).then(function(result) {
      if (!result.ok) {
        showToast(result.data.detail || t('No se pudo guardar'), 'error');
        return;
      }
      automationData.backups.mirror_dir = path;
      automationData.mirror = result.data.mirror;
      renderMirror();
      showToast(path ? t('Destino secundario guardado: las copias que ya había se están llevando allí') : t('Destino secundario quitado'), 'success');
    });
  });
});

['auto-restart-toggle', 'auto-backup-toggle', 'auto-backup-full-toggle', 'auto-idle-toggle'].forEach(function(id) {
  document.getElementById(id).addEventListener('click', function() {
    this.classList.toggle('on');
    saveAutomationSettings();
  });
});

['auto-restart-attempts', 'auto-restart-window', 'auto-backup-interval', 'auto-backup-keep', 'auto-idle-minutes'].forEach(function(id) {
  document.getElementById(id).addEventListener('change', saveAutomationSettings);
});

// -- Lista de tareas -------------------------------------------------------------
function describeTaskTitle(task) {
  if (task.kind === 'command') {
    return t('Comando {command}', { command: task.command });
  }
  if (task.kind === 'start') {
    return t('Encender {name}', { name: task.modpack });
  }
  return t(automationData.task_kinds[task.kind]);
}

function describeDays(days) {
  var key = days.join(',');
  if (key === '0,1,2,3,4,5,6') {
    return t('Todos los días');
  }
  if (key === '0,1,2,3,4') {
    return t('De lunes a viernes');
  }
  if (key === '5,6') {
    return t('Los fines de semana');
  }
  var names = days.map(function(day) { return DAY_NAMES[day]; });
  if (names.length === 1) {
    // «Los lunes», «Los sábados» / «Mondays»
    return t('Los {days}', { days: names[0] + (/s$/.test(names[0]) ? '' : 's') });
  }
  return joinList(names);
}

function dayChipsHtml(days) {
  return '<span class="day-chips" aria-hidden="true">' + DAY_LETTERS.map(function(letter, index) {
    return '<span class="day-chip' + (days.indexOf(index) !== -1 ? ' on' : '') + '">' + letter + '</span>';
  }).join('') + '</span>';
}

function taskStatusHtml(task) {
  var status = (automationData.task_status || {})[task.id];
  if (!status) {
    return '';
  }
  var when = formatRelativeDate(new Date(status.at).getTime() / 1000);
  return '<div class="task-status ' + (status.ok ? 'is-ok' : 'is-fail') + '">'
    + icon(status.ok ? 'circle-check' : 'circle-x')
    + '<span>' + escHtml(t('Última vez {when}: {message}', { when: when, message: t(status.message) })) + '</span></div>';
}

function renderTasks() {
  var list = document.getElementById('task-list');
  var tasks = automationData.tasks;
  if (!tasks.length) {
    list.innerHTML = emptyArt('sign', t('Nada programado'),
      t('Por ejemplo, reiniciar el servidor cada madrugada avisando antes a quien esté jugando.'),
      '<button type="button" class="btn-secondary" id="task-preset-btn">' + icon('refresh-cw') + t('Reinicio diario a las 05:00') + '</button>', true);
    document.getElementById('task-preset-btn').addEventListener('click', function() {
      openTaskForm({ kind: 'restart', time: '05:00', days: [0, 1, 2, 3, 4, 5, 6], warn_minutes: 5 });
    });
    return;
  }
  var sorted = tasks.slice().sort(function(a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
  list.innerHTML = '<div class="task-list">' + sorted.map(function(task) {
    var meta = describeDays(task.days);
    if (task.warn_minutes) {
      meta += t(', avisando {n} min antes', { n: task.warn_minutes });
    }
    if (task.only_empty) {
      meta += t(', solo si no hay nadie (espera hasta {time})', { time: formatWaitMinutes(task.wait_minutes) });
    }
    return '<div class="task-row' + (task.enabled ? '' : ' is-paused') + '" data-id="' + escHtml(task.id) + '">'
      + '<div class="toggle-track task-toggle' + (task.enabled ? ' on' : '') + '" aria-label="' + t('Tarea activa') + '"><div class="toggle-thumb"></div></div>'
      + '<div class="task-time">' + escHtml(task.time) + '</div>'
      + '<div class="task-main">'
      + '<div class="task-title">' + icon(TASK_ICONS[task.kind]) + '<span>' + escHtml(describeTaskTitle(task)) + '</span></div>'
      + '<div class="task-meta">' + dayChipsHtml(task.days) + '<span>' + escHtml(meta) + '</span></div>'
      + taskStatusHtml(task)
      + '</div>'
      + '<div class="task-actions">'
      + '<button type="button" class="btn-ghost btn-xs" data-action="run" title="' + t('Ejecutar ahora para probarla') + '">' + icon('play') + t('Probar') + '</button>'
      + '<button type="button" class="btn-ghost btn-xs" data-action="edit" aria-label="' + t('Editar') + '" title="' + t('Editar') + '">' + icon('pencil') + '</button>'
      + '<button type="button" class="btn-ghost btn-xs" data-action="delete" aria-label="' + t('Borrar') + '" title="' + t('Borrar') + '">' + icon('trash-2') + '</button>'
      + '</div></div>';
  }).join('') + '</div>';
}

function findTask(id) {
  return automationData.tasks.filter(function(task) { return task.id === id; })[0];
}

function saveTask(task, onDone) {
  return apiJson('/api/automation/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task)
  }).then(function(result) {
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo guardar la tarea'), 'error');
      return false;
    }
    var index = automationData.tasks.map(function(t) { return t.id; }).indexOf(result.data.id);
    if (index === -1) {
      automationData.tasks.push(result.data);
    } else {
      automationData.tasks[index] = result.data;
    }
    renderTasks();
    if (onDone) {
      onDone(result.data);
    }
    return true;
  });
}

document.getElementById('task-list').addEventListener('click', function(event) {
  var row = event.target.closest('.task-row');
  if (!row) {
    return;
  }
  var task = findTask(row.dataset.id);
  if (!task) {
    return;
  }
  if (event.target.closest('.task-toggle')) {
    var copy = Object.assign({}, task, { enabled: !task.enabled });
    saveTask(copy, function(saved) {
      showToast(saved.enabled ? t('Tarea activada') : t('Tarea en pausa'), 'success');
    });
    return;
  }
  var button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  var action = button.dataset.action;
  if (action === 'edit') {
    openTaskForm(task);
  } else if (action === 'delete') {
    showConfirm(t('¿Borrar la tarea?'), t('{task} a las {time}.', { task: describeTaskTitle(task), time: task.time }), function() {
      busyWhile(button, function() {
        return apiJson('/api/automation/tasks/' + encodeURIComponent(task.id), { method: 'DELETE' }).then(function(result) {
          if (!result.ok) {
            showToast(result.data.detail || t('No se pudo borrar'), 'error');
            return;
          }
          automationData.tasks = automationData.tasks.filter(function(t) { return t.id !== task.id; });
          renderTasks();
          showToast(t('Tarea borrada'), 'success');
        });
      });
    }, { confirmLabel: t('Borrar') });
  } else if (action === 'run') {
    var disruptive = task.kind === 'restart' || task.kind === 'stop';
    var run = function() {
      busyWhile(button, function() {
        return apiJson('/api/automation/tasks/' + encodeURIComponent(task.id) + '/run', { method: 'POST' }).then(function(result) {
          showToast(result.ok ? t(result.data.message) : (result.data.detail || t('No se pudo ejecutar')), result.ok ? 'success' : 'error');
          // El resultado llega cuando termina: se vuelve a mirar en un rato.
          setTimeout(function() {
            if (currentPage === 'automation') {
              loadAutomation();
            }
          }, disruptive && task.warn_minutes ? 4000 : 2500);
        });
      });
    };
    if (disruptive || task.kind === 'start') {
      var msg = task.warn_minutes
        ? t('Se hará ahora mismo, sin esperar los {n} minutos de aviso (los jugadores recibirán un aviso igualmente).', { n: task.warn_minutes })
        : t('Se hará ahora mismo.');
      showConfirm(t('¿Probar «{task}»?', { task: describeTaskTitle(task) }), msg, run, { confirmLabel: t('Ejecutar ahora'), tone: 'accent', icon: 'play' });
    } else {
      run();
    }
  }
});

// -- Formulario de tarea ---------------------------------------------------------
function renderTaskKinds() {
  var select = document.getElementById('task-kind');
  var kinds = automationData.task_kinds;
  select.innerHTML = Object.keys(kinds).map(function(key) {
    return '<option value="' + escHtml(key) + '">' + escHtml(t(kinds[key])) + '</option>';
  }).join('');
  var packs = document.getElementById('task-modpack');
  packs.innerHTML = automationData.modpacks.length
    ? automationData.modpacks.map(function(name) {
        return '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>';
      }).join('')
    : '<option value="">' + t('No hay servidores instalados') + '</option>';
}

(function buildDayPicker() {
  document.getElementById('task-days').innerHTML = DAY_LETTERS.map(function(letter, index) {
    return '<button type="button" class="day-toggle" data-day="' + index + '" aria-pressed="false" title="' + DAY_NAMES[index] + '">' + letter + '</button>';
  }).join('');
})();

document.getElementById('task-days').addEventListener('click', function(event) {
  var button = event.target.closest('.day-toggle');
  if (button) {
    button.setAttribute('aria-pressed', button.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
  }
});

function formatWaitMinutes(minutes) {
  if (minutes < 60) {
    return t('{n} min', { n: minutes });
  }
  return minutes === 60 ? t('1 hora') : t('{n} horas', { n: minutes / 60 });
}

function syncTaskFormFields() {
  var kind = document.getElementById('task-kind').value;
  var disruptive = kind === 'restart' || kind === 'stop';
  var onlyEmpty = disruptive && document.getElementById('task-only-empty').checked;
  document.getElementById('task-only-empty-field').hidden = !disruptive;
  document.getElementById('task-wait-field').hidden = !onlyEmpty;
  // Esperando a que no haya nadie, no hay a quién avisar.
  document.getElementById('task-warn-field').hidden = !disruptive || onlyEmpty;
  document.getElementById('task-modpack-field').hidden = kind !== 'start';
  document.getElementById('task-command-field').hidden = kind !== 'command';
}

document.getElementById('task-kind').addEventListener('change', syncTaskFormFields);
document.getElementById('task-only-empty').addEventListener('change', syncTaskFormFields);

function openTaskForm(task) {
  var form = document.getElementById('task-form');
  editingTaskId = task && task.id ? task.id : null;
  task = task || { kind: 'restart', time: '05:00', days: [0, 1, 2, 3, 4, 5, 6], warn_minutes: 5 };
  document.getElementById('task-form-title').textContent = editingTaskId ? t('Editar tarea') : t('Nueva tarea');
  document.getElementById('task-kind').value = task.kind;
  document.getElementById('task-time').value = task.time;
  document.getElementById('task-warn').value = String(task.warn_minutes || 0);
  document.getElementById('task-only-empty').checked = !!task.only_empty;
  document.getElementById('task-wait').value = String(task.wait_minutes || 120);
  document.getElementById('task-command').value = task.command || '';
  if (task.modpack) {
    document.getElementById('task-modpack').value = task.modpack;
  }
  document.querySelectorAll('#task-days .day-toggle').forEach(function(button) {
    button.setAttribute('aria-pressed', (task.days || []).indexOf(Number(button.dataset.day)) !== -1 ? 'true' : 'false');
  });
  syncTaskFormFields();
  form.hidden = false;
  form.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  document.getElementById('task-kind').focus({ preventScroll: true });
}

function closeTaskForm() {
  document.getElementById('task-form').hidden = true;
  editingTaskId = null;
}

document.getElementById('auto-new-task-btn').addEventListener('click', function() { openTaskForm(null); });
document.getElementById('task-cancel-btn').addEventListener('click', closeTaskForm);

document.getElementById('task-form').addEventListener('submit', function(event) {
  event.preventDefault();
  var previous = editingTaskId ? findTask(editingTaskId) : null;
  var task = {
    id: editingTaskId || undefined,
    enabled: previous ? previous.enabled : true,
    kind: document.getElementById('task-kind').value,
    time: document.getElementById('task-time').value,
    days: Array.prototype.filter.call(document.querySelectorAll('#task-days .day-toggle'), function(button) {
      return button.getAttribute('aria-pressed') === 'true';
    }).map(function(button) { return Number(button.dataset.day); }),
    warn_minutes: Number(document.getElementById('task-warn').value),
    only_empty: document.getElementById('task-only-empty').checked,
    wait_minutes: Number(document.getElementById('task-wait').value),
    command: document.getElementById('task-command').value,
    modpack: document.getElementById('task-modpack').value
  };
  var isNew = !editingTaskId;
  var btn = document.getElementById('task-save-btn');
  btn.disabled = true;
  saveTask(task, function() {
    closeTaskForm();
    showToast(isNew ? t('Tarea programada') : t('Tarea guardada'), 'success');
    if (isNew) {
      unlockAchievement('clockwork');
    }
  }).then(function() { btn.disabled = false; });
});
