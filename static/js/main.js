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
