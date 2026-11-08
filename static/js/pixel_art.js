// -- Dibujos de píxeles ----------------------------------------------------------
function hashString(text) {
  var hash = 2166136261;
  for (var i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

// Generador pseudoaleatorio con semilla: el mismo nombre da siempre el mismo dibujo.
function seededRandom(seed) {
  var state = seed || 1;
  return function() {
    state = Math.imul(state ^ (state >>> 15), 1 | state);
    state ^= state + Math.imul(state ^ (state >>> 7), 61 | state);
    return ((state ^ (state >>> 14)) >>> 0) / 4294967296;
  };
}

function pixelSvg(rows, palette, cls) {
  var size = rows.length;
  var rects = '';
  rows.forEach(function(row, y) {
    for (var x = 0; x < row.length; x++) {
      var color = palette[row[x]];
      if (color) {
        rects += '<rect x="' + x + '" y="' + y + '" width="1" height="1" fill="' + color + '"/>';
      }
    }
  });
  return '<svg class="' + cls + '" viewBox="0 0 ' + size + ' ' + size + '" shape-rendering="crispEdges" aria-hidden="true">' + rects + '</svg>';
}

// Bloque de 8x8 con los colores del nombre: el logo de los modpacks que no
// tienen uno propio. Simétrico y con luz arriba a la izquierda, como un
// bloque de verdad.
function packBlockSvg(name) {
  var random = seededRandom(hashString(name || '?'));
  var hue = Math.floor(random() * 360);
  var sat = 35 + Math.floor(random() * 30);
  var shades = [
    'hsl(' + hue + ',' + sat + '%,30%)',
    'hsl(' + hue + ',' + sat + '%,40%)',
    'hsl(' + hue + ',' + sat + '%,50%)',
    'hsl(' + ((hue + 40) % 360) + ',' + (sat + 15) + '%,62%)'
  ];
  // Mitad de arriba al azar y la de abajo girada 180°: queda como una
  // textura de bloque (con simetría de espejo salían caras).
  var cells = [];
  for (var y = 0; y < 4; y++) {
    cells.push([]);
    for (var x = 0; x < 8; x++) {
      var r = random();
      cells[y].push(r < .14 ? '3' : r < .45 ? '2' : r < .8 ? '1' : '0');
    }
  }
  var rows = cells.map(function(row) { return row.join(''); });
  for (var y2 = 3; y2 >= 0; y2--) {
    rows.push(cells[y2].slice().reverse().join(''));
  }
  // Borde: claro arriba e izquierda, oscuro abajo y derecha.
  rows = rows.map(function(row, y) {
    return row.split('').map(function(cell, x) {
      if (y === 0 || x === 0) {
        return 'h';
      }
      if (y === 7 || x === 7) {
        return 'd';
      }
      return cell;
    }).join('');
  });
  return pixelSvg(rows, {
    0: shades[0], 1: shades[1], 2: shades[2], 3: shades[3],
    h: 'hsl(' + hue + ',' + sat + '%,58%)', d: 'hsl(' + hue + ',' + sat + '%,22%)'
  }, 'pixel-fallback');
}

// Cara genérica de 8x8 para un jugador sin cabeza descargada: tono de piel,
// pelo y ojos salen del nombre, así cada uno se distingue de los demás.
var SKIN_TONES = ['#f2c7a5', '#e0a77e', '#c68a5f', '#9c6644', '#6e4630'];
var HAIR_TONES = ['#2b1d14', '#5a3a1e', '#a0662c', '#d8b25a', '#7b3b2b', '#3a3a46'];
var EYE_TONES = ['#3a6fd0', '#4f8a3a', '#6b4a2e', '#5b4aa8'];

function playerFaceSvg(name) {
  var random = seededRandom(hashString((name || '?').toLowerCase()));
  var skin = SKIN_TONES[Math.floor(random() * SKIN_TONES.length)];
  var hair = HAIR_TONES[Math.floor(random() * HAIR_TONES.length)];
  var eye = EYE_TONES[Math.floor(random() * EYE_TONES.length)];
  var fringe = random() < .5;
  var rows = [
    'hhhhhhhh',
    'hhhhhhhh',
    fringe ? 'hssshhhs' : 'hssssssh',
    'ssssssss',
    'swessews',
    'ssssssss',
    'sssmmsss',
    'ssssssss'
  ];
  return pixelSvg(rows, { h: hair, s: skin, w: '#ffffff', e: eye, m: 'rgba(0,0,0,.28)' }, 'pixel-fallback');
}

// Logo del modpack (server-icon.png o el de la tienda) con el bloque generado
// detrás: si la imagen no existe o falla, se queda el bloque.
function packIconHtml(pack, cls) {
  var html = '<span class="pack-icon ' + (cls || '') + '" aria-hidden="true">' + packBlockSvg(pack.name);
  if (pack.has_icon) {
    html += '<img src="/api/modpacks/' + encodeURIComponent(pack.name) + '/icon" alt="" loading="lazy" decoding="async" data-pixel-img>';
  }
  return html + '</span>';
}

// Cabeza del jugador (proxy con caché en /api/players/head) con una cara
// generada detrás por si no se puede descargar.
function headHtml(name, uuid, cls) {
  var html = '<span class="player-head ' + (cls || '') + '" aria-hidden="true">' + playerFaceSvg(name || uuid);
  if (name && /^[A-Za-z0-9_]{1,16}$/.test(name)) {
    html += '<img src="/api/players/head/' + encodeURIComponent(name)
      + (uuid ? '?uuid=' + encodeURIComponent(uuid) : '') + '" alt="" loading="lazy" decoding="async" data-pixel-img>';
  }
  return html + '</span>';
}

// load/error no suben por el DOM, pero se pueden escuchar en captura: así
// vale para todas las imágenes que se pinten con innerHTML.
document.addEventListener('load', function(event) {
  if (event.target.hasAttribute && event.target.hasAttribute('data-pixel-img')) {
    event.target.parentNode.classList.add('img-ready');
  }
}, true);
document.addEventListener('error', function(event) {
  if (event.target.hasAttribute && event.target.hasAttribute('data-pixel-img')) {
    event.target.remove();
  }
}, true);

// -- Estados vacíos ilustrados ---------------------------------------------------
var EMPTY_ART = {
  chest: {
    rows: ['............', '.oooooooooo.', '.owwwwwwwwo.', '.owdwwwwdwo.', '.owwwwwwwwo.', '.ooooggoooo.',
      '.owwwggwwwo.', '.owdwwwwdwo.', '.owwwwwwwwo.', '.owwwwwwwwo.', '.oooooooooo.', '............'],
    palette: { o: '#2b1d12', w: '#9a6a3a', d: '#6e4826', g: '#e8c04a' }
  },
  sign: {
    rows: ['............', '.oooooooooo.', '.owwwwwwwwo.', '.owddddddwo.', '.owwwwwwwwo.', '.owdddddwwo.',
      '.owwwwwwwwo.', '.oooooooooo.', '.....ow.....', '.....ow.....', '.....ow.....', '....oooo....'],
    palette: { o: '#3a2716', w: '#b98a50', d: '#7a5530' }
  },
  sapling: {
    rows: ['............', '.....ll.....', '...llLll....', '..lLlllLl...', '...llsll....', '.....s......',
      '..ll.s......', '..lLls......', '...lls......', '.....s......', '..bbbbbbbb..', '..bdbbbdbb..'],
    palette: { l: '#6fbf4f', L: '#3d7a2c', s: '#7a5530', b: '#6b4a33', d: '#4a3222' }
  },
  map: {
    rows: ['............', '.oooooooooo.', '.opplppppPo.', '.olllpppppo.', '.opllpppPpo.', '.opplprprpo.',
      '.opPppprppo.', '.opllprprpo.', '.olllpppppo.', '.opplppPppo.', '.oooooooooo.', '............'],
    palette: { o: '#5a4a2a', p: '#e8dcb8', P: '#c9b98c', l: '#7fae5a', r: '#d0453d' }
  },
  spyglass: {
    rows: ['............', '..oooo......', '.oGgggo.....', '.oGgggo.....', '.oggggo.....', '.oggggo.....',
      '..oooo......', '......hh....', '.......hh...', '........hh..', '.........hh.', '............'],
    palette: { o: '#2a2a35', g: '#8fd0e8', G: '#d6f2fb', h: '#8a5a30' }
  },
  shield: {
    rows: ['............', '.oooooooooo.', '.oSssssssso.', '.osssggssso.', '.osssggssso.', '.oggggggggo.',
      '.osssggssso.', '..ossggsso..', '..ossggsso..', '...osggso...', '....oooo....', '............'],
    palette: { o: '#2a2f3a', s: '#9aa8bc', S: '#c9d4e2', g: '#6fbf4f' }
  }
};

// emptyArt('chest', 'Título', 'Texto', '<button>…</button>', true) — el
// último parámetro lo hace más pequeño (para listas dentro de tarjetas).
function emptyArt(kind, title, text, actionHtml, compact) {
  var art = EMPTY_ART[kind] || EMPTY_ART.chest;
  return '<div class="empty-art' + (compact ? ' compact' : '') + '">'
    + pixelSvg(art.rows, art.palette, 'empty-art-pic')
    + '<div><div class="empty-art-title">' + escHtml(title) + '</div>'
    + (text ? '<div class="empty-art-text">' + escHtml(text) + '</div>' : '')
    + (actionHtml ? '<div class="empty-art-action">' + actionHtml + '</div>' : '')
    + '</div></div>';
}
