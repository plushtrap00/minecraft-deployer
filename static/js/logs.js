// -- Logs ---------------------------------------------------------------------
var rawLogContent = '';
var currentLogFile = '';

// Tamaño de página del visor (líneas), mismo criterio que MOD_MODAL_PAGE_SIZE/
// PAGE_SIZE en el resto de la app: constante de renderizado del cliente, no
// un ajuste de servidor — un log rotado puede tener varios miles de líneas y
// meterlas todas en el DOM de una vez arriesga colgar la pestaña.
var LOG_PAGE_SIZE = 500;
var logViewState = { lines: [], totalLines: 0, page: 0 };

function loadLogList() {
  if (!currentModpack) {
    return;
  }
  document.getElementById('log-file-list').innerHTML = '<p class="empty-msg">Cargando...</p>';
  document.getElementById('crash-file-list').innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/logs')
    .then(function(response) { return response.json(); })
    .then(function(data) { renderLogFileList(data.logs, data.crashes); })
    .catch(function() {
      document.getElementById('log-file-list').innerHTML =
        '<p class="empty-msg" style="color:var(--red)">Error</p>';
    });
}

// "latest.log"/"debug.log" (sesión actual) y "debug-N.log.gz" (rotados) no
// dicen nada por sí solos en la lista — una etiqueta legible, con el nombre
// real igual disponible como tooltip (title) para quien lo necesite tal cual.
function logDisplayLabel(name) {
  if (name === 'latest.log') {
    return 'Log actual';
  }
  if (name === 'debug.log') {
    return 'Debug actual';
  }
  var m = /^debug-(\d+)\.log\.gz$/.exec(name);
  if (m) {
    return 'Debug rotado ' + m[1];
  }
  return name;
}

// timestamp llega como "2026-07-05T18:52:29" (ver _parse_crash_timestamp en
// routes/modpacks.py) — sin sufijo de zona, así que el motor JS lo trata como
// hora local, razonable dado que tanto el servidor como quien lo lee suelen
// estar en la misma zona en un setup de home server.
function formatCrashTimestamp(ts) {
  if (!ts) {
    return null;
  }
  var d = new Date(ts);
  if (isNaN(d.getTime())) {
    return null;
  }
  var pad = function(n) { return String(n).padStart(2, '0'); };
  return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear()
    + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function renderLogFileList(logs, crashes) {
  var logList = document.getElementById('log-file-list');
  var crashList = document.getElementById('crash-file-list');
  if (!logs || !logs.length) {
    logList.innerHTML = '<p class="empty-msg">Sin logs</p>';
  } else {
    logList.innerHTML = '';
    logs.forEach(function(file) {
      var btn = document.createElement('button');
      btn.className = 'log-file-btn';
      btn.dataset.file = file.name;
      btn.title = file.name;
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">' + escHtml(logDisplayLabel(file.name)) + '</span>'
        + '<span style="color:var(--muted);flex-shrink:0;font-size:.72rem">' + file.size_kb + ' KB</span>';
      btn.addEventListener('click', function() { loadLogFile(file.name); });
      logList.appendChild(btn);
    });
  }
  if (!crashes || !crashes.length) {
    crashList.innerHTML = '<p class="empty-msg">Sin crashes 🎉</p>';
  } else {
    crashList.innerHTML = '';
    crashes.forEach(function(file) {
      var label = formatCrashTimestamp(file.timestamp) || file.name;
      var btn = document.createElement('button');
      btn.className = 'log-file-btn crash-btn';
      btn.dataset.file = file.name;
      btn.title = file.name;
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:.72rem">' + escHtml(label) + '</span>'
        + '<span style="color:var(--muted);flex-shrink:0;font-size:.72rem">' + file.size_kb + ' KB</span>';
      btn.addEventListener('click', function() { loadLogFile(file.name); });
      crashList.appendChild(btn);
    });
  }
}

function loadLogFile(filename) {
  currentLogFile = filename;
  document.querySelectorAll('.log-file-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.file === filename);
  });
  var viewer = document.getElementById('log-viewer');
  var placeholder = document.getElementById('log-placeholder');
  var culpritBox = document.getElementById('crash-culprit');
  var downloadLink = document.getElementById('log-download-link');
  viewer.innerHTML = '<span style="color:var(--muted)">Cargando...</span>';
  placeholder.style.display = 'none';
  viewer.style.display = 'block';
  culpritBox.style.display = 'none';
  document.getElementById('log-match-count').textContent = '';
  downloadLink.style.display = 'none';

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/logs/' + encodeURIComponent(filename))
    .then(function(response) { return response.json(); })
    .then(function(data) {
      rawLogContent = data.content;
      renderLog(true);

      downloadLink.href = '/api/modpacks/' + encodeURIComponent(currentModpack) + '/logs/' + encodeURIComponent(filename)
        + '/download?token=' + encodeURIComponent(authToken);
      downloadLink.style.display = '';

      renderCrashInfo(data.crash_info);
    })
    .catch(function() {
      viewer.innerHTML = '<span style="color:var(--red)">Error al cargar archivo</span>';
    });
}

// crash_info (services/modpack.py::analyze_crash) solo viene poblado para
// archivos de crash-reports/ — para un log normal llega null y la caja
// simplemente no se muestra, en vez del "posible culpable" a ciegas de antes.
function renderCrashInfo(crashInfo) {
  var culpritBox = document.getElementById('crash-culprit');
  if (!crashInfo || (!crashInfo.exception_summary && !crashInfo.culprit_mods.length && !crashInfo.caused_by_chain.length)) {
    culpritBox.style.display = 'none';
    return;
  }
  culpritBox.style.display = 'block';

  var summaryEl = document.getElementById('crash-exception-summary');
  summaryEl.textContent = crashInfo.exception_summary || '';
  summaryEl.style.display = crashInfo.exception_summary ? '' : 'none';

  var modsEl = document.getElementById('crash-culprit-mods');
  if (crashInfo.culprit_mods.length) {
    modsEl.innerHTML = crashInfo.culprit_mods.map(function(name) {
      return '<code style="display:inline-block;margin:2px 4px 2px 0;background:rgba(248,81,73,.15);color:var(--red);padding:1px 6px;border-radius:4px">'
        + escHtml(name) + '</code>';
    }).join('');
  } else {
    modsEl.innerHTML = '<span style="color:var(--muted)">No se pudo identificar un mod concreto</span>';
  }

  var causedByDetails = document.getElementById('crash-caused-by-details');
  if (crashInfo.caused_by_chain.length) {
    document.getElementById('crash-caused-by').innerHTML = crashInfo.caused_by_chain
      .map(function(line) { return '<div>' + escHtml(line) + '</div>'; })
      .join('');
    causedByDetails.style.display = '';
  } else {
    causedByDetails.style.display = 'none';
  }
}

// initialLoad=true (justo tras abrir un archivo): aterriza en la última
// página para logs normales (mismo criterio de "ir al final" que ya había) o
// en la primera para crash reports (mismo criterio de "ir al principio").
// En cualquier otra llamada (búsqueda/filtro cambiados) se vuelve a la
// primera página del resultado nuevo — seguir en una página vieja que puede
// ni tener resultados sería más confuso que reiniciar.
function renderLog(initialLoad) {
  var search = document.getElementById('log-search').value.toLowerCase();
  var filter = document.getElementById('log-filter').value;
  var lines = rawLogContent.split('\n');
  var filtered = [];
  lines.forEach(function(line, idx) {
    var lineLower = line.toLowerCase();
    var show = true;
    if (filter === 'error') {
      show = lineLower.indexOf('error') !== -1 || lineLower.indexOf('fatal') !== -1;
    } else if (filter === 'warn') {
      show = lineLower.indexOf('warn') !== -1;
    } else if (filter === 'errors-warns') {
      show = lineLower.indexOf('error') !== -1 || lineLower.indexOf('fatal') !== -1 || lineLower.indexOf('warn') !== -1;
    } else if (filter === 'info') {
      show = lineLower.indexOf('[info]') !== -1 || lineLower.indexOf('/info]') !== -1;
    }
    if (!show) {
      return;
    }
    if (search && lineLower.indexOf(search) === -1) {
      return;
    }
    filtered.push({ num: idx + 1, text: line });
  });

  logViewState.lines = filtered;
  logViewState.totalLines = lines.length;
  var totalPages = Math.max(1, Math.ceil(filtered.length / LOG_PAGE_SIZE));
  if (initialLoad) {
    logViewState.page = currentLogFile.indexOf('crash') !== -1 ? 0 : totalPages - 1;
  } else {
    logViewState.page = 0;
  }
  renderLogPage();
}

function renderLogPage() {
  var viewer = document.getElementById('log-viewer');
  var search = document.getElementById('log-search').value.toLowerCase();
  var filtered = logViewState.lines;
  var totalPages = Math.max(1, Math.ceil(filtered.length / LOG_PAGE_SIZE));
  var start = logViewState.page * LOG_PAGE_SIZE;
  var pageItems = filtered.slice(start, start + LOG_PAGE_SIZE);

  var html = '';
  pageItems.forEach(function(item) {
    var lineLower = item.text.toLowerCase();
    var cls = '';
    if (lineLower.indexOf('fatal') !== -1) {
      cls = 'log-line-fatal';
    } else if (lineLower.indexOf('error') !== -1) {
      cls = 'log-line-error';
    } else if (lineLower.indexOf('warn') !== -1) {
      cls = 'log-line-warn';
    } else if (lineLower.indexOf('[info]') !== -1 || lineLower.indexOf('/info]') !== -1) {
      cls = 'log-line-info';
    }
    var escaped = escHtml(item.text);
    if (search) {
      var re = new RegExp('(' + escRegex(search) + ')', 'gi');
      escaped = escaped.replace(re, '<mark style="background:rgba(210,153,34,.4);color:var(--text)">$1</mark>');
    }
    html += '<div class="log-line ' + cls + '"><span class="log-line-num">' + item.num + '</span><span class="log-line-text">' + escaped + '</span></div>';
  });
  viewer.innerHTML = html || '<span style="color:var(--muted)">Sin resultados</span>';
  document.getElementById('log-match-count').textContent = filtered.length + ' / ' + logViewState.totalLines + ' líneas';

  renderModModalPagination('log-pagination', logViewState.page, totalPages, function(p) {
    logViewState.page = p;
    renderLogPage();
  });

  if (search) {
    var firstMark = viewer.querySelector('mark');
    if (firstMark) {
      firstMark.scrollIntoView({ block: 'center' });
    }
  } else if (currentLogFile.indexOf('crash') !== -1) {
    viewer.scrollTop = 0;
  } else {
    viewer.scrollTop = viewer.scrollHeight;
  }
}

var _logSearchTimer = null;
document.getElementById('log-search').addEventListener('input', function() {
  clearTimeout(_logSearchTimer);
  _logSearchTimer = setTimeout(function() {
    if (rawLogContent) {
      renderLog();
    }
  }, 200);
});

document.getElementById('log-filter').addEventListener('change', function() {
  if (rawLogContent) {
    renderLog();
  }
});
