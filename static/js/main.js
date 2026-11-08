// -- Navegación y dirección de la página --------------------------------------
// La sección que se ve queda en la URL (#servidor, #modpacks/ATM9/mods,
// #instalar/crear...): al recargar se vuelve al mismo sitio y los botones
// Atrás/Adelante del navegador funcionan. Toda la navegación pasa por
// navigate(), que antes de cambiar comprueba si hay una operación de mods en
// curso o cambios sin guardar (confirmLeave, en utils.js).
var PAGE_SLUGS = {
  server: 'servidor', players: 'jugadores', manage: 'modpacks', deploy: 'instalar',
  help: 'ayuda', users: 'usuarios', config: 'configuracion', automation: 'automatizacion'
};
var MGMT_TAB_SLUGS = {
  props: 'propiedades', ram: 'ram', configs: 'config-mods', kubejs: 'kubejs',
  worldfiles: 'archivos-mundo', logs: 'logs', mods: 'mods', backups: 'copias'
};
var DEPLOY_MODE_SLUGS = {
  'deploy-mode-import': 'subir', 'deploy-mode-create': 'crear', 'deploy-mode-download': 'descargar'
};
var ADMIN_PAGES = ['users', 'config'];

var currentPage = 'server';
var appliedHash = null;

function keyForSlug(map, slug) {
  return Object.keys(map).filter(function(key) { return map[key] === slug; })[0] || null;
}

function safeDecode(text) {
  try {
    return decodeURIComponent(text);
  } catch (e) {
    return text;
  }
}

function parseRoute(hash) {
  var parts = (hash || '').replace(/^#\/?/, '').split('/').map(safeDecode);
  var page = keyForSlug(PAGE_SLUGS, parts[0]) || 'server';
  if (ADMIN_PAGES.indexOf(page) !== -1 && currentRole !== 'admin') {
    page = 'server';
  }
  var route = { page: page };
  if (page === 'manage' && parts[1]) {
    route.modpack = parts[1];
    route.tab = keyForSlug(MGMT_TAB_SLUGS, parts[2]) || 'props';
  }
  if (page === 'deploy') {
    route.mode = keyForSlug(DEPLOY_MODE_SLUGS, parts[1]);
  }
  return route;
}

function buildHash(route) {
  var hash = '#' + PAGE_SLUGS[route.page];
  if (route.page === 'manage' && route.modpack) {
    hash += '/' + encodeURIComponent(route.modpack) + '/' + MGMT_TAB_SLUGS[route.tab || 'props'];
  }
  if (route.page === 'deploy' && route.mode) {
    hash += '/' + DEPLOY_MODE_SLUGS[route.mode];
  }
  return hash;
}

function activeMgmtTab() {
  var tab = document.querySelector('#mgmt-panel-tabs .mgmt-tab.active');
  return tab ? tab.id.replace('mtab-', '') : 'props';
}

function activeDeployMode() {
  var tab = document.querySelector('.deploy-modes .mgmt-tab.active');
  return tab ? tab.id : null;
}

function mgmtPanelOpen() {
  return document.getElementById('mgmt-panel').classList.contains('show');
}

// Ruta de lo que se ve ahora mismo.
function currentRoute() {
  var route = { page: currentPage };
  if (currentPage === 'manage' && currentModpack && mgmtPanelOpen()) {
    route.modpack = currentModpack;
    route.tab = activeMgmtTab();
  }
  if (currentPage === 'deploy') {
    route.mode = activeDeployMode();
  }
  return route;
}

// Deja la URL como está la página sin crear una entrada en el historial
// (p.ej. tras borrar el modpack que se estaba gestionando).
function replaceRoute(route) {
  appliedHash = buildHash(route || currentRoute());
  if (location.hash !== appliedHash) {
    history.replaceState(null, '', appliedHash);
  }
}

function showPage(name) {
  document.querySelectorAll('.page').forEach(function(page) {
    page.classList.toggle('active', page.id === 'page-' + name);
  });
  document.querySelectorAll('.nav-tab').forEach(function(tab) {
    tab.classList.toggle('active', tab.id === 'tab-' + name);
  });
  // En móvil, si la sección está dentro del menú "Más", se marca "Más".
  navMoreBtn.classList.toggle('active', !!document.querySelector('#nav-aside #tab-' + name));
  currentPage = name;
  var sections = Array.prototype.filter.call(document.querySelectorAll('.nav-tab[id^="tab-"]'), function(tab) {
    return tab.style.display !== 'none';
  }).map(function(tab) { return tab.id.slice(4); });
  collectForAchievement('explorer', name, sections);
  if (name === 'manage') {
    loadModpacks();
  }
  if (name === 'server') {
    loadServerPageData();
  }
  if (name === 'players') {
    loadPlayers();
  }
  if (name === 'deploy') {
    loadDeployPageData();
  }
  if (name === 'users') {
    loadUsers();
  }
  if (name === 'config') {
    loadAdminConfig();
  }
  if (name === 'automation') {
    loadAutomation();
  }
}

function applyRoute(route, forcePage) {
  if (forcePage || route.page !== currentPage) {
    showPage(route.page);
  }
  if (route.page === 'manage') {
    if (route.modpack && (route.modpack !== currentModpack || !mgmtPanelOpen())) {
      selectModpack(route.modpack, route.tab);
    } else if (route.modpack && route.tab !== activeMgmtTab()) {
      activateMgmtTab(route.tab);
    } else if (!route.modpack && mgmtPanelOpen()) {
      closeModpackPanel();
    }
  }
  if (route.page === 'deploy' && route.mode && route.mode !== activeDeployMode()) {
    document.getElementById(route.mode).click();
  }
  replaceRoute(route);
}

// Salir de la pestaña Mods (o del modpack) mientras se suben o instalan mods
// dejaría la operación a medias: guardModOperationNav() lo impide.
function leavesModOperation(route) {
  return !(route.page === 'manage' && route.modpack === currentModpack && route.tab === 'mods');
}

function navigate(route) {
  if (buildHash(route) === buildHash(currentRoute()) && route.page === currentPage) {
    // Pulsar otra vez la sección en la que ya estás la recarga, como antes.
    showPage(route.page);
    return;
  }
  if (leavesModOperation(route) && guardModOperationNav()) {
    return;
  }
  confirmLeave(function() {
    var hash = buildHash(route);
    if (location.hash !== hash) {
      history.pushState(null, '', hash);
    }
    applyRoute(route);
  });
}

// Atrás/Adelante del navegador, o la URL cambiada a mano.
window.addEventListener('popstate', function() {
  var route = parseRoute(location.hash);
  if (buildHash(route) === appliedHash) {
    return;
  }
  var restore = function() { history.pushState(null, '', appliedHash); };
  if (leavesModOperation(route) && guardModOperationNav()) {
    restore();
    return;
  }
  confirmLeave(function() { applyRoute(route); }, null, restore);
});

// Lo llama auth.js nada más haber sesión: abre la sección de la URL (o
// Servidor si no hay ninguna) y carga sus datos.
function applyInitialRoute() {
  var route = parseRoute(location.hash);
  // El estado del servidor se carga siempre al entrar (como cuando Servidor
  // era la única portada): otras secciones también lo usan.
  if (route.page !== 'server') {
    loadServerPageData();
  }
  applyRoute(route, true);
}

Object.keys(PAGE_SLUGS).forEach(function(name) {
  document.getElementById('tab-' + name).addEventListener('click', function() {
    var route = { page: name };
    // Volver a Modpacks deja abierto el modpack que se estaba gestionando.
    if (name === 'manage' && currentModpack && mgmtPanelOpen()) {
      route.modpack = currentModpack;
      route.tab = activeMgmtTab();
    }
    if (name === 'deploy') {
      route.mode = activeDeployMode();
    }
    navigate(route);
  });
});

// Los modos de Instalar no tienen nada que guardar: solo se apunta en la URL.
Object.keys(DEPLOY_MODE_SLUGS).forEach(function(modeId) {
  document.getElementById(modeId).addEventListener('click', function() {
    if (currentPage === 'deploy') {
      replaceRoute({ page: 'deploy', mode: modeId });
    }
  });
});

// -- Navegación móvil: menú "Más" ---------------------------------------------
// En pantallas estrechas las secciones de administración viven en un menú
// que sube desde la barra inferior (ver nav.css). Se cierra al elegir algo,
// al pulsar fuera o con Escape.
var navEl = document.getElementById('nav');
var navMoreBtn = document.getElementById('nav-more-btn');

function setNavMoreOpen(open) {
  navEl.classList.toggle('more-open', open);
  navMoreBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
}

navMoreBtn.addEventListener('click', function(event) {
  event.stopPropagation();
  setNavMoreOpen(!navEl.classList.contains('more-open'));
});

document.getElementById('nav-aside').addEventListener('click', function(event) {
  if (event.target.closest('button')) {
    setNavMoreOpen(false);
  }
});

document.addEventListener('click', function(event) {
  if (navEl.classList.contains('more-open') && !event.target.closest('#nav-aside')) {
    setNavMoreOpen(false);
  }
});

document.addEventListener('keydown', function(event) {
  if (event.key === 'Escape' && navEl.classList.contains('more-open') && !topModal()) {
    setNavMoreOpen(false);
    navMoreBtn.focus();
  }
});

// Los botones de administración se quedan solo con el icono en pantallas
// medianas: el texto se copia a title/aria-label para que se sepa qué son.
document.querySelectorAll('.nav-aside button').forEach(function(button) {
  var label = button.querySelector('span').textContent;
  button.setAttribute('aria-label', label);
  if (!button.title) {
    button.title = label;
  }
});

function loadServerPageData() {
  loadMcDomain();
  checkServerStatus();
  loadFirewallStatus();
  loadHistoryCharts();
}
