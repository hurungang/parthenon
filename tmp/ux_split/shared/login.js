/* Parthenon UX prototype — login screen (this page only).
   The single-file prototype opened on the login screen; the hub opens on the
   Dashboard instead, and the login states are reachable from the prototype map. */
function protoShowLogin() {
  var lp = document.getElementById('login-page');
  if (!lp) return;
  lp.style.display = 'flex';
  var sw = document.getElementById('oidc-demo-switcher');
  if (sw) sw.style.display = '';
  oidcSetState('findws');
}
function protoHideLogin() {
  var lp = document.getElementById('login-page');
  if (lp) lp.style.display = 'none';
  var sw = document.getElementById('oidc-demo-switcher');
  if (sw) sw.style.display = 'none';
}
(function () {
  var boot = function () { protoHideLogin(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
