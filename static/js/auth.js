// ── Auth / Login ──────────────────────────────────────────────────────────────
// La sesión vive en una cookie HttpOnly que pone el servidor al entrar: el
// navegador la manda sola en fetch, EventSource, XMLHttpRequest y enlaces de
// descarga, así que aquí no se guarda ni se pasa ningún token.
var currentRole = 'user';
var currentUser = '';

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
  var isLimited = currentRole === 'limited';
  document.getElementById('tab-users').style.display = isAdmin ? 'inline-flex' : 'none';
  document.getElementById('tab-config').style.display = isAdmin ? 'inline-flex' : 'none';
  // Cuenta limitada (services/permissions.py): ni instalar ni automatizar, y
  // la consola solo se lee. El servidor corta igualmente todo lo demás.
  document.getElementById('tab-deploy').style.display = isLimited ? 'none' : '';
  document.getElementById('tab-automation').style.display = isLimited ? 'none' : '';
  document.body.classList.toggle('account-limited', isLimited);
}

// Vuelve a la pantalla de login. La llama apiFetch al recibir un 401 (la
// sesión ya no vale, no hace falta avisar al servidor) y endSession() al
// pulsar "Salir".
function logout() {
  currentRole = 'user';
  currentUser = '';
  if (typeof resetAccountAchievements === 'function') {
    resetAccountAchievements();
  }
  applyRoleUI();
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('login-pass').value = '';
  document.getElementById('login-error').textContent = '';
}

function endSession() {
  fetch('/api/auth/logout', { method: 'POST' })
    .then(function(response) { return response.json(); })
    .then(function(data) {
      // La pantalla de entrada vuelve al idioma por defecto.
      if (data.lang && data.lang !== currentLang()) {
        location.reload();
        return;
      }
      logout();
    })
    .catch(logout);
}

function onLoginSuccess(role, user) {
  currentRole = role || 'user';
  currentUser = user || '';
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
  if (typeof loadAccountAchievements === 'function') {
    loadAccountAchievements();
  }
  warnRecoveryCodesLeft();
  if (typeof applyInitialRoute === 'function') {
    applyInitialRoute();
  }
}

function doLogin() {
  var username = document.getElementById('login-user').value.trim();
  var password = document.getElementById('login-pass').value;
  var btn = document.getElementById('login-btn');
  var errorEl = document.getElementById('login-error');
  if (!username) {
    errorEl.textContent = t('Escribe tu usuario.');
    document.getElementById('login-user').focus();
    return;
  }
  if (!password) {
    errorEl.textContent = t('Escribe tu contraseña.');
    document.getElementById('login-pass').focus();
    return;
  }
  btn.disabled = true;
  btn.textContent = t('Entrando…');
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
      btn.textContent = t('Entrar');
      if (!result.ok) {
        errorEl.textContent = result.data.detail || t('Usuario o contraseña incorrectos.');
        return;
      }
      if (result.data.two_factor) {
        showLoginSecondStep(result.data.ticket);
        return;
      }
      finishLogin(result.data);
    })
    .catch(function(error) {
      btn.disabled = false;
      btn.textContent = t('Entrar');
      errorEl.textContent = t('No se pudo conectar con el panel. Comprueba que el equipo sigue encendido. ({error})', { error: error.message });
    });
}

// Lo común a entrar con contraseña y con el segundo paso.
function finishLogin(data) {
  if (typeof data.recovery_left === 'number') {
    try {
      sessionStorage.setItem('mcd-recovery-left', String(data.recovery_left));
    } catch (err) {}
  }
  // Cada cuenta tiene su idioma: si no es el de la pantalla, se recarga en el suyo.
  if (data.lang && data.lang !== currentLang()) {
    location.reload();
    return;
  }
  onLoginSuccess(data.role, data.user);
}

// Si se ha entrado con un código de recuperación, se avisa de cuántos quedan
// (también tras recargar por el idioma, por eso pasa por sessionStorage).
function warnRecoveryCodesLeft() {
  var left = null;
  try {
    left = sessionStorage.getItem('mcd-recovery-left');
    sessionStorage.removeItem('mcd-recovery-left');
  } catch (err) {}
  if (left === null) {
    return;
  }
  showToast(Number(left) === 1
    ? t('Has entrado con un código de recuperación. Te queda 1: crea unos nuevos en Cambiar contraseña → Verificación en dos pasos.')
    : t('Has entrado con un código de recuperación. Te quedan {n}: si te quedan pocos, crea unos nuevos en Cambiar contraseña → Verificación en dos pasos.', { n: left }), 'warn');
}

// -- Segundo paso: código de la app o de recuperación ------------------------------
var loginTicket = '';

function showLoginSecondStep(ticket) {
  loginTicket = ticket;
  document.getElementById('login-form').hidden = true;
  document.getElementById('login-2fa-form').hidden = false;
  document.getElementById('login-code').value = '';
  document.getElementById('login-2fa-error').textContent = '';
  setTimeout(function() { document.getElementById('login-code').focus(); }, 0);
}

function backToLoginFirstStep() {
  loginTicket = '';
  document.getElementById('login-2fa-form').hidden = true;
  document.getElementById('login-form').hidden = false;
  document.getElementById('login-pass').value = '';
  document.getElementById('login-pass').focus();
}

function doLoginSecondStep() {
  var code = document.getElementById('login-code').value.trim();
  var btn = document.getElementById('login-2fa-btn');
  var errorEl = document.getElementById('login-2fa-error');
  if (!code) {
    errorEl.textContent = t('Escribe el código.');
    return;
  }
  btn.disabled = true;
  btn.textContent = t('Entrando…');
  errorEl.textContent = '';
  var form = new FormData();
  form.append('ticket', loginTicket);
  form.append('code', code);
  fetch('/api/auth/login/2fa', { method: 'POST', body: form })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, status: response.status, data: data };
      });
    })
    .then(function(result) {
      btn.disabled = false;
      btn.textContent = t('Entrar');
      if (!result.ok) {
        errorEl.textContent = result.data.detail || t('El código no es correcto');
        document.getElementById('login-code').select();
        return;
      }
      document.getElementById('login-2fa-form').hidden = true;
      document.getElementById('login-form').hidden = false;
      loginTicket = '';
      finishLogin(result.data);
    })
    .catch(function(error) {
      btn.disabled = false;
      btn.textContent = t('Entrar');
      errorEl.textContent = t('No se pudo conectar con el panel. Comprueba que el equipo sigue encendido. ({error})', { error: error.message });
    });
}

document.getElementById('login-form').addEventListener('submit', function(event) {
  event.preventDefault();
  doLogin();
});

document.getElementById('login-2fa-form').addEventListener('submit', function(event) {
  event.preventDefault();
  doLoginSecondStep();
});
document.getElementById('login-2fa-back').addEventListener('click', backToLoginFirstStep);

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
        onLoginSuccess(result.data.role, result.data.user);
      } else {
        logout();
      }
    })
    .catch(function() {
      logout();
    });
})();
