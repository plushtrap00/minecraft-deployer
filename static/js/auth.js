// ── Auth / Login ──────────────────────────────────────────────────────────────
var authToken = localStorage.getItem('mc_token') || '';
var currentRole = localStorage.getItem('mc_role') || 'user';

function authHeaders() {
  return authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
}

var _pendingFetches = {};

function apiFetch(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers || {}, authHeaders());

  // GET requests: cancel any previous in-flight request to the same URL
  var key = (opts.method || 'GET') + ':' + url;
  if ((opts.method || 'GET') === 'GET') {
    if (_pendingFetches[key]) _pendingFetches[key].abort();
    var ctrl = new AbortController();
    _pendingFetches[key] = ctrl;
    opts.signal = ctrl.signal;
  }

  return fetch(url, opts).then(function(r) {
    delete _pendingFetches[key];
    if (r.status === 401) { logout(); throw new Error('Sesión expirada'); }
    return r;
  }).catch(function(e) {
    delete _pendingFetches[key];
    // Aborted requests die silently — no error UI
    if (e.name === 'AbortError') return new Promise(function() {});
    throw e;
  });
}

function cancelFetchesMatching(prefix) {
  Object.keys(_pendingFetches).forEach(function(k) {
    if (k.indexOf(prefix) !== -1) {
      _pendingFetches[k].abort();
      delete _pendingFetches[k];
    }
  });
}

function applyRoleUI() {
  var tab = document.getElementById('tab-users');
  tab.style.display = currentRole === 'admin' ? 'inline-block' : 'none';
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
  var user = document.getElementById('login-user').value.trim();
  var pass = document.getElementById('login-pass').value;
  var btn  = document.getElementById('login-btn');
  var err  = document.getElementById('login-error');
  if (!pass) {
    err.textContent = 'Introduce la contraseña';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Entrando...';
  err.textContent = '';
  var form = new FormData();
  form.append('username', user);
  form.append('password', pass);
  fetch('/api/auth/login', { method: 'POST', body: form })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      btn.disabled = false;
      btn.textContent = 'Entrar';
      if (!res.ok) {
        err.textContent = res.d.detail || 'Error de autenticación';
        return;
      }
      onLoginSuccess(res.d.token, res.d.role);
    })
    .catch(function(e) {
      btn.disabled = false;
      btn.textContent = 'Entrar';
      err.textContent = 'Error de red: ' + e.message;
    });
}

document.getElementById('login-btn').addEventListener('click', doLogin);
document.getElementById('login-pass').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') doLogin();
});

// Verificar token existente al arrancar
(function checkExistingToken() {
  if (!authToken) return;
  fetch('/api/auth/verify', { headers: authHeaders() })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      if (res.ok) {
        currentRole = res.d.role || 'user';
        localStorage.setItem('mc_role', currentRole);
        document.getElementById('login-screen').classList.add('hidden');
        applyRoleUI();
      } else {
        logout();
      }
    })
    .catch(function() { logout(); });
})();
