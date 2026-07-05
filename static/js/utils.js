// -- Utility helpers ----------------------------------------------------------
function escHtml(str) {
  if (!str) {
    return '';
  }
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}


// -- Tab en editores de código: inserta indentación en vez de mover el foco ----
// Reutilizable en cualquier textarea de edición de código/config (config-editor,
// props-raw-editor, y cualquier otro que se agregue) sin repetir la lógica.
function enableCodeEditorTab(textarea) {
  textarea.addEventListener('keydown', function(event) {
    if (event.key !== 'Tab') {
      return;
    }
    event.preventDefault();

    var value = this.value;
    var start = this.selectionStart;
    var end = this.selectionEnd;
    var multiLine = value.substring(start, end).indexOf('\n') !== -1;

    if (!multiLine) {
      if (event.shiftKey) {
        var lineStart = value.lastIndexOf('\n', start - 1) + 1;
        var lineText = value.substring(lineStart, start);
        var match = lineText.match(/^\t|^ {1,2}/);
        var removed = match ? match[0].length : 0;
        if (removed > 0) {
          this.value = value.substring(0, lineStart) + value.substring(lineStart + removed);
          this.selectionStart = this.selectionEnd = start - removed;
        }
      } else {
        this.value = value.substring(0, start) + '\t' + value.substring(end);
        this.selectionStart = this.selectionEnd = start + 1;
      }
    } else {
      // Selección multi-línea: indenta/desindenta cada línea completa del
      // bloque (como en un editor de código real) y deja el bloque entero
      // seleccionado.
      var blockStart = value.lastIndexOf('\n', start - 1) + 1;
      var nextNewline = value.indexOf('\n', end);
      var blockEnd = nextNewline === -1 ? value.length : nextNewline;
      var lines = value.substring(blockStart, blockEnd).split('\n');

      var newLines = event.shiftKey
        ? lines.map(function(line) {
            var m = line.match(/^\t|^ {1,2}/);
            return m ? line.substring(m[0].length) : line;
          })
        : lines.map(function(line) { return '\t' + line; });

      var newBlock = newLines.join('\n');
      this.value = value.substring(0, blockStart) + newBlock + value.substring(blockEnd);
      this.selectionStart = blockStart;
      this.selectionEnd = blockStart + newBlock.length;
    }

    // Mutar .value a mano no dispara 'input' de forma nativa; se despacha uno
    // sintético para que listeners ya existentes (ej. el gutter de números de
    // línea) se refresquen solos, sin que este helper necesite saber de ellos.
    this.dispatchEvent(new Event('input'));
  });
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
    if (onConfirm) {
      onConfirm();
    }
  });
  overlay.classList.add('show');
}

document.getElementById('dialog-overlay').addEventListener('click', function(event) {
  if (event.target === this) {
    this.classList.remove('show');
  }
});


// -- Overlay de reinicio: bloquea toda la app hasta que vuelva a responder ----
// El estado real ("¿está reiniciando?") vive en sysmon.js (beginRestartWatch),
// que ya corre siempre en segundo plano desde que carga la página -- acá solo
// las funciones de mostrar/ocultar, para que cualquier archivo pueda usarlas
// sin duplicar el overlay ni su poll.
function showRestartOverlay(title, sub) {
  document.getElementById('restart-overlay-title').textContent = title || 'La app se está reiniciando...';
  document.getElementById('restart-overlay-sub').textContent = sub || 'Esto puede tardar unos segundos. No cierres esta pestaña.';
  document.getElementById('restart-overlay').classList.add('show');
}

function hideRestartOverlay() {
  document.getElementById('restart-overlay').classList.remove('show');
}


// -- Toast --------------------------------------------------------------------
function showToast(msg, type) {
  var toastEl = document.getElementById('toast');
  toastEl.textContent = msg;
  toastEl.className = 'toast show ' + (type || '');
  setTimeout(function() {
    toastEl.className = 'toast';
  }, 3000);
}
