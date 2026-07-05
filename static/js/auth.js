// ── Auth / Login ──────────────────────────────────────────────────────────────
var authToken = localStorage.getItem('mc_token') || '';
var currentRole = localStorage.getItem('mc_role') || 'user';

function authHeaders() {
  if (authToken) {
    return { 'Authorization': 'Bearer ' + authToken };
  }
  return {};
}

var _pendingFetches = {};

function apiFetch(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers || {}, authHeaders());

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
  document.getElementById('tab-users').style.display = isAdmin ? 'inline-block' : 'none';
  document.getElementById('tab-config').style.display = isAdmin ? 'inline-block' : 'none';
}

function logout() {
  localStorage.removeItem('mc_token');
  localStorage.removeItem('mc_role');
  authToken = '';
  currentRole = 'user';
  applyRoleUI();
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('login-pass').value = '';
  document.getElementById('login-error').textContent = '';
}

function onLoginSuccess(token, role) {
  authToken = token;
  currentRole = role || 'user';
  localStorage.setItem('mc_token', token);
  localStorage.setItem('mc_role', currentRole);
  document.getElementById('login-screen').classList.add('hidden');
  applyRoleUI();
}

function doLogin() {
  var username = document.getElementById('login-user').value.trim();
  var password = document.getElementById('login-pass').value;
  var btn = document.getElementById('login-btn');
  var errorEl = document.getElementById('login-error');
  if (!password) {
    errorEl.textContent = 'Introduce la contraseña';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Entrando...';
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
        errorEl.textContent = result.data.detail || 'Error de autenticación';
        return;
      }
      onLoginSuccess(result.data.token, result.data.role);
    })
    .catch(function(error) {
      btn.disabled = false;
      btn.textContent = 'Entrar';
      errorEl.textContent = 'Error de red: ' + error.message;
    });
}

document.getElementById('login-btn').addEventListener('click', doLogin);
document.getElementById('login-pass').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    doLogin();
  }
});

// Verificar token existente al arrancar
(function checkExistingToken() {
  if (!authToken) {
    return;
  }
  fetch('/api/auth/verify', { headers: authHeaders() })
    .then(function(response) {
      return response.json().then(function(data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function(result) {
      if (result.ok) {
        currentRole = result.data.role || 'user';
        localStorage.setItem('mc_role', currentRole);
        document.getElementById('login-screen').classList.add('hidden');
        applyRoleUI();
      } else {
        logout();
      }
    })
    .catch(function() {
      logout();
    });
})();
