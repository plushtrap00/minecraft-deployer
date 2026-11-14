// -- server.properties form ---------------------------------------------------
var KNOWN_KEYS = [
  'motd', 'server-port', 'max-players', 'online-mode', 'white-list', 'enforce-whitelist',
  'level-name', 'level-seed', 'level-type', 'gamemode', 'difficulty', 'hardcore',
  'generate-structures', 'allow-nether', 'pvp', 'spawn-monsters', 'spawn-animals',
  'spawn-npcs', 'allow-flight', 'spawn-protection', 'view-distance', 'simulation-distance',
  'network-compression-threshold', 'max-tick-time', 'rate-limit', 'enable-rcon',
  'rcon.port', 'rcon.password', 'enable-query', 'query.port', 'broadcast-rcon-to-ops'
];

function parseProps(text) {
  var props = {};
  text.split('\n').forEach(function(line) {
    line = line.trim();
    if (!line || line.startsWith('#')) {
      return;
    }
    var eq = line.indexOf('=');
    if (eq === -1) {
      return;
    }
    props[line.substring(0, eq).trim()] = line.substring(eq + 1).trim();
  });
  return props;
}

function serializeProps(props) {
  return Object.keys(props).map(function(key) { return key + '=' + props[key]; }).join('\n');
}

// Valor que usa Minecraft cuando la clave no está en el archivo: es lo que
// se enseña en el formulario en ese caso (antes se quedaba el valor del
// modpack anterior, o el interruptor apagado).
var PROP_DEFAULTS = {
  'online-mode': 'true', 'white-list': 'false', 'enforce-whitelist': 'false',
  'hardcore': 'false', 'generate-structures': 'true', 'allow-nether': 'true',
  'pvp': 'true', 'spawn-monsters': 'true', 'spawn-animals': 'true', 'spawn-npcs': 'true',
  'allow-flight': 'false', 'enable-query': 'false',
  'gamemode': 'survival', 'difficulty': 'easy'
};

function propDefault(key) {
  return PROP_DEFAULTS[key] !== undefined ? PROP_DEFAULTS[key] : '';
}

function propsToForm(props) {
  document.querySelectorAll('.prop-input').forEach(function(el) {
    var key = el.dataset.key;
    el.value = props[key] !== undefined ? props[key] : propDefault(key);
  });
  document.querySelectorAll('.toggle-track[data-key]').forEach(function(track) {
    var key = track.dataset.key;
    var val = props[key] !== undefined ? props[key] : propDefault(key);
    track.classList.toggle('on', val === 'true');
  });
  var unknown = {};
  Object.keys(props).forEach(function(key) {
    if (KNOWN_KEYS.indexOf(key) === -1) {
      unknown[key] = props[key];
    }
  });
  document.getElementById('props-raw-editor').value = serializeProps(unknown);
}

// Estado actual del formulario: { clave: valor } más el editor avanzado.
function readPropsForm() {
  var state = {};
  document.querySelectorAll('.prop-input').forEach(function(el) {
    if (el.dataset.key) {
      state[el.dataset.key] = el.value;
    }
  });
  document.querySelectorAll('.toggle-track[data-key]').forEach(function(track) {
    state[track.dataset.key] = track.classList.contains('on') ? 'true' : 'false';
  });
  state.__raw__ = document.getElementById('props-raw-editor').value;
  return state;
}

// Solo se escriben las claves que ya estaban en el archivo o que el usuario
// ha cambiado: una clave que no estaba se deja fuera (Minecraft usa su valor
// por defecto) en vez de añadirla vacía o a false.
function formToProps(originalText) {
  var props = parseProps(originalText);
  var current = readPropsForm();
  Object.keys(current).forEach(function(key) {
    if (key === '__raw__') {
      return;
    }
    var changed = !propsSnapshot || current[key] !== propsSnapshot[key];
    if (props[key] !== undefined || changed) {
      props[key] = current[key];
    }
  });
  Object.assign(props, parseProps(current.__raw__));
  return props;
}

function buildPropsText(props, originalText) {
  var lines = originalText.split('\n');
  var updated = {};
  var result = lines.map(function(line) {
    var trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      return line;
    }
    var eq = trimmed.indexOf('=');
    if (eq === -1) {
      return line;
    }
    var key = trimmed.substring(0, eq).trim();
    if (props[key] !== undefined) {
      updated[key] = true;
      return key + '=' + props[key];
    }
    return line;
  });
  Object.keys(props).forEach(function(key) {
    if (!updated[key]) {
      result.push(key + '=' + props[key]);
    }
  });
  return result.join('\n');
}

var originalPropsText = '';
// Lo que tenía el formulario al cargarlo o guardarlo (null mientras carga):
// para saber si hay cambios sin guardar.
var propsSnapshot = null;

function propsAreDirty() {
  if (!propsSnapshot || !currentModpack) {
    return false;
  }
  return JSON.stringify(readPropsForm()) !== JSON.stringify(propsSnapshot);
}

registerUnsaved('props', 'server.properties', propsAreDirty, function() { propsSnapshot = null; });

function loadServerProps() {
  propsSnapshot = null;
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/server-properties')
    .then(function(response) {
      if (!response.ok) {
        throw new Error();
      }
      return response.json();
    })
    .then(function(data) {
      originalPropsText = data.content;
      document.getElementById('props-editor').value = data.content;
      propsToForm(parseProps(data.content));
      propsSnapshot = readPropsForm();
    })
    .catch(function() {
      // Un modpack que aún no ha arrancado nunca no tiene server.properties:
      // el formulario sale con los valores por defecto y al guardar se crea.
      originalPropsText = '';
      document.getElementById('props-editor').value = '';
      propsToForm({});
      propsSnapshot = readPropsForm();
    });
}

document.querySelectorAll('.props-section-header').forEach(function(header) {
  var body = document.getElementById('ps-' + header.dataset.section);
  header.setAttribute('aria-controls', body.id);
  header.setAttribute('aria-expanded', body.style.display === 'none' ? 'false' : 'true');
  header.addEventListener('click', function() {
    var collapsed = body.style.display === 'none';
    body.style.display = collapsed ? '' : 'none';
    this.classList.toggle('collapsed', !collapsed);
    this.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
  });
});

document.getElementById('props-form').addEventListener('click', function(event) {
  var track = event.target.closest('.toggle-track[data-key]');
  if (track) {
    track.classList.toggle('on');
  }
});

document.getElementById('save-props-btn').addEventListener('click', function() {
  var props = formToProps(originalPropsText);
  var newText = buildPropsText(props, originalPropsText);
  var form = new FormData();
  form.append('content', newText);
  busyWhile(document.getElementById('save-props-btn'), function() {
    return apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/server-properties', {
      method: 'POST',
      body: form
    })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (data.success) {
          originalPropsText = newText;
          propsSnapshot = readPropsForm();
          showToast('server.properties guardado', 'success');
        flashDone(document.getElementById('save-props-btn'));
        } else {
          showToast(data.detail || 'No se pudo guardar server.properties', 'error');
        }
      })
      .catch(function() { showToast('No se pudo guardar server.properties', 'error'); });
  });
});

// Ctrl+S (o Cmd+S) guarda server.properties si es la pestaña que se ve.
document.addEventListener('keydown', function(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 's' || topModal()) {
    return;
  }
  if (document.getElementById('page-manage').classList.contains('active')
      && document.getElementById('mgmt-props').classList.contains('active') && currentModpack) {
    event.preventDefault();
    document.getElementById('save-props-btn').click();
  }
});
