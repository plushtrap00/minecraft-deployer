// -- Iconos de los logros -------------------------------------------------------
// Uno pixelado de 10x10 por logro (ACHIEVEMENTS en appearance.js), dibujado
// con pixelSvg: cada letra de las filas es un color de su paleta y el punto
// es transparente. Bloqueado se ve en grises, también en los
// secretos: el nombre sale como «???» pero la silueta sirve de pista.

var ACHIEVEMENT_ICONS = {
  // Cofre
  'first-install': {
    rows: [
      '..........',
      '.oooooooo.',
      '.wWWWWWWw.',
      '.wWWWWWWw.',
      '.oooGGooo.',
      '.wWWGGWWw.',
      '.wWWWWWWw.',
      '.wWWWWWWw.',
      '.oooooooo.',
      '..........'
    ],
    palette: { o: '#4a2f17', w: '#8a5a2b', W: '#c08a4a', G: '#d8d8d8' }
  },
  // Antorcha encendida
  'first-start': {
    rows: [
      '....yy....',
      '...yFFy...',
      '...yFFy...',
      '....bB....',
      '....bB....',
      '....bB....',
      '....bB....',
      '....bB....',
      '....bB....',
      '..........'
    ],
    palette: { y: '#ff9a2a', F: '#ffe27a', b: '#a0713c', B: '#6b4a24' }
  },
  // Corona
  'first-op': {
    rows: [
      '..........',
      '..........',
      '.y..yy..y.',
      '.yy.yy.yy.',
      '.yyyyyyyy.',
      '.yyRyyByy.',
      '.yyyyyyyy.',
      '.dddddddd.',
      '..........',
      '..........'
    ],
    palette: { y: '#f2c14a', d: '#b8862a', R: '#e0473c', B: '#5fb8e8' }
  },
  // Casa con las luces encendidas
  'full-house': {
    rows: [
      '....rr....',
      '...rrrr...',
      '..rrrrrr..',
      '.rrrrrrrr.',
      'rrrrrrrrrr',
      '.wwwwwwww.',
      '.wyywwyyw.',
      '.wyywwddw.',
      '.wwwwwddw.',
      '.wwwwwddw.'
    ],
    palette: { r: '#b5482f', w: '#d9c39a', y: '#ffd76a', d: '#6b4a33' }
  },
  // Reloj
  'smooth': {
    rows: [
      '...gggg...',
      '..gYYYYg..',
      '.gYYkYYYg.',
      '.gYYkYYYg.',
      '.gYYkkkYg.',
      '.gYYYYYYg.',
      '.gYYYYYYg.',
      '..gYYYYg..',
      '...gggg...',
      '..........'
    ],
    palette: { g: '#b8862a', Y: '#f6e7b0', k: '#3a2a1a' }
  },
  // Luna y estrellas
  'night-shift': {
    rows: [
      '..........',
      '....mmm.s.',
      '..mmm.....',
      '..mm......',
      '.mmk...s..',
      '.mmk......',
      '.mmmk.....',
      '..mmmmk...',
      '...mmmm...',
      '..........'
    ],
    palette: { m: '#e9e6f5', k: '#a9a3c7', s: '#fff4b0' }
  },
  // Sol saliendo sobre la hierba
  'early-bird': {
    rows: [
      '..........',
      '....yy....',
      '.y..yy..y.',
      '..y....y..',
      '...oooo...',
      '..oooooo..',
      'y.oooooo.y',
      'gggggggggg',
      'gGgGgGgGgG',
      '..........'
    ],
    palette: { y: '#ffd76a', o: '#ffb347', g: '#5aa043', G: '#3f7a2d' }
  },
  // Librería
  'collector': {
    rows: [
      'wwwwwwwwww',
      'wrbgyrbgyw',
      'wrbgyrbgyw',
      'wrbgyrbgyw',
      'wwwwwwwwww',
      'wgyrbgyrbw',
      'wgyrbgyrbw',
      'wgyrbgyrbw',
      'wwwwwwwwww',
      '..........'
    ],
    palette: { w: '#a0713c', r: '#b5482f', b: '#4f6fbf', g: '#5aa043', y: '#d8b25a' }
  },
  // Pico de hierro
  'handyman': {
    rows: [
      '...cccc...',
      '.ccCCCCcc.',
      'c...ss...c',
      '....ss....',
      '....ss....',
      '....ss....',
      '....ss....',
      '....ss....',
      '....ss....',
      '..........'
    ],
    palette: { c: '#9aa4ad', C: '#e6ebef', s: '#8a5a2b' }
  },
  // Escoba
  'tidy': {
    rows: [
      '.........s',
      '........s.',
      '.......s..',
      '......s...',
      '.....s....',
      '...yys....',
      '..yyyyy...',
      '.yyyyyy...',
      'yYyYyY....',
      '..........'
    ],
    palette: { s: '#8a5a2b', y: '#d8b25a', Y: '#a8822e' }
  },
  // Mapa
  'new-world': {
    rows: [
      'pppppppppp',
      'pBBBggBBBp',
      'pBggggBBBp',
      'pBBgggBggp',
      'pBBBgBBggp',
      'pggBBBBBgp',
      'pgggBBBBBp',
      'pBggBBrBBp',
      'pppppppppp',
      '..........'
    ],
    palette: { p: '#e8d9a8', B: '#4f86c6', g: '#5aa043', r: '#e0473c' }
  },
  // Disquete
  'backup': {
    rows: [
      'dddddddd..',
      'dwwwwkwdd.',
      'dwwwwkwddd',
      'dddddddddd',
      'dddddddddd',
      'dlllllllld',
      'dlllllllld',
      'dlllllllld',
      'dddddddddd',
      '..........'
    ],
    palette: { d: '#4f6fbf', w: '#d0d6e0', k: '#3a4a7a', l: '#e8ecf2' }
  },
  // Campana
  'herald': {
    rows: [
      '....bb....',
      '...yyyy...',
      '..yYyyyy..',
      '..yYyyyy..',
      '..yYyyyy..',
      '.yyyyyyyy.',
      '.dddddddd.',
      '....kk....',
      '..........',
      '..........'
    ],
    palette: { y: '#f2c14a', Y: '#fff1b0', d: '#b8862a', b: '#6b4a33', k: '#6b4a33' }
  },
  // Cuatro jugadores apretados
  'sold-out': {
    rows: [
      'hhhh.HHHH.',
      'hhhh.HHHH.',
      'esse.esse.',
      'ssss.ssss.',
      '..........',
      '.HHHH.hhhh',
      '.HHHH.hhhh',
      '.esse.esse',
      '.ssss.ssss',
      '..........'
    ],
    palette: { h: '#5a3a1e', H: '#d8b25a', s: '#e0a77e', e: '#3a6fd0' }
  },
  // Reloj de arena
  'marathon': {
    rows: [
      '.wwwwwwww.',
      '..gyyyyg..',
      '..gyyyyg..',
      '...gyyg...',
      '....yy....',
      '...g..g...',
      '..g.yy.g..',
      '..gyyyyg..',
      '.wwwwwwww.',
      '..........'
    ],
    palette: { w: '#8a5a2b', g: '#bfe3f0', y: '#e8c26a' }
  },
  // Portal
  'tourist': {
    rows: [
      '.oooooooo.',
      '.oppPpppo.',
      '.opPpppPo.',
      '.oppppPpo.',
      '.oPpppppo.',
      '.opppPppo.',
      '.oppPpppo.',
      '.opPpppPo.',
      '.oooooooo.',
      '..........'
    ],
    palette: { o: '#2a1f3d', p: '#7a3fd0', P: '#c08aff' }
  },
  // Brújula
  'explorer': {
    rows: [
      '...gggg...',
      '..gwwwwg..',
      '.gwwwwrwg.',
      '.gwwwrrwg.',
      '.gwwkrwwg.',
      '.gwkkwwwg.',
      '.gwkwwwwg.',
      '..gwwwwg..',
      '...gggg...',
      '..........'
    ],
    palette: { g: '#8a8f99', w: '#d9d6cc', r: '#e0473c', k: '#3a3a46' }
  },
  // Espada de hierro
  'iron-fist': {
    rows: [
      '........cc',
      '.......cwc',
      '......cwc.',
      '.....cwc..',
      '.b..cwc...',
      '..bcwc....',
      '...bc.....',
      '..sbb.....',
      '.ss..b....',
      'ss........'
    ],
    palette: { c: '#9aa4ad', w: '#e6ebef', b: '#4a3a2a', s: '#8a5a2b' }
  },
  // Corazón
  'mercy': {
    rows: [
      '..........',
      '.rrr..rrr.',
      'rWrrrrrrrr',
      'rWrrrrrrrr',
      'rrrrrrrrrd',
      '.rrrrrrrd.',
      '..rrrrrd..',
      '...rrrd...',
      '....rd....',
      '..........'
    ],
    palette: { r: '#e0473c', W: '#ff9a8a', d: '#a82e24' }
  },
  // Mando
  'konami': {
    rows: [
      '..........',
      '..........',
      '.gggggggg.',
      'gggggggrgg',
      'gwggggrgrg',
      'wwwggggrgg',
      'gwgggggggg',
      'gggg..gggg',
      '.gg....gg.',
      '..........'
    ],
    palette: { g: '#4a4458', w: '#d9d6cc', r: '#e0473c' }
  },
  // Cara con los ojos en blanco
  'herobrine': {
    rows: [
      'hhhhhhhhhh',
      'hhhhhhhhhh',
      'hhsssssshh',
      'ssssssssss',
      'swwsssswws',
      'ssssssssss',
      'sssnnnnsss',
      'ssnmmmmnss',
      'ssnnnnnnss',
      'ssssssssss'
    ],
    palette: { h: '#3b2412', s: '#b98a62', w: '#ffffff', n: '#5a3a20', m: '#7a4a3a' }
  },
  // Bloque barrera
  'hard-stop': {
    rows: [
      '..rrrrrr..',
      '.rr....rr.',
      'rr....rrrr',
      'r....rrr.r',
      'r...rrr..r',
      'r..rrr...r',
      'r.rrr....r',
      'rrrr....rr',
      '.rr....rr.',
      '..rrrrrr..'
    ],
    palette: { r: '#e0473c' }
  },
  // Nube con lluvia
  'weatherman': {
    rows: [
      '..........',
      '...wwww...',
      '..wwwwwww.',
      '.wwwwwwwww',
      'wwwwwwwwww',
      '.gggggggg.',
      '..b..b..b.',
      '.b..b..b..',
      '..b..b..b.',
      '..........'
    ],
    palette: { w: '#e6ebef', g: '#aeb6c0', b: '#5fa8e8' }
  },
  // Espiral
  'dizzy': {
    rows: [
      '.pppppppp.',
      'p........p',
      'p.pppppp.p',
      'p.p....p.p',
      'p.p.pp.p.p',
      'p.p.p..p.p',
      'p.p.pppp.p',
      'p.p......p',
      'p.pppppppp',
      '..........'
    ],
    palette: { p: '#e78bd9' }
  },
  // Destello
  'touch-sky': {
    rows: [
      '....y.....',
      '....y.....',
      '...yWy....',
      'yyyWWWyyy.',
      '...yWy....',
      '....y.....',
      '....y...y.',
      '.......yWy',
      '........y.',
      '..........'
    ],
    palette: { y: '#ffd76a', W: '#fff8d0' }
  },
  // TNT
  'tnt': {
    rows: [
      'rrrrrrrrrr',
      'rdrrdrrdrr',
      'rrrrrrrrrr',
      'wwwwwwwwww',
      'kkkwkkwkkk',
      'wkwwkkwwkw',
      'wkwwkkwwkw',
      'wwwwwwwwww',
      'rrrrrrrrrr',
      'rdrrdrrdrr'
    ],
    palette: { r: '#d23a2a', d: '#9a2420', w: '#efe9e0', k: '#222222' }
  },
  // Diamante
  'platinum': {
    rows: [
      '..........',
      '..cccccc..',
      '.cwwccccc.',
      'cwccccccdc',
      '.cccccccd.',
      '..ccccdd..',
      '...ccdd...',
      '....cd....',
      '..........',
      '..........'
    ],
    palette: { c: '#5fe0e0', w: '#e8ffff', d: '#2a9a9a' }
  }
};

// Gris con la misma luminosidad que el color: así la silueta conserva el
// dibujo de dentro (las letras de la TNT, los ojos de la cara...).
function achievementGrey(hex) {
  var value = parseInt(hex.slice(1), 16);
  var luma = (.299 * (value >> 16) + .587 * ((value >> 8) & 255) + .114 * (value & 255)) / 255;
  return 'hsl(250, 6%, ' + Math.round(28 + luma * 50) + '%)';
}

// Icono de un logro. Bloqueado: la misma figura en grises.
function achievementIconHtml(item, unlocked) {
  var art = ACHIEVEMENT_ICONS[item.id];
  if (!art) {
    return icon(unlocked ? 'trophy' : 'lock');
  }
  var palette = art.palette;
  if (!unlocked) {
    palette = {};
    Object.keys(art.palette).forEach(function(key) { palette[key] = achievementGrey(art.palette[key]); });
  }
  return pixelSvg(art.rows, palette, 'achievement-art');
}
