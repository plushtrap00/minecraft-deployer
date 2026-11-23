// ── Gestión de usuarios (admin) ───────────────────────────────────────────────
function loadUsers() {
  apiFetch('/api/users')
    .then(function(r) { return r.json(); })
    .then(function(users) {
      var list = document.getElementById('users-list');
      if (!users.length) {
        list.innerHTML = '<p class="empty-msg">' + t('No hay usuarios.') + '</p>';
        return;
      }
      list.innerHTML = users.map(function(u) {
        var isAdmin = u.role === 'admin';
        var badge = isAdmin
          ? '<span class="role-badge role-admin">Admin</span>'
          : '<span class="role-badge role-user">' + t('Usuario') + '</span>';
        var tfa = u.two_factor
          ? '<span class="role-badge role-tfa" title="' + escHtml(t('Verificación en dos pasos activada')) + '">' + icon('shield') + '2FA</span>'
          : '';
        var actions = isAdmin ? '' :
          '<div class="pe-actions">'
          + (u.two_factor ? '<button class="btn-ghost user-tfa-btn btn-xs" data-user="' + escHtml(u.username) + '">' + icon('shield') + t('Quitar 2FA') + '</button>' : '')
          + '<button class="btn-ghost user-password-btn btn-xs" data-user="' + escHtml(u.username) + '">' + icon('lock') + t('Cambiar contraseña') + '</button>'
          + '<button class="btn-danger user-delete-btn btn-xs" data-user="' + escHtml(u.username) + '">' + icon('trash-2') + t('Eliminar') + '</button></div>';
        return '<div class="player-entry">'
          + '<span class="pe-name">' + escHtml(u.username) + '</span>'
          + badge + tfa + actions
          + '</div>';
      }).join('');
    })
    .catch(function() {
      document.getElementById('users-list').innerHTML = '<p class="empty-msg">' + t('Error cargando usuarios.') + '</p>';
    });
}

function deleteUser(username, button) {
  showConfirm(
    t('Eliminar a {user}', { user: username }),
    t('Esta cuenta ya no podrá entrar al panel. Esta acción no se puede deshacer.'),
    function() { doDeleteUser(username, button); },
    { confirmLabel: t('Eliminar usuario') }
  );
}

function doDeleteUser(username, button) {
  busyWhile(button, function() {
    return apiFetch('/api/users/' + encodeURIComponent(username), { method: 'DELETE' })
      .then(function(r) {
        return r.json().then(function(d) { return { ok: r.ok, d: d }; });
      })
      .then(function(res) {
        if (res.ok) {
          showToast(t('Usuario eliminado'), 'success');
          loadUsers();
        } else {
          showToast(res.d.detail || t('No se pudo eliminar el usuario'), 'error');
        }
      })
      .catch(function() { showToast(t('No se pudo conectar con el panel'), 'error'); });
  });
}

document.getElementById('btn-refresh-users').addEventListener('click', loadUsers);
document.getElementById('users-list').addEventListener('click', function(event) {
  var btn = event.target.closest('.user-delete-btn');
  if (btn) {
    deleteUser(btn.dataset.user, btn);
  }
  var pwBtn = event.target.closest('.user-password-btn');
  if (pwBtn) {
    openPasswordModal(pwBtn.dataset.user);
  }
  var tfaBtn = event.target.closest('.user-tfa-btn');
  if (tfaBtn) {
    removeUserTwoFactor(tfaBtn.dataset.user, tfaBtn);
  }
});

// Validación del formulario de nuevo usuario
var USERNAME_RE = /^[a-zA-Z0-9_-]+$/;
var PRINTABLE_RE = /^[\x20-\x7E]+$/;

function validateNewUsername(val) {
  if (!val) return t('El nombre de usuario es obligatorio');
  if (val.length > 16) return t('Máximo 16 caracteres');
  if (!USERNAME_RE.test(val)) return t('Solo se permiten letras, números, guion bajo (_) y guion (-)');
  return '';
}

function validateNewPassword(val) {
  if (!val) return t('La contraseña es obligatoria');
  if (val.length < 8) return t('Mínimo 8 caracteres');
  if (val.length > 72) return t('Máximo 72 caracteres');
  if (!PRINTABLE_RE.test(val)) return t('Solo se permiten caracteres estándar (sin emojis ni símbolos raros)');
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
  this.innerHTML = icon(inp.type === 'password' ? 'eye' : 'eye-off');
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
        showToast(t('Usuario «{user}» creado', { user: username }), 'success');
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
        showToast(res.d.detail || t('Error al crear usuario'), 'error');
        document.getElementById('add-user-btn').disabled = false;
      }
    })
    .catch(function() {
      showToast(t('No se pudo conectar con el panel. Comprueba la conexión y vuelve a intentarlo.'), 'error');
      document.getElementById('add-user-btn').disabled = false;
    });
});

// Por si alguien pierde el móvil y también sus códigos de recuperación.
function removeUserTwoFactor(username, button) {
  showConfirm(t('¿Quitar la verificación en dos pasos a {user}?', { user: username }),
    t('Podrá entrar solo con su contraseña hasta que la vuelva a activar.'), function() {
      busyWhile(button, function() {
        return apiJson('/api/users/' + encodeURIComponent(username) + '/two-factor', { method: 'DELETE' }).then(function(result) {
          showToast(result.ok ? t('Verificación en dos pasos quitada') : (result.data.detail || t('No se pudo quitar')), result.ok ? 'success' : 'error');
          loadUsers();
        });
      });
    }, { confirmLabel: t('Quitar') });
}
