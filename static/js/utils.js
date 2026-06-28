// -- Utility helpers ----------------------------------------------------------
function escHtml(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}


// -- Dialog (alert / confirm) -------------------------------------------------
function showAlert(msg, icon) {
  var overlay = document.getElementById('dialog-overlay');
  document.getElementById('dialog-icon').textContent = icon || 'ℹ️';
  document.getElementById('dialog-title').textContent = 'Aviso';
  document.getElementById('dialog-msg').textContent = msg;
  var btns = document.getElementById('dialog-buttons');
  btns.innerHTML = '<button id="dialog-ok">Aceptar</button>';
  document.getElementById('dialog-ok').addEventListener('click', function() {
    overlay.classList.remove('show');
  });
  overlay.classList.add('show');
}

function showConfirm(title, msg, onConfirm) {
  var overlay = document.getElementById('dialog-overlay');
  document.getElementById('dialog-icon').textContent = '⚠️';
  document.getElementById('dialog-title').textContent = title;
  document.getElementById('dialog-msg').textContent = msg;
  var btns = document.getElementById('dialog-buttons');
  btns.innerHTML = '<button class="btn-secondary" id="dialog-cancel">Cancelar</button>'
    + '<button id="dialog-ok" style="background:var(--red);color:#fff">Confirmar</button>';
  document.getElementById('dialog-cancel').addEventListener('click', function() {
    overlay.classList.remove('show');
  });
  document.getElementById('dialog-ok').addEventListener('click', function() {
    overlay.classList.remove('show');
    if (onConfirm) onConfirm();
  });
  overlay.classList.add('show');
}

document.getElementById('dialog-overlay').addEventListener('click', function(e) {
  if (e.target === this) this.classList.remove('show');
});


// -- Toast --------------------------------------------------------------------
function showToast(msg, type) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (type || '');
  setTimeout(function() {
    t.className = 'toast';
  }, 3000);
}
