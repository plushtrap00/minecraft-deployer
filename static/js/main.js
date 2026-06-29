//  Navegacin
['deploy','manage','server','players','users'].forEach(function(name) {
  document.getElementById('tab-'+name).addEventListener('click', function() {
    document.querySelectorAll('.page').forEach(function(p){ p.classList.remove('active'); });
    document.querySelectorAll('.nav-tab').forEach(function(t){ t.classList.remove('active'); });
    document.getElementById('page-'+name).classList.add('active');
    this.classList.add('active');
    if (name === 'manage') loadModpacks();
    if (name === 'server') { loadMcDomain(); checkServerStatus(); loadFirewallStatus(); }
    if (name === 'users') loadUsers();
  });
});
