// ── Auth / Login ──────────────────────────────────────────────────────────────
// La sesión vive en una cookie HttpOnly que pone el servidor al entrar: el
// navegador la manda sola en fetch, EventSource, XMLHttpRequest y enlaces de
// descarga, así que aquí no se guarda ni se pasa ningún token.
var currentRole = 'user';

var _pendingFetches = {};

function apiFetch(url, opts) {
  opts = opts || {};

  // GET requests: cancel any previous in-flight request to the same URL
  var requestKey = (opts.method || 'GET') + ':' + url;
  if ((opts.method || 'GET') === 'GET') {
    if (_pendingFetches[requestKey]) {
      _pendingFetches[requestKey].abort();
    }
    var controller = new AbortController();
    _pendingFetches[requestKey] = controller;
    opts.signal = controller.signal;
  }

  return fetch(url, opts).then(function(response) {
    delete _pendingFetches[requestKey];
    if (response.status === 401) {
      logout();
      throw new Error('Sesión expirada');
    }
    return response;
  }).catch(function(error) {
    delete _pendingFetches[requestKey];
    // Aborted requests die silently — no error UI
    if (error.name === 'AbortError') {
      return new Promise(function() {});
    }
    throw error;
  });
}

function cancelFetchesMatching(prefix) {
  Object.keys(_pendingFetches).forEach(function(requestKey) {
    if (requestKey.indexOf(prefix) !== -1) {
      _pendingFetches[requestKey].abort();
      delete _pendingFetches[requestKey];
    }
  });
}

function applyRoleUI() {
  var isAdmin = currentRole === 'admin';
  document.getElementById('tab-users').style.display = isAdmin ? 'inline-flex' : 'none';
  document.getElementById('tab-config').style.display = isAdmin ? 'inline-flex' : 'none';
}

// Vuelve a la pantalla de login. La llama apiFetch al recibir un 401 (la
// sesión ya no vale, no hace falta avisar al servidor) y endSession() al
// pulsar "Salir".
function logout() {
  currentRole = 'user';
  applyRoleUI();
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('login-pass').value = '';
  document.getElementById('login-error').textContent = '';
}

function endSession() {
  fetch('/api/auth/logout', { method: 'POST' }).finally(logout);
}

function onLoginSuccess(role) {
  currentRole = role || 'user';
  document.getElementById('login-screen').classList.add('hidden');
  applyRoleUI();
  // El primer intento de sysmon.js de comprobar auto-actualización sale
  // disparado sin sesión todavía (nada más cargar la página) y falla con 401
  // — no hace falta esperar hasta el próximo intento programado para que se
  // entere de que ya hay sesión de verdad.
  if (typeof autoUpdatePollTimer !== 'undefined' && autoUpdatePollTimer !== null) {
    clearTimeout(autoUpdatePollTimer);
    autoUpdatePollTimer = null;
  }
  if (typeof loadAutoUpdateStatus === 'function') {
    loadAutoUpdateStatus();
  }
  if (typeof loadServerPageData === 'function') {
    loadServerPageData();
  }
}

function doLogin() {
  var username = document.getElementById('login-user').value.trim();
  var password = document.getElementById('login-pass').value;
  var btn = document.getElementById('login-btn');
  var errorEl = document.getElementById('login-error');
  if (!username) {
    errorEl.textContent = 'Escribe tu usuario.';
    document.getElementById('login-user').focus();
    return;
  }
  if (!password) {
    errorEl.textContent = 'Escribe tu contraseña.';
    document.getElementById('login-pass').focus();
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Entrando…';
  errorEl.textContent = '';
  var form = new FormData();
  form.append('username', username);
  form.append('password', password);
  fetch('/api/auth/login', { method: 'POST', body: form })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      btn.disabled = false;
      btn.textContent = 'Entrar';
      if (!result.ok) {
        errorEl.textContent = result.data.detail || 'Usuario o contraseña incorrectos.';
        return;
      }
      onLoginSuccess(result.data.role);
    })
    .catch(function(error) {
      btn.disabled = false;
      btn.textContent = 'Entrar';
      errorEl.textContent = 'No se pudo conectar con el panel. Comprueba que el equipo sigue encendido. (' + error.message + ')';
    });
}

document.getElementById('login-btn').addEventListener('click', doLogin);
document.getElementById('login-pass').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    doLogin();
  }
});
// Enter en el usuario pasa a la contraseña (o entra, si ya está escrita).
document.getElementById('login-user').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    if (document.getElementById('login-pass').value) {
      doLogin();
    } else {
      document.getElementById('login-pass').focus();
    }
  }
});

// Si ya hay una sesión abierta (la cookie sigue valiendo), entrar directamente.
(function checkExistingSession() {
  fetch('/api/auth/verify')
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      if (result.ok) {
        onLoginSuccess(result.data.role);
      } else {
        logout();
      }
    })
    .catch(function() {
      logout();
    });
})();
