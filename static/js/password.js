// -- Contraseñas ---------------------------------------------------------------------
// Un mismo diálogo (partials/modals/password.html) para dos cosas:
// - Cualquier usuario cambia la suya (botón «Contraseña» del menú): pide la actual.
// - El admin pone una nueva a otro usuario (página Usuarios): no la pide.
var passwordModal = document.getElementById('password-modal');
var passwordTarget = null; // null = la propia; si no, el nombre del usuario

function openPasswordModal(targetUser) {
  passwordTarget = targetUser || null;
  var own = passwordTarget === null;
  document.getElementById('password-title').textContent = own ? 'Cambiar contraseña' : 'Contraseña de ' + passwordTarget;
  document.getElementById('password-intro').textContent = own
    ? 'Para cambiarla hace falta la que usas ahora.'
    : 'Pon una contraseña nueva para «' + passwordTarget + '» y pásasela.';
  // style.display y no el atributo hidden: .prop-field fija su propio display.
  document.getElementById('password-current-field').style.display = own ? '' : 'none';
  document.getElementById('password-username').value = own ? (currentUser || '') : passwordTarget;
  ['password-current', 'password-new', 'password-repeat'].forEach(function(id) {
    document.getElementById(id).value = '';
  });
  document.getElementById('password-error').textContent = '';
  passwordModal.classList.add('show');
  setTimeout(function() {
    document.getElementById(own ? 'password-current' : 'password-new').focus();
  }, 0);
}

function closePasswordModal() {
  if (!document.getElementById('password-submit').disabled) {
    passwordModal.classList.remove('show');
  }
}

function passwordFormError() {
  var own = passwordTarget === null;
  var current = document.getElementById('password-current').value;
  var next = document.getElementById('password-new').value;
  var repeat = document.getElementById('password-repeat').value;
  if (own && !current) {
    return 'Escribe tu contraseña actual';
  }
  var error = validateNewPassword(next);
  if (error) {
    return error;
  }
  if (next !== repeat) {
    return 'Las dos contraseñas nuevas no coinciden';
  }
  if (own && next === current) {
    return 'La contraseña nueva es igual que la actual';
  }
  return '';
}

document.getElementById('btn-password').addEventListener('click', function() {
  openPasswordModal(null);
});
document.getElementById('password-close').addEventListener('click', closePasswordModal);
document.getElementById('password-cancel').addEventListener('click', closePasswordModal);
passwordModal.addEventListener('click', function(event) {
  if (event.target === passwordModal) {
    closePasswordModal();
  }
});

document.getElementById('password-form').addEventListener('submit', function(event) {
  event.preventDefault();
  var errorEl = document.getElementById('password-error');
  var error = passwordFormError();
  errorEl.textContent = error;
  if (error) {
    return;
  }
  var own = passwordTarget === null;
  var next = document.getElementById('password-new').value;
  var url = own ? '/api/auth/password' : '/api/users/' + encodeURIComponent(passwordTarget) + '/password';
  var body = own
    ? { current_password: document.getElementById('password-current').value, new_password: next }
    : { password: next };
  var submit = document.getElementById('password-submit');
  submit.disabled = true;
  submit.textContent = 'Guardando…';
  apiJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(function(result) {
    submit.disabled = false;
    submit.textContent = 'Guardar';
    if (!result.ok) {
      errorEl.textContent = result.data.detail || 'No se pudo cambiar la contraseña';
      return;
    }
    passwordModal.classList.remove('show');
    showToast(own ? 'Contraseña cambiada' : 'Contraseña de «' + passwordTarget + '» cambiada', 'success');
  });
});
