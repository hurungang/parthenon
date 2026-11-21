/* Parthenon UX prototype — per-page bootstrap, loaded last so page scripts
   (which legitimately redefine a few legacy names) win the load order. */
(function () {
  if (typeof protoBoot === 'function') protoBoot();
})();
