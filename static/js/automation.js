// -- Automatización: reinicio tras caída, copias automáticas y tareas ----------
// Los ajustes se guardan en cuanto se cambian (no hay botón de guardar); las
// tareas se crean y editan en el formulario de la tarjeta.
var DAY_LETTERS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
var DAY_NAMES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
var TASK_ICONS = { restart: 'refresh-cw', stop: 'square', start: 'play', command: 'terminal', backup: 'archive' };
var automationData = null;
var editingTaskId = null;

function loadAutomation() {
  apiJson('/api/automation').then(function(result) {
    if (!result.ok) {
      document.getElementById('task-list').innerHTML = noticeHtml('error', escHtml(result.data.detail || 'No se pudo cargar la automatización.'));
      return;
    }
    automationData = result.data;
    renderAutomationSettings();
    renderTaskKinds();
    renderTasks();
    document.getElementById('auto-server-time').textContent = 'Hora del servidor: ' + result.data.server_time;
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
      keep: parseInt(document.getElementById('auto-backup-keep').value, 10)
    }
  };
  apiJson('/api/automation/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function(result) {
    if (!result.ok) {
      showToast(result.data.detail || 'No se pudo guardar', 'error');
      return;
    }
    automationData.auto_restart = result.data.auto_restart;
    automationData.backups = result.data.backups;
    // Los números fuera de rango vuelven a lo que de verdad se guardó.
    renderAutomationSettings();
    showToast('Guardado', 'success');
  });
}

['auto-restart-toggle', 'auto-backup-toggle'].forEach(function(id) {
  document.getElementById(id).addEventListener('click', function() {
    this.classList.toggle('on');
    saveAutomationSettings();
  });
});

['auto-restart-attempts', 'auto-restart-window', 'auto-backup-interval', 'auto-backup-keep'].forEach(function(id) {
  document.getElementById(id).addEventListener('change', saveAutomationSettings);
});

// -- Lista de tareas -------------------------------------------------------------
function describeTaskTitle(task) {
  if (task.kind === 'command') {
    return 'Comando ' + task.command;
  }
  if (task.kind === 'start') {
    return 'Encender ' + task.modpack;
  }
  return automationData.task_kinds[task.kind];
}

function describeDays(days) {
  var key = days.join(',');
  if (key === '0,1,2,3,4,5,6') {
    return 'Todos los días';
  }
  if (key === '0,1,2,3,4') {
    return 'De lunes a viernes';
  }
  if (key === '5,6') {
    return 'Los fines de semana';
  }
  var names = days.map(function(day) { return DAY_NAMES[day]; });
  return names.length === 1 ? 'Los ' + names[0] + (/s$/.test(names[0]) ? '' : 's')
    : names.slice(0, -1).join(', ') + ' y ' + names[names.length - 1];
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
    + '<span>Última vez ' + escHtml(when) + ': ' + escHtml(status.message) + '</span></div>';
}

function renderTasks() {
  var list = document.getElementById('task-list');
  var tasks = automationData.tasks;
  if (!tasks.length) {
    list.innerHTML = emptyArt('sign', 'Nada programado',
      'Por ejemplo, reiniciar el servidor cada madrugada avisando antes a quien esté jugando.',
      '<button class="btn-secondary" id="task-preset-btn">' + icon('refresh-cw') + 'Reinicio diario a las 05:00</button>', true);
    document.getElementById('task-preset-btn').addEventListener('click', function() {
      openTaskForm({ kind: 'restart', time: '05:00', days: [0, 1, 2, 3, 4, 5, 6], warn_minutes: 5 });
    });
    return;
  }
  var sorted = tasks.slice().sort(function(a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
  list.innerHTML = '<div class="task-list">' + sorted.map(function(task) {
    var meta = describeDays(task.days);
    if (task.warn_minutes) {
      meta += ', avisando ' + task.warn_minutes + ' min antes';
    }
    return '<div class="task-row' + (task.enabled ? '' : ' is-paused') + '" data-id="' + escHtml(task.id) + '">'
      + '<div class="toggle-track task-toggle' + (task.enabled ? ' on' : '') + '" aria-label="Tarea activa"><div class="toggle-thumb"></div></div>'
      + '<div class="task-time">' + escHtml(task.time) + '</div>'
      + '<div class="task-main">'
      + '<div class="task-title">' + icon(TASK_ICONS[task.kind]) + '<span>' + escHtml(describeTaskTitle(task)) + '</span></div>'
      + '<div class="task-meta">' + dayChipsHtml(task.days) + '<span>' + escHtml(meta) + '</span></div>'
      + taskStatusHtml(task)
      + '</div>'
      + '<div class="task-actions">'
      + '<button class="btn-ghost btn-xs" data-action="run" title="Ejecutar ahora para probarla">' + icon('play') + 'Probar</button>'
      + '<button class="btn-ghost btn-xs" data-action="edit" aria-label="Editar" title="Editar">' + icon('pencil') + '</button>'
      + '<button class="btn-ghost btn-xs" data-action="delete" aria-label="Borrar" title="Borrar">' + icon('trash-2') + '</button>'
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
      showToast(result.data.detail || 'No se pudo guardar la tarea', 'error');
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
      showToast(saved.enabled ? 'Tarea activada' : 'Tarea en pausa', 'success');
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
    showConfirm('¿Borrar la tarea?', describeTaskTitle(task) + ' a las ' + task.time + '.', function() {
      apiJson('/api/automation/tasks/' + encodeURIComponent(task.id), { method: 'DELETE' }).then(function(result) {
        if (!result.ok) {
          showToast(result.data.detail || 'No se pudo borrar', 'error');
          return;
        }
        automationData.tasks = automationData.tasks.filter(function(t) { return t.id !== task.id; });
        renderTasks();
        showToast('Tarea borrada', 'success');
      });
    }, { confirmLabel: 'Borrar' });
  } else if (action === 'run') {
    var disruptive = task.kind === 'restart' || task.kind === 'stop';
    var run = function() {
      apiJson('/api/automation/tasks/' + encodeURIComponent(task.id) + '/run', { method: 'POST' }).then(function(result) {
        showToast(result.ok ? result.data.message : (result.data.detail || 'No se pudo ejecutar'), result.ok ? 'success' : 'error');
        // El resultado llega cuando termina: se vuelve a mirar en un rato.
        setTimeout(function() {
          if (currentPage === 'automation') {
            loadAutomation();
          }
        }, disruptive && task.warn_minutes ? 4000 : 2500);
      });
    };
    if (disruptive || task.kind === 'start') {
      var msg = task.warn_minutes
        ? 'Se hará ahora mismo, sin esperar los ' + task.warn_minutes + ' minutos de aviso (los jugadores recibirán un aviso igualmente).'
        : 'Se hará ahora mismo.';
      showConfirm('¿Probar «' + describeTaskTitle(task) + '»?', msg, run, { confirmLabel: 'Ejecutar ahora', tone: 'accent', icon: 'play' });
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
    return '<option value="' + escHtml(key) + '">' + escHtml(kinds[key]) + '</option>';
  }).join('');
  var packs = document.getElementById('task-modpack');
  packs.innerHTML = automationData.modpacks.length
    ? automationData.modpacks.map(function(name) {
        return '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>';
      }).join('')
    : '<option value="">No hay servidores instalados</option>';
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

function syncTaskFormFields() {
  var kind = document.getElementById('task-kind').value;
  document.getElementById('task-warn-field').hidden = !(kind === 'restart' || kind === 'stop');
  document.getElementById('task-modpack-field').hidden = kind !== 'start';
  document.getElementById('task-command-field').hidden = kind !== 'command';
}

document.getElementById('task-kind').addEventListener('change', syncTaskFormFields);

function openTaskForm(task) {
  var form = document.getElementById('task-form');
  editingTaskId = task && task.id ? task.id : null;
  task = task || { kind: 'restart', time: '05:00', days: [0, 1, 2, 3, 4, 5, 6], warn_minutes: 5 };
  document.getElementById('task-form-title').textContent = editingTaskId ? 'Editar tarea' : 'Nueva tarea';
  document.getElementById('task-kind').value = task.kind;
  document.getElementById('task-time').value = task.time;
  document.getElementById('task-warn').value = String(task.warn_minutes || 0);
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
    command: document.getElementById('task-command').value,
    modpack: document.getElementById('task-modpack').value
  };
  var isNew = !editingTaskId;
  var btn = document.getElementById('task-save-btn');
  btn.disabled = true;
  saveTask(task, function() {
    closeTaskForm();
    showToast(isNew ? 'Tarea programada' : 'Tarea guardada', 'success');
    if (isNew) {
      unlockAchievement('clockwork');
    }
  }).then(function() { btn.disabled = false; });
});
