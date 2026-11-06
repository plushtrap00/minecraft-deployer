// -- Pasos de "Instalar" -----------------------------------------------------
// Cada modo de la página (subir, crear desde cero, buscar y descargar) es
// una secuencia de tarjetas .step. Aquí solo se calcula qué pasos están
// completos para marcarlos (.done) y, mientras falte algo obligatorio, el
// botón final se ve inactivo (.is-blocked) con una línea que dice qué falta.
// No se usa btn.disabled a propósito: deploy.js, create_server.js y
// modpack_install.js ya lo manejan para "operación en curso", y si se pulsa
// igualmente su propia validación explica qué falta.

function stepValue(id) {
  var el = document.getElementById(id);
  return el ? String(el.value || '').trim() : '';
}

function ramStepDone(prefix) {
  return Number(stepValue(prefix + '-min-val')) > 0 && Number(stepValue(prefix + '-max-val')) > 0;
}

var INSTALL_STEP_FLOWS = [
  {
    section: 'deploy-import-section',
    button: 'deploy-btn',
    steps: [
      { label: 'el archivo', done: function() { return !!selectedFile; } },
      { label: 'el nombre del servidor', done: function() { return !!stepValue('folder-name'); } },
      // Opcional: solo se marca como hecho si se activó y tiene valores.
      { optional: true, done: function() {
        return document.getElementById('ram-toggle').classList.contains('on') && ramStepDone('ram');
      } },
    ],
  },
  {
    section: 'deploy-create-section',
    button: 'create-server-btn',
    steps: [
      { label: 'el nombre', done: function() { return !!stepValue('create-name'); } },
      { label: 'la versión', done: function() {
        if (!stepValue('create-mc-version')) {
          return false;
        }
        return stepValue('create-loader') === 'vanilla' || !!stepValue('create-loader-version');
      } },
      { label: 'la RAM', done: function() { return ramStepDone('create-ram'); } },
    ],
  },
  {
    section: 'deploy-download-section',
    button: 'dl-install-btn',
    steps: [
      { label: 'el modpack', done: function() { return !!dlSelectedPack; } },
      { label: 'la versión y el nombre', done: function() {
        return !!stepValue('dl-version-select') && !!stepValue('dl-server-name');
      } },
      { label: 'la RAM', done: function() { return ramStepDone('dl-ram'); } },
    ],
  },
];

function refreshInstallSteps(flow) {
  var section = document.getElementById(flow.section);
  var cards = section.querySelectorAll('.step');
  var missing = [];
  flow.steps.forEach(function(step, index) {
    var done = step.done();
    if (cards[index]) {
      cards[index].classList.toggle('done', done);
    }
    if (!done && !step.optional) {
      missing.push(step.label);
    }
  });
  var button = document.getElementById(flow.button);
  button.classList.toggle('is-blocked', missing.length > 0);
  var hint = section.querySelector('[data-missing-for="' + flow.button + '"]');
  var hintText = missing.length ? 'Falta ' + joinWithY(missing) + '.' : '';
  // Solo si cambia: reescribir el texto siempre dispararía otra vez el
  // MutationObserver de abajo y se quedaría en bucle.
  if (hint && hint.textContent !== hintText) {
    hint.textContent = hintText;
  }
}

function joinWithY(items) {
  if (items.length < 2) {
    return items.join('');
  }
  return items.slice(0, -1).join(', ') + ' y ' + items[items.length - 1];
}

function refreshAllInstallSteps() {
  INSTALL_STEP_FLOWS.forEach(refreshInstallSteps);
}

// Cualquier cambio dentro de un modo puede completar un paso: escribir,
// elegir en un select, soltar un archivo o pulsar un resultado de búsqueda.
// Algunos (selección de modpack, listas de versiones que llegan por red)
// cambian el estado sin evento propio, así que también se recalcula un
// momento después y cuando cambia el DOM de la sección.
INSTALL_STEP_FLOWS.forEach(function(flow) {
  var section = document.getElementById(flow.section);
  var refresh = function() {
    refreshInstallSteps(flow);
    setTimeout(function() { refreshInstallSteps(flow); }, 0);
  };
  ['input', 'change', 'click', 'drop'].forEach(function(type) {
    section.addEventListener(type, refresh);
  });
  new MutationObserver(function() { refreshInstallSteps(flow); })
    .observe(section, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
});

refreshAllInstallSteps();
