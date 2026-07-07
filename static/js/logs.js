// -- Logs ---------------------------------------------------------------------
var rawLogContent = '';
var currentLogFile = '';

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
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">' + escHtml(file.name) + '</span>'
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
      var btn = document.createElement('button');
      btn.className = 'log-file-btn crash-btn';
      btn.dataset.file = file.name;
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:.72rem">' + escHtml(file.name) + '</span>'
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
  viewer.innerHTML = '<span style="color:var(--muted)">Cargando...</span>';
  placeholder.style.display = 'none';
  viewer.style.display = 'block';
  culpritBox.style.display = 'none';
  document.getElementById('log-match-count').textContent = '';

  apiFetch('/api/modpacks/' + encodeURIComponent(currentModpack) + '/logs/' + encodeURIComponent(filename))
    .then(function(response) { return response.json(); })
    .then(function(data) {
      rawLogContent = data.content;
      renderLog();
      // analyze_crash() (services/modpack.py) devuelve una lista plana de
      // strings ("Posible culpable: X"), no un objeto {mods, caused_by} —
      // antes se leía como si lo fuera, lo que lanzaba un TypeError acá
      // (culprits.mods es undefined en un array) y el catch de abajo pisaba
      // el log ya renderizado con "Error al cargar archivo".
      var culprits = data.culprits;
      if (culprits && culprits.length) {
        culpritBox.style.display = 'block';
        document.getElementById('crash-culprit-mods').innerHTML = culprits
          .map(function(line) {
            return '<code style="display:inline-block;margin:2px 4px 2px 0;background:rgba(248,81,73,.15);color:var(--red);padding:1px 6px;border-radius:4px">'
              + escHtml(line) + '</code>';
          })
          .join('');
        document.getElementById('crash-caused-by').innerHTML = '';
      }
    })
    .catch(function() {
      viewer.innerHTML = '<span style="color:var(--red)">Error al cargar archivo</span>';
    });
}

function renderLog() {
  var viewer = document.getElementById('log-viewer');
  var search = document.getElementById('log-search').value.toLowerCase();
  var filter = document.getElementById('log-filter').value;
  var lines = rawLogContent.split('\n');
  var html = '';
  var shownCount = 0;
  lines.forEach(function(line) {
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
    shownCount++;
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
    var escaped = escHtml(line);
    if (search) {
      var re = new RegExp('(' + escRegex(search) + ')', 'gi');
      escaped = escaped.replace(re, '<mark style="background:rgba(210,153,34,.4);color:var(--text)">$1</mark>');
    }
    html += '<div class="' + cls + '">' + escaped + '</div>';
  });
  viewer.innerHTML = html || '<span style="color:var(--muted)">Sin resultados</span>';
  document.getElementById('log-match-count').textContent = shownCount + ' / ' + lines.length + ' líneas';
  if (search) {
    var firstMark = viewer.querySelector('mark');
    if (firstMark) {
      firstMark.scrollIntoView({ block: 'center' });
    }
  } else {
    if (currentLogFile.indexOf('crash') !== -1) {
      viewer.scrollTop = 0;
    } else {
      viewer.scrollTop = viewer.scrollHeight;
    }
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
