// -- Servidor → Rendimiento: TPS, jugadores y RAM de las últimas 24 h / 7 días -
// Tres gráficas de línea separadas (una medida cada una, cada una con su
// escala). Donde el servidor estuvo apagado la línea se corta. Al pasar el
// ratón (o el dedo) se ve el valor de ese momento.
var PERF_CHARTS = [
  { key: 'tps', title: 'TPS', domain: function() { return [0, 20]; }, ticks: [0, 10, 20],
    format: function(v) { return v.toLocaleString('es-ES', { maximumFractionDigits: 1 }); } },
  { key: 'players', title: 'Jugadores', integer: true,
    domain: function(max) { return [0, Math.max(2, Math.ceil(max))]; },
    format: function(v) { return String(Math.round(v)); } },
  { key: 'ram', title: 'RAM', unit: 'GB',
    domain: function(max) { return [0, Math.max(1, Math.ceil(max / 1024))]; },
    value: function(mb) { return mb / 1024; },
    format: function(v) { return v.toLocaleString('es-ES', { maximumFractionDigits: 1 }) + ' GB'; } }
];
var PERF_HEIGHT = 132;
var PERF_PAD = { top: 10, right: 8, bottom: 22, left: 30 };
var perfHours = 24;
var perfSamples = null;
var perfTimer = null;

function loadHistoryCharts() {
  var select = document.getElementById('perf-modpack');
  var previous = select.value;
  refreshServerPackInfo().then(function(packs) {
    if (!packs.length) {
      document.getElementById('perf-card').hidden = true;
      return;
    }
    document.getElementById('perf-card').hidden = false;
    var names = packs.map(function(pack) { return pack.name; });
    var running = serverRunning ? document.getElementById('console-modpack').textContent : '';
    // Por defecto el que está en marcha; si no, el último que se usó.
    var recent = packs.slice().sort(function(a, b) { return (b.last_played || 0) - (a.last_played || 0); })[0].name;
    select.innerHTML = names.map(function(name) {
      return '<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>';
    }).join('');
    select.value = names.indexOf(previous) !== -1 ? previous : (names.indexOf(running) !== -1 ? running : recent);
    fetchHistory();
  }).catch(function() {});
  clearInterval(perfTimer);
  perfTimer = setInterval(function() {
    if (currentPage === 'server' && !document.hidden && serverRunning) {
      fetchHistory();
    }
  }, 5 * 60 * 1000);
}

function fetchHistory() {
  var modpack = document.getElementById('perf-modpack').value;
  if (!modpack) {
    return;
  }
  apiJson('/api/server/history?modpack=' + encodeURIComponent(modpack) + '&hours=' + perfHours).then(function(result) {
    if (modpack !== document.getElementById('perf-modpack').value) {
      return;
    }
    if (!result.ok) {
      document.getElementById('perf-charts').innerHTML = noticeHtml('error', escHtml(result.data.detail || 'No se pudo leer el historial.'));
      return;
    }
    perfSamples = result.data.samples;
    renderHistoryCharts();
  });
}

function renderHistoryCharts() {
  var holder = document.getElementById('perf-charts');
  if (!perfSamples || !perfSamples.length) {
    holder.innerHTML = emptyArt('spyglass', 'Aún no hay historial',
      'Mientras el servidor está encendido se apunta una muestra por minuto. Vuelve dentro de un rato y verás aquí cómo ha ido.', '', true);
    holder.classList.add('is-empty');
    return;
  }
  holder.classList.remove('is-empty');
  holder.innerHTML = PERF_CHARTS.map(function(chart) {
    return '<figure class="perf-chart" data-key="' + chart.key + '">'
      + '<figcaption><span class="perf-title">' + chart.title + '</span><span class="perf-summary"></span></figcaption>'
      + '<div class="perf-plot"><svg class="perf-svg" role="img"></svg><div class="perf-tip" hidden></div></div>'
      + '</figure>';
  }).join('');
  PERF_CHARTS.forEach(function(chart) {
    drawPerfChart(holder.querySelector('.perf-chart[data-key="' + chart.key + '"]'), chart);
  });
}

function perfTimeLabel(epoch, withDay) {
  var date = new Date(epoch * 1000);
  var time = date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  return withDay ? date.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric' }) + ', ' + time : time;
}

function drawPerfChart(figure, chart) {
  var svg = figure.querySelector('svg');
  var plot = figure.querySelector('.perf-plot');
  var width = Math.max(220, plot.clientWidth);
  var height = PERF_HEIGHT;
  var now = Date.now() / 1000;
  var t0 = now - perfHours * 3600;
  var points = perfSamples.filter(function(s) { return s[chart.key] !== undefined && s[chart.key] !== null; })
    .map(function(s) { return { t: s.t, v: chart.value ? chart.value(s[chart.key]) : s[chart.key] }; });
  var summary = figure.querySelector('.perf-summary');
  if (!points.length) {
    summary.textContent = 'sin datos';
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.innerHTML = '';
    return;
  }
  var max = Math.max.apply(null, points.map(function(p) { return p.v; }));
  var domain = chart.domain(chart.key === 'ram' ? max * 1024 : max);
  var avg = points.reduce(function(sum, p) { return sum + p.v; }, 0) / points.length;
  summary.textContent = chart.key === 'players'
    ? 'máximo ' + chart.format(max)
    : 'media ' + chart.format(avg);

  var innerW = width - PERF_PAD.left - PERF_PAD.right;
  var innerH = height - PERF_PAD.top - PERF_PAD.bottom;
  var x = function(t) { return PERF_PAD.left + (t - t0) / (now - t0) * innerW; };
  var y = function(v) { return PERF_PAD.top + innerH - (v - domain[0]) / (domain[1] - domain[0]) * innerH; };

  var ticks = chart.ticks || [domain[0], Math.round(domain[1] / 2 * 10) / 10, domain[1]];
  if (chart.integer) {
    ticks = ticks.map(Math.round).filter(function(v, i, all) { return all.indexOf(v) === i; });
  }
  var parts = [];
  ticks.forEach(function(tick) {
    var ty = y(tick).toFixed(1);
    parts.push('<line class="perf-grid" x1="' + PERF_PAD.left + '" x2="' + (width - PERF_PAD.right) + '" y1="' + ty + '" y2="' + ty + '"/>');
    parts.push('<text class="perf-axis" x="' + (PERF_PAD.left - 6) + '" y="' + ty + '" dy="0.32em" text-anchor="end">'
      + (chart.key === 'ram' ? tick.toLocaleString('es-ES') : tick) + '</text>');
  });
  // Marcas de tiempo: cada 6 h en 24 h, cada día en 7 días.
  var step = perfHours <= 24 ? 6 * 3600 : 86400;
  var first = Math.ceil(t0 / step) * step;
  if (perfHours > 24) {
    var midnight = new Date(t0 * 1000);
    midnight.setHours(24, 0, 0, 0);
    first = midnight.getTime() / 1000;
  }
  for (var t = first; t < now; t += step) {
    var label = perfHours <= 24 ? perfTimeLabel(t) : new Date(t * 1000).toLocaleDateString('es-ES', { weekday: 'short' });
    parts.push('<text class="perf-axis" x="' + x(t).toFixed(1) + '" y="' + (height - 6) + '" text-anchor="middle">' + escHtml(label) + '</text>');
  }

  // La línea se corta donde faltan muestras (servidor apagado).
  var bucket = Math.max(60, perfHours * 3600 / 360);
  var d = '';
  var segmentLength = 0;
  var lonely = [];
  points.forEach(function(point, index) {
    var gap = index === 0 || point.t - points[index - 1].t > bucket * 2.5;
    if (gap && segmentLength === 1) {
      lonely.push(points[index - 1]);
    }
    d += (gap ? 'M' : 'L') + x(point.t).toFixed(1) + ' ' + y(point.v).toFixed(1);
    segmentLength = gap ? 1 : segmentLength + 1;
  });
  if (segmentLength === 1) {
    lonely.push(points[points.length - 1]);
  }
  parts.push('<path class="perf-line" d="' + d + '"/>');
  // Una muestra suelta no forma línea: se marca con un punto.
  lonely.forEach(function(point) {
    parts.push('<circle class="perf-dot" cx="' + x(point.t).toFixed(1) + '" cy="' + y(point.v).toFixed(1) + '" r="2.5"/>');
  });
  parts.push('<line class="perf-cross" y1="' + PERF_PAD.top + '" y2="' + (PERF_PAD.top + innerH) + '" visibility="hidden"/>');
  parts.push('<circle class="perf-focus" r="4" visibility="hidden"/>');
  parts.push('<rect class="perf-hit" x="' + PERF_PAD.left + '" y="0" width="' + innerW + '" height="' + height + '"/>');

  svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  svg.setAttribute('aria-label', chart.title + ': ' + summary.textContent + ' en ' + (perfHours <= 24 ? 'las últimas 24 horas' : 'los últimos 7 días'));
  svg.innerHTML = parts.join('');

  var cross = svg.querySelector('.perf-cross');
  var focus = svg.querySelector('.perf-focus');
  var tip = figure.querySelector('.perf-tip');
  var hide = function() {
    cross.setAttribute('visibility', 'hidden');
    focus.setAttribute('visibility', 'hidden');
    tip.hidden = true;
  };
  var show = function(event) {
    var rect = svg.getBoundingClientRect();
    var px = (event.clientX - rect.left) * (width / rect.width);
    var nearest = null;
    points.forEach(function(point) {
      var dist = Math.abs(x(point.t) - px);
      if (!nearest || dist < nearest.dist) {
        nearest = { point: point, dist: dist };
      }
    });
    // Lejos de cualquier muestra (en un hueco) no se enseña nada.
    if (!nearest || nearest.dist > Math.max(12, innerW * bucket * 2 / (now - t0))) {
      hide();
      return;
    }
    var cx = x(nearest.point.t);
    var cy = y(nearest.point.v);
    cross.setAttribute('x1', cx);
    cross.setAttribute('x2', cx);
    cross.setAttribute('visibility', 'visible');
    focus.setAttribute('cx', cx);
    focus.setAttribute('cy', cy);
    focus.setAttribute('visibility', 'visible');
    tip.innerHTML = '<strong>' + escHtml(chart.format(nearest.point.v)) + '</strong><span>' + escHtml(perfTimeLabel(nearest.point.t, perfHours > 24)) + '</span>';
    tip.hidden = false;
    var left = cx / width * rect.width;
    tip.style.left = Math.min(Math.max(left, 50), rect.width - 50) + 'px';
  };
  var hit = svg.querySelector('.perf-hit');
  hit.addEventListener('pointermove', show);
  hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', hide);
}

document.getElementById('perf-modpack').addEventListener('change', fetchHistory);
document.querySelectorAll('#perf-card .segmented-btn').forEach(function(button) {
  button.addEventListener('click', function() {
    perfHours = Number(button.dataset.hours);
    document.querySelectorAll('#perf-card .segmented-btn').forEach(function(other) {
      other.classList.toggle('active', other === button);
      other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
    });
    fetchHistory();
  });
});

// Al cambiar el ancho de la ventana se vuelven a dibujar a su tamaño.
var perfResizeTimer = null;
window.addEventListener('resize', function() {
  clearTimeout(perfResizeTimer);
  perfResizeTimer = setTimeout(function() {
    if (perfSamples && perfSamples.length && currentPage === 'server') {
      renderHistoryCharts();
    }
  }, 150);
});
