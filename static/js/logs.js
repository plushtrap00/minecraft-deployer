// -- Logs --------------------------------------------------------------------
var rawLogContent = '';
var currentLogFile = '';

function loadLogList() {
  if (!currentModpack) return;
  document.getElementById('log-file-list').innerHTML = '<p class="empty-msg">Cargando...</p>';
  document.getElementById('crash-file-list').innerHTML = '<p class="empty-msg">Cargando...</p>';
  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/logs')
    .then(function(r){ return r.json(); })
    .then(function(d){ renderLogFileList(d.logs, d.crashes); })
    .catch(function(){
      document.getElementById('log-file-list').innerHTML = '<p class="empty-msg" style="color:var(--red)">Error</p>';
    });
}

function renderLogFileList(logs, crashes) {
  var logList = document.getElementById('log-file-list');
  var crashList = document.getElementById('crash-file-list');
  if (!logs || !logs.length) {
    logList.innerHTML = '<p class="empty-msg">Sin logs</p>';
  } else {
    logList.innerHTML = '';
    logs.forEach(function(f) {
      var btn = document.createElement('button');
      btn.className = 'log-file-btn';
      btn.dataset.file = f.name;
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">'+escHtml(f.name)+'</span>'
        + '<span style="color:var(--muted);flex-shrink:0;font-size:.72rem">'+f.size_kb+' KB</span>';
      btn.addEventListener('click', function(){ loadLogFile(f.name); });
      logList.appendChild(btn);
    });
  }
  if (!crashes || !crashes.length) {
    crashList.innerHTML = '<p class="empty-msg">Sin crashes 🎉</p>';
  } else {
    crashList.innerHTML = '';
    crashes.forEach(function(f) {
      var btn = document.createElement('button');
      btn.className = 'log-file-btn crash-btn';
      btn.dataset.file = f.name;
      btn.innerHTML = '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-size:.72rem">'+escHtml(f.name)+'</span>'
        + '<span style="color:var(--muted);flex-shrink:0;font-size:.72rem">'+f.size_kb+' KB</span>';
      btn.addEventListener('click', function(){ loadLogFile(f.name); });
      crashList.appendChild(btn);
    });
  }
}

function loadLogFile(filename) {
  currentLogFile = filename;
  document.querySelectorAll('.log-file-btn').forEach(function(b){
    b.classList.toggle('active', b.dataset.file === filename);
  });
  var viewer = document.getElementById('log-viewer');
  var placeholder = document.getElementById('log-placeholder');
  var culpritBox = document.getElementById('crash-culprit');
  viewer.innerHTML = '<span style="color:var(--muted)">Cargando...</span>';
  placeholder.style.display = 'none';
  viewer.style.display = 'block';
  culpritBox.style.display = 'none';
  document.getElementById('log-match-count').textContent = '';

  apiFetch('/api/modpacks/'+encodeURIComponent(currentModpack)+'/logs/'+encodeURIComponent(filename))
    .then(function(r){ return r.json(); })
    .then(function(d){
      rawLogContent = d.content;
      renderLog();
      var c = d.culprits;
      if (c && (c.mods.length || c.caused_by.length)) {
        culpritBox.style.display = 'block';
        var modsHtml = c.mods.length
          ? c.mods.map(function(m){ return '<code style="display:inline-block;margin:2px 4px 2px 0;background:rgba(248,81,73,.15);color:var(--red);padding:1px 6px;border-radius:4px">'+escHtml(m)+'</code>'; }).join('')
          : '<span style="color:var(--muted)">No se pudo identificar un mod concreto</span>';
        document.getElementById('crash-culprit-mods').innerHTML = modsHtml;
        document.getElementById('crash-caused-by').innerHTML = c.caused_by
          .map(function(l){ return '<div>'+escHtml(l)+'</div>'; }).join('');
      }
    })
    .catch(function(){ viewer.innerHTML = '<span style="color:var(--red)">Error al cargar archivo</span>'; });
}

function renderLog() {
  var viewer = document.getElementById('log-viewer');
  var search = document.getElementById('log-search').value.toLowerCase();
  var filter = document.getElementById('log-filter').value;
  var lines = rawLogContent.split('\n');
  var html = '';
  var shown = 0;
  lines.forEach(function(line) {
    var low = line.toLowerCase();
    var show = true;
    if (filter === 'error') show = low.indexOf('error') !== -1 || low.indexOf('fatal') !== -1;
    else if (filter === 'warn') show = low.indexOf('warn') !== -1;
    else if (filter === 'errors-warns') show = low.indexOf('error') !== -1 || low.indexOf('fatal') !== -1 || low.indexOf('warn') !== -1;
    else if (filter === 'info') show = low.indexOf('[info]') !== -1 || low.indexOf('/info]') !== -1;
    if (!show) return;
    if (search && low.indexOf(search) === -1) return;
    shown++;
    var cls = '';
    if (low.indexOf('fatal') !== -1) cls = 'log-line-fatal';
    else if (low.indexOf('error') !== -1) cls = 'log-line-error';
    else if (low.indexOf('warn') !== -1) cls = 'log-line-warn';
    else if (low.indexOf('[info]') !== -1 || low.indexOf('/info]') !== -1) cls = 'log-line-info';
    var escaped = escHtml(line);
    if (search) {
      var re = new RegExp('('+escRegex(search)+')', 'gi');
      escaped = escaped.replace(re, '<mark style="background:rgba(210,153,34,.4);color:var(--text)">$1</mark>');
    }
    html += '<div class="'+cls+'">'+escaped+'</div>';
  });
  viewer.innerHTML = html || '<span style="color:var(--muted)">Sin resultados</span>';
  document.getElementById('log-match-count').textContent = shown+' / '+lines.length+' líneas';
  if (search) {
    var firstMark = viewer.querySelector('mark');
    if (firstMark) firstMark.scrollIntoView({block:'center'});
  } else {
    viewer.scrollTop = currentLogFile.indexOf('crash') !== -1 ? 0 : viewer.scrollHeight;
  }
}

document.getElementById('log-search').addEventListener('input', function(){ if(rawLogContent) renderLog(); });
document.getElementById('log-filter').addEventListener('change', function(){ if(rawLogContent) renderLog(); });
