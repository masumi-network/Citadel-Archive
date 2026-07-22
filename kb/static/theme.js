/* Citadel dashboard theme toggle. Loaded as an external script (CSP
   script-src 'self'). Applies any saved preference to <html> as early as
   possible, then wires an optional #themeToggle button. Default (no saved
   pref, OS not light) stays dark; OS light without an override shows light. */
(function () {
  "use strict";
  var root = document.documentElement;

  try {
    var saved = localStorage.getItem("citadel-theme");
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) { /* storage blocked — fall back to prefers-color-scheme */ }

  function current() {
    var attr = root.getAttribute("data-theme");
    if (attr) return attr;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }

  function label(btn) {
    if (btn) btn.textContent = current() === "light" ? "☀ Light" : "☾ Dark";
  }

  function wire() {
    var btn = document.getElementById("themeToggle");
    if (!btn) return;
    label(btn);
    btn.addEventListener("click", function () {
      var next = current() === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("citadel-theme", next); } catch (e) { /* ignore */ }
      label(btn);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
