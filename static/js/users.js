// ── Gestión de usuarios (admin) ───────────────────────────────────────────────
function loadUsers() {
  apiFetch('/api/users')
    .then(function(r) { return r.json(); })
    .then(function(users) {
      var list = document.getElementById('users-list');
      if (!users.length) {
        list.innerHTML = '<p class="empty-msg">No hay usuarios.</p>';
        return;
      }
      list.innerHTML = users.map(function(u) {
        var isAdmin = u.role === 'admin';
        var badge = isAdmin
          ? '<span style="background:rgba(88,166,255,.15);color:var(--accent);border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:700">Admin</span>'
          : '<span style="background:rgba(63,185,80,.15);color:var(--green);border-radius:99px;padding:2px 9px;font-size:.72rem;font-weight:700">Usuario</span>';
        var actions = isAdmin ? '' :
          '<div class="pe-actions"><button class="btn-danger" style="padding:4px 10px;font-size:.78rem" onclick="deleteUser(\'' + escHtml(u.username) + '\')">Eliminar</button></div>';
        return '<div class="player-entry">'
          + '<span class="pe-name">' + escHtml(u.username) + '</span>'
          + badge + actions
          + '</div>';
      }).join('');
    })
    .catch(function() {
      document.getElementById('users-list').innerHTML = '<p class="empty-msg">Error cargando usuarios.</p>';
    });
}

function deleteUser(username) {
  if (!confirm('¿Eliminar usuario "' + username + '"?')) return;
  apiFetch('/api/users/' + encodeURIComponent(username), { method: 'DELETE' })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      if (res.ok) {
        showToast('Usuario eliminado', 'success');
        loadUsers();
      } else {
        showToast(res.d.detail || 'Error al eliminar', 'error');
      }
    });
}

document.getElementById('btn-refresh-users').addEventListener('click', loadUsers);

// Validación del formulario de nuevo usuario
var USERNAME_RE = /^[a-zA-Z0-9_-]+$/;
var PRINTABLE_RE = /^[\x20-\x7E]+$/;

function validateNewUsername(val) {
  if (!val) return 'El nombre de usuario es obligatorio';
  if (val.length > 16) return 'Máximo 16 caracteres';
  if (!USERNAME_RE.test(val)) return 'Solo se permiten letras, números, guion bajo (_) y guion (-)';
  return '';
}

function validateNewPassword(val) {
  if (!val) return 'La contraseña es obligatoria';
  if (val.length < 8) return 'Mínimo 8 caracteres';
  if (!PRINTABLE_RE.test(val)) return 'Solo se permiten caracteres estándar (sin emojis ni símbolos raros)';
  return '';
}

function updateAddUserBtn() {
  var nameErr = validateNewUsername(document.getElementById('new-user-name').value.trim());
  var passErr = validateNewPassword(document.getElementById('new-user-pass').value);
  document.getElementById('add-user-btn').disabled = !!(nameErr || passErr);
}

function setFieldState(inputEl, errEl, errMsg) {
  inputEl.classList.toggle('input-error', !!errMsg);
  inputEl.classList.toggle('input-ok', !errMsg && inputEl.value.length > 0);
  errEl.textContent = errMsg;
}

document.getElementById('new-user-name').addEventListener('input', function() {
  setFieldState(this, document.getElementById('new-user-name-err'), validateNewUsername(this.value.trim()));
  updateAddUserBtn();
});

document.getElementById('new-user-pass').addEventListener('input', function() {
  setFieldState(this, document.getElementById('new-user-pass-err'), validateNewPassword(this.value));
  updateAddUserBtn();
});

document.getElementById('toggle-pass-vis').addEventListener('click', function() {
  var inp = document.getElementById('new-user-pass');
  inp.type = inp.type === 'password' ? 'text' : 'password';
  this.textContent = inp.type === 'password' ? '👁' : '🙈';
});

document.getElementById('add-user-btn').addEventListener('click', function() {
  var username = document.getElementById('new-user-name').value.trim();
  var password = document.getElementById('new-user-pass').value;
  var nameErr = validateNewUsername(username);
  var passErr = validateNewPassword(password);
  if (nameErr || passErr) return;
  this.disabled = true;
  apiFetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: username, password: password })
  })
    .then(function(r) {
      return r.json().then(function(d) { return { ok: r.ok, d: d }; });
    })
    .then(function(res) {
      if (res.ok) {
        showToast('Usuario "' + username + '" creado', 'success');
        var nameInp = document.getElementById('new-user-name');
        var passInp = document.getElementById('new-user-pass');
        nameInp.value = '';
        nameInp.className = nameInp.className.replace(/input-ok|input-error/g, '').trim();
        passInp.value = '';
        passInp.className = passInp.className.replace(/input-ok|input-error/g, '').trim();
        document.getElementById('new-user-name-err').textContent = '';
        document.getElementById('new-user-pass-err').textContent = '';
        document.getElementById('add-user-btn').disabled = true;
        loadUsers();
      } else {
        showToast(res.d.detail || 'Error al crear usuario', 'error');
        document.getElementById('add-user-btn').disabled = false;
      }
    })
    .catch(function() {
      showToast('Error de red', 'error');
      document.getElementById('add-user-btn').disabled = false;
    });
});
