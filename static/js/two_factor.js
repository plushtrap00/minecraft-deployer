// -- Verificación en dos pasos de la cuenta propia -------------------------------
// Diálogo partials/modals/two_factor.html, abierto desde «Cambiar contraseña».
// El backend está en routes/auth.py (/api/auth/2fa...) y services/two_factor.py.
var tfaModal = document.getElementById('tfa-modal');
var tfaRecoveryCodes = [];

function tfaShowView(name) {
  ['off', 'setup', 'codes', 'on'].forEach(function(view) {
    document.getElementById('tfa-view-' + view).hidden = view !== name;
  });
  document.getElementById('tfa-confirm').hidden = name !== 'setup';
  document.getElementById('tfa-done').hidden = name !== 'codes';
  document.getElementById('tfa-cancel').hidden = name === 'codes';
}

function tfaJson(url, body) {
  return apiJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
}

function openTwoFactorModal() {
  tfaModal.classList.add('show');
  ['tfa-setup-error', 'tfa-on-error'].forEach(function(id) { document.getElementById(id).textContent = ''; });
  document.getElementById('tfa-password').value = '';
  refreshTwoFactorStatus();
}

function refreshTwoFactorStatus() {
  apiJson('/api/auth/2fa').then(function(result) {
    if (!result.ok) {
      showToast(result.data.detail || t('No se pudo cargar'), 'error');
      return;
    }
    renderTwoFactorStatus(result.data);
  });
}

function renderTwoFactorStatus(status) {
  var line = document.getElementById('password-tfa-status');
  if (line) {
    line.textContent = status.enabled ? t('Activada') : t('Desactivada');
    line.dataset.on = status.enabled ? '1' : '0';
  }
  if (!tfaModal.classList.contains('show')) {
    return;
  }
  if (!status.enabled) {
    tfaShowView('off');
    return;
  }
  var left = status.recovery_left;
  var text = left === 1
    ? t('Activada. Te queda 1 código de recuperación.')
    : t('Activada. Te quedan {n} códigos de recuperación.', { n: left });
  document.getElementById('tfa-on-status').innerHTML = noticeHtml(left <= 2 ? 'warn' : 'ok', escHtml(text)
    + (left <= 2 ? ' ' + escHtml(t('Crea unos nuevos antes de quedarte sin ninguno.')) : ''));
  tfaShowView('on');
}

function closeTwoFactorModal() {
  // Los códigos recién creados no se cierran sin confirmar que se han guardado.
  if (!document.getElementById('tfa-view-codes').hidden) {
    return;
  }
  tfaModal.classList.remove('show');
}

// Clave en grupos de 4 para copiarla a mano sin perderse.
function tfaGroupSecret(secret) {
  return secret.replace(/(.{4})/g, '$1 ').trim();
}

document.getElementById('tfa-start').addEventListener('click', function() {
  var button = this;
  busyWhile(button, function() {
    return tfaJson('/api/auth/2fa/setup').then(function(result) {
      if (!result.ok) {
        showToast(result.data.detail || t('No se pudo empezar'), 'error');
        return;
      }
      // El SVG lo genera el propio panel (services/qr.py), no viene de fuera.
      document.getElementById('tfa-qr').innerHTML = result.data.qr_svg;
      document.getElementById('tfa-qr').setAttribute('aria-label', t('Código QR para la app de códigos'));
      document.getElementById('tfa-secret').textContent = tfaGroupSecret(result.data.secret);
      document.getElementById('tfa-code').value = '';
      document.getElementById('tfa-setup-error').textContent = '';
      tfaShowView('setup');
      setTimeout(function() { document.getElementById('tfa-code').focus(); }, 0);
    });
  });
});

function tfaConfirmSetup() {
  var button = document.getElementById('tfa-confirm');
  var code = document.getElementById('tfa-code').value.replace(/\s/g, '');
  var error = document.getElementById('tfa-setup-error');
  if (!/^\d{6}$/.test(code)) {
    error.textContent = t('Escribe las 6 cifras que muestra la app');
    return;
  }
  busyWhile(button, function() {
    return tfaJson('/api/auth/2fa/enable', { code: code }).then(function(result) {
      if (!result.ok) {
        error.textContent = result.data.detail || t('El código no es correcto');
        return;
      }
      showRecoveryCodes(result.data.recovery_codes);
      unlockAchievement('two-keys');
    });
  });
}

document.getElementById('tfa-confirm').addEventListener('click', tfaConfirmSetup);
document.getElementById('tfa-code').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    tfaConfirmSetup();
  }
});

function showRecoveryCodes(codes) {
  tfaRecoveryCodes = codes;
  document.getElementById('tfa-codes').innerHTML = codes.map(function(code) {
    return '<li><code>' + escHtml(code) + '</code></li>';
  }).join('');
  tfaShowView('codes');
}

function tfaCodesText() {
  return t('Códigos de recuperación de MC Deployer ({user}). Cada uno sirve una sola vez.', { user: currentUser })
    + '\n\n' + tfaRecoveryCodes.join('\n') + '\n';
}

// navigator.clipboard solo existe en https o localhost; el panel suele ir por
// http en la red de casa, así que se cae al método antiguo.
function tfaCopyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise(function(resolve, reject) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (err) {}
    area.remove();
    if (ok) {
      resolve();
    } else {
      reject(new Error('copy'));
    }
  });
}

document.getElementById('tfa-copy').addEventListener('click', function() {
  tfaCopyText(tfaCodesText()).then(function() {
    showToast(t('Copiados'), 'success');
  }, function() {
    showToast(t('No se pudieron copiar: selecciónalos y cópialos a mano'), 'error');
  });
});

document.getElementById('tfa-download').addEventListener('click', function() {
  var link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([tfaCodesText()], { type: 'text/plain' }));
  link.download = 'mc-deployer-recuperacion-' + currentUser + '.txt';
  document.body.appendChild(link);
  link.click();
  setTimeout(function() { URL.revokeObjectURL(link.href); link.remove(); }, 0);
});

document.getElementById('tfa-done').addEventListener('click', function() {
  tfaRecoveryCodes = [];
  document.getElementById('tfa-codes').innerHTML = '';
  tfaShowView('on');
  refreshTwoFactorStatus();
});

function tfaPasswordAction(url, onDone) {
  var password = document.getElementById('tfa-password').value;
  var error = document.getElementById('tfa-on-error');
  if (!password) {
    error.textContent = t('Escribe tu contraseña');
    document.getElementById('tfa-password').focus();
    return null;
  }
  error.textContent = '';
  return tfaJson(url, { password: password }).then(function(result) {
    if (!result.ok) {
      error.textContent = result.data.detail || t('No se pudo guardar');
      return;
    }
    document.getElementById('tfa-password').value = '';
    onDone(result.data);
  });
}

document.getElementById('tfa-new-codes').addEventListener('click', function() {
  var button = this;
  busyWhile(button, function() {
    return tfaPasswordAction('/api/auth/2fa/recovery', function(data) {
      showRecoveryCodes(data.recovery_codes);
    });
  });
});

document.getElementById('tfa-disable').addEventListener('click', function() {
  var button = this;
  if (!document.getElementById('tfa-password').value) {
    tfaPasswordAction('/api/auth/2fa/disable');
    return;
  }
  showConfirm(t('¿Desactivar la verificación en dos pasos?'), t('Para entrar volverá a bastar con la contraseña.'), function() {
    busyWhile(button, function() {
      return tfaPasswordAction('/api/auth/2fa/disable', function() {
        showToast(t('Verificación en dos pasos desactivada'), 'success');
        refreshTwoFactorStatus();
      });
    });
  }, { confirmLabel: t('Desactivar') });
});

document.getElementById('tfa-close').addEventListener('click', closeTwoFactorModal);
document.getElementById('tfa-cancel').addEventListener('click', closeTwoFactorModal);
tfaModal.addEventListener('click', function(event) {
  if (event.target === tfaModal) {
    closeTwoFactorModal();
  }
});
