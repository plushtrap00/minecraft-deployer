// El tema elegido se aplica antes de pintar nada, para que no se vea un
// instante el de por defecto (el resto de Apariencia está en appearance.js).
// Va en su propio archivo y no dentro de index.html porque la
// Content-Security-Policy (main.py) solo deja ejecutar scripts de /static.
(function() {
  try {
    var savedTheme = localStorage.getItem('mcd-theme');
    if (savedTheme && savedTheme !== 'amethyst') {
      document.documentElement.setAttribute('data-theme', savedTheme);
    }
  } catch (e) {}
})();
