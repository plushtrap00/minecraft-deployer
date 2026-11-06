//  Navegación
['deploy', 'manage', 'server', 'players', 'help', 'users', 'config'].forEach(function(name) {
  document.getElementById('tab-' + name).addEventListener('click', function() {
    if (guardModOperationNav()) {
      return;
    }
    document.querySelectorAll('.page').forEach(function(page) {
      page.classList.remove('active');
    });
    document.querySelectorAll('.nav-tab').forEach(function(tab) {
      tab.classList.remove('active');
    });
    document.getElementById('page-' + name).classList.add('active');
    this.classList.add('active');
    // En móvil, si la sección está dentro del menú "Más", se marca "Más".
    navMoreBtn.classList.toggle('active', !!this.closest('#nav-aside'));
    if (name === 'manage') {
      loadModpacks();
    }
    if (name === 'server') {
      loadServerPageData();
    }
    if (name === 'users') {
      loadUsers();
    }
    if (name === 'config') {
      loadAdminConfig();
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
  if (event.key === 'Escape' && navEl.classList.contains('more-open')) {
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

// "Servidor" es la pestaña activa por defecto (ver static/index.html), así
// que necesita cargar sus datos también al entrar a la app, no solo al hacer
// clic en la pestaña — se llama desde onLoginSuccess()/checkExistingToken()
// en auth.js, una vez hay sesión real (no antes, para no repetir el mismo
// 401-antes-de-login que ya rompía el sondeo de auto-actualización).
function loadServerPageData() {
  loadMcDomain();
  checkServerStatus();
  loadFirewallStatus();
}
