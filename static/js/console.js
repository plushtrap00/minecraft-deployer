// Consola del servidor en marcha (página Servidor): líneas en vivo por SSE
// con sus colores, vista de chat, comandos e historial de comandos. El
// estado del servidor y la cabecera están en server.js.

// -- Consola ---------------------------------------------------------------------
// Dos vistas de la misma consola: todo, o solo el chat (mensajes, entradas y
// salidas y lo dicho con say). En la de chat, lo que se escribe se manda con say.
var consoleChatMode = false;

function setConsoleView(chat) {
  consoleChatMode = chat;
  document.getElementById('console').classList.toggle('chat-only', chat);
  document.getElementById('console-view-log').classList.toggle('active', !chat);
  document.getElementById('console-view-chat').classList.toggle('active', chat);
  document.getElementById('console-view-log').setAttribute('aria-selected', chat ? 'false' : 'true');
  document.getElementById('console-view-chat').setAttribute('aria-selected', chat ? 'true' : 'false');
  var input = document.getElementById('cmd-input');
  input.placeholder = chat ? 'Escribe un mensaje para los jugadores…' : 'Escribe un comando: say Hola, list, whitelist add Alex…';
  input.setAttribute('aria-label', chat ? 'Mensaje para los jugadores' : 'Comando para el servidor');
  document.querySelector('.cmd-prompt').innerHTML = chat ? icon('message-square') : '&gt;';
  var consoleEl = document.getElementById('console');
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

document.getElementById('console-view-log').addEventListener('click', function() { setConsoleView(false); });
document.getElementById('console-view-chat').addEventListener('click', function() { setConsoleView(true); });

var cmdHistory = [];
var cmdHistoryPos = 0;

document.getElementById('cmd-send-btn').addEventListener('click', sendCommand);
document.getElementById('cmd-input').addEventListener('keydown', function(event) {
  if (event.key === 'Enter') {
    sendCommand();
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    // Historial de comandos como en una terminal: ↑ el anterior, ↓ el siguiente.
    if (!cmdHistory.length) {
      return;
    }
    event.preventDefault();
    cmdHistoryPos += event.key === 'ArrowUp' ? -1 : 1;
    cmdHistoryPos = Math.max(0, Math.min(cmdHistory.length, cmdHistoryPos));
    this.value = cmdHistory[cmdHistoryPos] || '';
  }
});

function sendCommand() {
  var input = document.getElementById('cmd-input');
  var cmd = input.value.trim();
  if (!cmd) {
    return;
  }
  input.value = '';
  if (consoleChatMode) {
    // En la vista Chat lo escrito es un mensaje para los jugadores.
    sendServerCommand('say ' + cmd).then(function(ok) {
      if (ok) {
        unlockAchievement('herald');
      }
    });
    return;
  }
  if (cmdHistory[cmdHistory.length - 1] !== cmd) {
    cmdHistory.push(cmd);
    if (cmdHistory.length > 50) {
      cmdHistory.shift();
    }
  }
  cmdHistoryPos = cmdHistory.length;
  sendServerCommand(cmd).then(function(ok) {
    if (ok && /^\/?say\s+\S/i.test(cmd)) {
      unlockAchievement('herald');
    }
    if (ok && /^\/?stop$/i.test(cmd)) {
      unlockAchievement('hard-stop');
    }
    if (ok && /^\/?(weather\s|time\s+set\s)/i.test(cmd)) {
      unlockAchievement('weatherman');
    }
  });
}

function sendServerCommand(cmd) {
  var form = new FormData();
  form.append('cmd', cmd);
  appendConsoleNode('> ' + cmd, 'log-cmd');
  return apiFetch('/api/server/command', { method: 'POST', body: form })
    .then(function(response) {
      if (!response.ok) {
        showToast('El servidor no aceptó el comando', 'error');
      }
      return response.ok;
    })
    .catch(function() {
      showToast('No se pudo enviar el comando', 'error');
      return false;
    });
}

function startSSE() {
  sseSource = new EventSource('/api/server/logs');
  sseSource.onmessage = function(event) {
    if (event.data === '__STOPPED__') {
      applyServerState(false, null);
      return;
    }
    appendLine(event.data);
  };
  sseSource.onerror = function() {
    setTimeout(function() {
      if (serverRunning && !sseSource) {
        startSSE();
      }
    }, 3000);
  };
}

// Formato típico de Forge/NeoForge/Fabric/vanilla:
//   [14:02:15] [Server thread/INFO] [net.minecraft.server.Main/]: mensaje
// La hora y el origen se atenúan para que destaque el mensaje; el nivel
// decide el color de toda la línea.
var LOG_LINE_RE = /^(\[[0-9:.]+\])(\s*\[[^\]]*\/(INFO|WARN|ERROR|FATAL|DEBUG)\](?:\s*\[[^\]]*\])?:?)?(.*)$/;
var JOIN_RE = /^\s*([A-Za-z0-9_]{1,16}) (joined|left) the game\s*$/;
var CHAT_RE = /^(\s*(?:\[Not Secure\] )?)<([A-Za-z0-9_]{1,16})> (.*)$/;
// Lo que se dice con say desde la consola, el panel o RCON.
var SAY_RE = /^\s*(?:\[Not Secure\] )?\[(Server|Rcon)\] /;
// Códigos de formato de Minecraft (§a, §l...): cada letra es un color o un
// estilo; §r lo quita todo. §k (texto revuelto) se ignora.
var MC_FORMAT_RE = /§([0-9a-fk-or])/gi;
var MC_STYLES = { l: 'mc-bold', o: 'mc-italic', n: 'mc-underline', m: 'mc-strike' };

function appendMcFormatted(parent, text) {
  if (text.indexOf('§') === -1) {
    parent.appendChild(document.createTextNode(text));
    return;
  }
  var color = null;
  var styles = {};
  var last = 0;
  var flush = function(end) {
    if (end <= last) {
      return;
    }
    var chunk = text.slice(last, end);
    var classes = Object.keys(styles);
    if (color !== null) {
      classes.push('mc-' + color);
    }
    if (!classes.length) {
      parent.appendChild(document.createTextNode(chunk));
      return;
    }
    var span = document.createElement('span');
    span.className = classes.join(' ');
    span.textContent = chunk;
    parent.appendChild(span);
  };
  var match;
  MC_FORMAT_RE.lastIndex = 0;
  while ((match = MC_FORMAT_RE.exec(text)) !== null) {
    flush(match.index);
    last = match.index + match[0].length;
    var code = match[1].toLowerCase();
    if (/[0-9a-f]/.test(code)) {
      // Un color nuevo, como en el juego, también quita los estilos.
      color = code;
      styles = {};
    } else if (code === 'r') {
      color = null;
      styles = {};
    } else if (MC_STYLES[code]) {
      styles[MC_STYLES[code]] = true;
    }
  }
  flush(text.length);
}

// El mensaje de una línea: entradas y salidas de jugadores con su cabeza,
// nombre resaltado en el chat y el resto con sus códigos de color.
function appendLogMessage(div, message) {
  var join = message.match(JOIN_RE);
  if (join) {
    div.classList.add(join[2] === 'joined' ? 'log-join' : 'log-leave', 'is-chat');
    div.insertAdjacentHTML('beforeend', ' ' + headHtml(join[1], null, 'sm') + ' ');
    div.appendChild(document.createTextNode(message.trim()));
    return;
  }
  var chat = message.match(CHAT_RE);
  if (chat) {
    div.classList.add('is-chat');
    div.appendChild(document.createTextNode(chat[1]));
    var who = document.createElement('span');
    who.className = 'log-chat-name';
    who.textContent = '<' + chat[2] + '>';
    div.appendChild(who);
    div.appendChild(document.createTextNode(' '));
    appendMcFormatted(div, chat[3]);
    return;
  }
  if (SAY_RE.test(message)) {
    div.classList.add('is-chat', 'log-say');
  }
  appendMcFormatted(div, message);
}

function appendLine(line) {
  // Restos de colores ANSI: con el ESC delante, o ya sin él pero siempre con
  // al menos un número ("[0m", "[32;1m"). Sin exigir el número, "[m" se
  // comía el principio de "[main/INFO]" o "[mixin/]".
  var clean = line.replace(/\x1b\[[0-9;]*m|\[[0-9;]+m/g, '');
  trackStartupLine(clean);
  var lineLower = clean.toLowerCase();
  var match = clean.match(LOG_LINE_RE);
  var level = match && match[3];
  var cls = '';
  if (level === 'ERROR' || level === 'FATAL' || (!level && (lineLower.indexOf('error') !== -1 || lineLower.indexOf('exception') !== -1))) {
    cls = 'log-error';
  } else if (level === 'WARN' || (!level && lineLower.indexOf('warn') !== -1)) {
    cls = 'log-warn';
  } else if (DONE_LINE_RE.test(clean)) {
    cls = 'log-done';
  } else if (clean.indexOf('[Deployer]') !== -1) {
    cls = 'log-deployer';
    if (clean.indexOf('tras la caída') !== -1) {
      unlockAchievement('phoenix');
    }
  }
  var div = appendConsoleNode(null, cls);
  if (match && match[2]) {
    var ts = document.createElement('span');
    ts.className = 'ts';
    ts.textContent = match[1];
    var src = document.createElement('span');
    src.className = 'src';
    src.textContent = match[2];
    div.appendChild(ts);
    div.appendChild(src);
    appendLogMessage(div, match[4]);
  } else {
    appendMcFormatted(div, clean);
  }
  scrollConsoleIfFollowing();
}

function appendConsoleNode(text, cls) {
  var consoleEl = document.getElementById('console');
  var div = document.createElement('div');
  if (cls) {
    div.className = cls;
  }
  if (text !== null) {
    div.textContent = text;
  }
  consoleEl.appendChild(div);
  var excess = consoleEl.children.length - 800;
  for (var i = 0; i < excess; i++) {
    consoleEl.removeChild(consoleEl.firstChild);
  }
  if (text !== null) {
    scrollConsoleIfFollowing();
  }
  return div;
}

function scrollConsoleIfFollowing() {
  if (document.getElementById('console-follow').checked) {
    var consoleEl = document.getElementById('console');
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}
