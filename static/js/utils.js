// -- Utility helpers ----------------------------------------------------------
function escHtml(str) {
  if (str === null || str === undefined) {
    return '';
  }
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Solo enlaces http(s): los page_url vienen de Modrinth/CurseForge y un
// "javascript:" en un href se ejecutaría al hacer clic.
function isWebUrl(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url);
}

function escRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Icono del sprite SVG de index.html (Lucide). Devuelve HTML para meterlo en
// cadenas de innerHTML; hereda el color y el tamaño del texto que lo rodea.
function icon(name) {
  return '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
}

// Bloque de carga con la forma aproximada de una lista (ver .skeleton-rows en
// base.css), en lugar de un "Cargando..." suelto.
function loadingHtml() {
  return '<div class="skeleton-rows" role="status" aria-label="Cargando"><div></div><div></div><div></div></div>';
}

// "hace 3 días", "ayer", "hace 2 h"... para fechas en segundos epoch.
function formatRelativeDate(epochSeconds) {
  var sec = Math.max(0, Math.floor(Date.now() / 1000 - epochSeconds));
  if (sec < 3600) {
    return sec < 120 ? 'ahora mismo' : 'hace ' + Math.floor(sec / 60) + ' min';
  }
  if (sec < 86400) {
    return 'hace ' + Math.floor(sec / 3600) + ' h';
  }
  var days = Math.floor(sec / 86400);
  if (days === 1) {
    return 'ayer';
  }
  if (days < 30) {
    return 'hace ' + days + ' días';
  }
  return new Date(epochSeconds * 1000).toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' });
}

// Los diálogos y modales reciben su icono como emoji desde muchos sitios
// (showConfirm(..., { icon: '⏳' }), openModListModal(title, '✅', ...)): aquí
// se traducen al icono SVG equivalente para que todo use el mismo juego. Un
// emoji sin equivalente se muestra tal cual. También aceptan directamente el
// nombre de un icono del sprite ('circle-check').
var EMOJI_ICONS = {
  '📦': 'package', '⚠️': 'triangle-alert', '⚠': 'triangle-alert', '✅': 'circle-check',
  '❌': 'circle-x', '🔧': 'wrench', '🖥️': 'monitor', '📥': 'download', '⬇️': 'download',
  '🔗': 'link', '🗑': 'trash-2', '🗑️': 'trash-2', '⏳': 'clock', '🔄': 'refresh-cw',
  'ℹ️': 'info', '⏹': 'square', '⏻': 'log-out', '🧩': 'puzzle', '🔎': 'search', '🔍': 'search'
};

function emojiIcon(emoji) {
  var name = EMOJI_ICONS[emoji] || (/^[a-z0-9-]+$/.test(emoji || '') ? emoji : null);
  return name ? icon(name) : escHtml(emoji || '');
}

// Aviso en línea con su icono: kind es 'ok', 'warn', 'error' o 'info' (ver
// .notice en base.css). html ya tiene que venir escapado.
var NOTICE_ICONS = { ok: 'circle-check', warn: 'triangle-alert', error: 'circle-x', info: 'info' };

function noticeHtml(kind, html) {
  return '<div class="notice notice-' + kind + '">' + icon(NOTICE_ICONS[kind]) + '<div>' + html + '</div></div>';
}

// Etiqueta de modloader con su color propio (ver .loader-tag en server.css).
// Vanilla o desconocido salen en gris; la versión de MC no lleva etiqueta.
function loaderTag(modloader) {
  if (!modloader) {
    return '<span class="loader-tag">Vanilla</span>';
  }
  return '<span class="loader-tag" data-loader="' + escHtml(modloader.toLowerCase()) + '">'
    + escHtml(modloader) + '</span>';
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
  document.getElementById('dialog-icon').innerHTML = emojiIcon(icon || 'ℹ️');
  document.getElementById('dialog-title').textContent = 'Aviso';
  document.getElementById('dialog-msg').textContent = msg;
  var btns = document.getElementById('dialog-buttons');
  btns.innerHTML = '<button id="dialog-ok">Aceptar</button>';
  document.getElementById('dialog-ok').addEventListener('click', function() {
    overlay.classList.remove('show');
  });
  openDialogOverlay(overlay);
}

// Si el diálogo ya estaba abierto (una confirmación que encadena otra), los
// botones son nuevos y el foco se habría quedado en el que ya no existe.
function openDialogOverlay(overlay) {
  overlay.classList.add('show');
  setTimeout(function() { focusInsideModal(overlay); }, 0);
}

// options es opcional: { icon, confirmLabel, cancelLabel, tone, onCancel }
// (tone: 'red' por defecto, 'accent' o 'yellow'; ver .btn-tone-* en base.css)
// — por defecto se comporta igual que antes (confirmación destructiva en
// rojo), pero permite reusar el mismo diálogo para acciones no destructivas
// (p.ej. "¿reiniciar la app ahora o más tarde?") con textos y color propios.
function showConfirm(title, msg, onConfirm, options) {
  options = options || {};
  var overlay = document.getElementById('dialog-overlay');
  document.getElementById('dialog-icon').innerHTML = emojiIcon(options.icon || '⚠️');
  document.getElementById('dialog-title').textContent = title;
  document.getElementById('dialog-msg').textContent = msg;
  var btns = document.getElementById('dialog-buttons');
  var tone = options.tone || 'red';
  btns.innerHTML = '<button class="btn-secondary" id="dialog-cancel">' + escHtml(options.cancelLabel || 'Cancelar') + '</button>'
    + '<button id="dialog-ok" class="btn-tone-' + tone + '">' + escHtml(options.confirmLabel || 'Confirmar') + '</button>';
  document.getElementById('dialog-cancel').addEventListener('click', function() {
    overlay.classList.remove('show');
    if (options.onCancel) {
      options.onCancel();
    }
  });
  document.getElementById('dialog-ok').addEventListener('click', function() {
    overlay.classList.remove('show');
    if (onConfirm) {
      onConfirm();
    }
  });
  openDialogOverlay(overlay);
}

// Pulsar fuera del diálogo es lo mismo que «Cancelar» (con su onCancel).
document.getElementById('dialog-overlay').addEventListener('click', function(event) {
  if (event.target === this) {
    var cancel = document.getElementById('dialog-cancel') || document.getElementById('dialog-ok');
    if (cancel) {
      cancel.click();
    } else {
      this.classList.remove('show');
    }
  }
});


// -- Overlay de reinicio: bloquea toda la app hasta que vuelva a responder ----
// El estado real ("¿está reiniciando?") vive en sysmon.js (beginRestartWatch),
// que ya corre siempre en segundo plano desde que carga la página -- aquí solo
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
// Cada aviso es un elemento propio dentro de #toast: si llegan dos seguidos se
// apilan y cada uno desaparece a su tiempo (antes el segundo pisaba al primero
// y el temporizador del primero ocultaba el segundo antes de tiempo). Los de
// error duran algo más, que suelen traer texto que hay que leer.
var TOAST_MAX = 4;

function showToast(msg, type) {
  var stack = document.getElementById('toast');
  var toastEl = document.createElement('div');
  toastEl.className = 'toast' + (type ? ' ' + type : '');
  toastEl.textContent = msg;
  stack.appendChild(toastEl);
  while (stack.children.length > TOAST_MAX) {
    stack.removeChild(stack.firstChild);
  }
  requestAnimationFrame(function() {
    toastEl.classList.add('show');
  });
  setTimeout(function() {
    toastEl.classList.remove('show');
    setTimeout(function() {
      if (toastEl.parentNode) {
        toastEl.parentNode.removeChild(toastEl);
      }
    }, 300);
  }, type === 'error' ? 5000 : 3000);
}


// -- Modales: Escape, foco y Tab ----------------------------------------------
// Vale para todos los .modal-overlay sin que cada uno tenga que hacer nada:
// - Escape cierra el de más arriba pulsando su propio botón de cerrar (o el
//   «Cancelar» del diálogo), así se respetan las comprobaciones que ya tenga
//   ese botón (cambios sin guardar, operación en curso...).
// - Al abrirse se lleva el foco dentro; al cerrarse vuelve al elemento que
//   lo tenía antes (normalmente el botón que lo abrió).
// - Tab y Mayús+Tab no se salen del modal de arriba.
var FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), '
  + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function topModal() {
  var open = document.querySelectorAll('.modal-overlay.show');
  return open.length ? open[open.length - 1] : null;
}

function visibleFocusables(container) {
  return Array.prototype.filter.call(container.querySelectorAll(FOCUSABLE_SELECTOR), function(el) {
    return el.offsetParent !== null || el === document.activeElement;
  });
}

function focusInsideModal(overlay) {
  var target;
  if (overlay.id === 'dialog-overlay') {
    // En una confirmación el foco va a «Cancelar»: un Enter despistado no
    // debe borrar nada.
    target = document.getElementById('dialog-cancel') || document.getElementById('dialog-ok');
  } else {
    target = overlay.querySelector('[autofocus]')
      || visibleFocusables(overlay).filter(function(el) {
        return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
      })[0]
      || overlay.querySelector('.modal-close');
  }
  if (target) {
    target.focus({ preventScroll: true });
  }
}

function closeTopModal(overlay) {
  if (overlay.id === 'dialog-overlay') {
    var cancel = document.getElementById('dialog-cancel') || document.getElementById('dialog-ok');
    if (cancel) {
      cancel.click();
    }
    return;
  }
  var closeBtn = overlay.querySelector('.modal-close');
  if (closeBtn) {
    closeBtn.click();
  } else {
    overlay.classList.remove('show');
  }
}

(function watchModals() {
  var observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
      var overlay = mutation.target;
      var isOpen = overlay.classList.contains('show');
      if (isOpen && !overlay._modalOpen) {
        overlay._modalOpen = true;
        var active = document.activeElement;
        overlay._returnFocus = active && !overlay.contains(active) ? active : null;
        setTimeout(function() { focusInsideModal(overlay); }, 0);
      } else if (!isOpen && overlay._modalOpen) {
        overlay._modalOpen = false;
        var back = overlay._returnFocus;
        overlay._returnFocus = null;
        if (back && document.contains(back) && !topModal()) {
          back.focus({ preventScroll: true });
        }
      }
    });
  });
  document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    observer.observe(overlay, { attributes: true, attributeFilter: ['class'] });
  });
})();

document.addEventListener('keydown', function(event) {
  var overlay = topModal();
  if (!overlay) {
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    closeTopModal(overlay);
    return;
  }
  if (event.key === 'Tab') {
    var items = visibleFocusables(overlay);
    if (!items.length) {
      return;
    }
    var first = items[0];
    var last = items[items.length - 1];
    if (!overlay.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});


// -- Interruptores y etiquetas accesibles -------------------------------------
// Los interruptores (.toggle-track) son <div>: aquí se les da role="switch",
// foco con Tab, Espacio/Enter para cambiarlos y aria-checked al día. Y cada
// etiqueta de campo (.prop-label, .field-label) se enlaza con su control, que
// así se enfoca al pulsar el texto y los lectores de pantalla saben qué es.
// Un MutationObserver lo aplica también a lo que se pinta después (formulario
// de config de mods, RAM...), sin que cada render tenga que acordarse.
var a11yIdCounter = 0;

function ensureId(el, prefix) {
  if (!el.id) {
    a11yIdCounter += 1;
    el.id = prefix + '-' + a11yIdCounter;
  }
  return el.id;
}

function enhanceToggle(track) {
  if (track.dataset.a11y) {
    return;
  }
  track.dataset.a11y = '1';
  track.setAttribute('role', 'switch');
  if (!track.hasAttribute('tabindex')) {
    track.tabIndex = 0;
  }
  track.setAttribute('aria-checked', track.classList.contains('on') ? 'true' : 'false');
  if (!track.hasAttribute('aria-label') && !track.hasAttribute('aria-labelledby')) {
    // En una fila «interruptor + texto» el texto es el span de al lado.
    var row = track.closest('.toggle-row');
    var text = row && row.querySelector('span:not(.ram-info)');
    if (text) {
      track.setAttribute('aria-labelledby', ensureId(text, 'lbl'));
    }
  }
}

function linkFieldLabel(label) {
  if (label.htmlFor || label.dataset.a11y) {
    return;
  }
  label.dataset.a11y = '1';
  var field = label.parentElement;
  var control = field && field.querySelector('input:not([type="hidden"]), select, textarea, .toggle-track');
  if (!control) {
    return;
  }
  if (control.classList.contains('toggle-track')) {
    control.setAttribute('aria-labelledby', ensureId(label, 'lbl'));
    // Pulsar el texto de un interruptor también lo cambia, como en un checkbox.
    label.addEventListener('click', function() { control.click(); });
  } else if (label.tagName === 'LABEL') {
    label.htmlFor = ensureId(control, 'fld');
  } else {
    control.setAttribute('aria-labelledby', ensureId(label, 'lbl'));
  }
}

function enhanceA11y(root) {
  if (!root.querySelectorAll) {
    return;
  }
  if (root.matches && root.matches('.toggle-track')) {
    enhanceToggle(root);
  }
  root.querySelectorAll('.toggle-track').forEach(enhanceToggle);
  root.querySelectorAll('.prop-label, .field-label').forEach(linkFieldLabel);
}

document.addEventListener('keydown', function(event) {
  var track = event.target.closest && event.target.closest('.toggle-track[role="switch"]');
  if (track && (event.key === ' ' || event.key === 'Enter')) {
    event.preventDefault();
    track.click();
  }
});

(function watchA11y() {
  enhanceA11y(document.body);
  new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
      if (mutation.type === 'attributes') {
        var track = mutation.target;
        if (track.classList.contains('toggle-track')) {
          track.setAttribute('aria-checked', track.classList.contains('on') ? 'true' : 'false');
        }
        return;
      }
      mutation.addedNodes.forEach(function(node) {
        if (node.nodeType === 1) {
          enhanceA11y(node);
        }
      });
    });
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
})();


// -- Cambios sin guardar ------------------------------------------------------
// Cada formulario que se puede quedar a medias se registra con
// registerUnsaved(): un nombre para el aviso, una función que dice si hay
// cambios y otra que los descarta. Antes de cambiar de página, de modpack o
// de pestaña (o de cerrar el editor) se llama a confirmLeave(): si hay
// cambios pregunta, y si no sigue directamente. Al recargar o cerrar la
// pestaña del navegador avisa el propio navegador.
var unsavedSources = {};

function registerUnsaved(key, label, isDirty, discard) {
  unsavedSources[key] = { label: label, isDirty: isDirty, discard: discard };
}

function dirtySources(keys) {
  return (keys || Object.keys(unsavedSources)).map(function(key) {
    return unsavedSources[key];
  }).filter(function(source) {
    return source && source.isDirty();
  });
}

// keys (opcional): solo mirar esos formularios, p.ej. ['editor'] al cerrar el
// editor de archivos. onCancel (opcional): si el usuario decide quedarse.
function confirmLeave(proceed, keys, onCancel) {
  var dirty = dirtySources(keys);
  if (!dirty.length) {
    proceed();
    return;
  }
  var names = dirty.map(function(source) { return source.label; }).join(' y ');
  showConfirm(
    'Hay cambios sin guardar',
    'Tienes cambios sin guardar en ' + names + '. Si sigues, se perderán.',
    function() {
      dirty.forEach(function(source) {
        if (source.discard) {
          source.discard();
        }
      });
      proceed();
    },
    { confirmLabel: 'Descartar cambios', cancelLabel: 'Seguir editando', onCancel: onCancel }
  );
}

window.addEventListener('beforeunload', function(event) {
  if (dirtySources().length) {
    event.preventDefault();
    event.returnValue = '';
  }
});
