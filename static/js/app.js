/* Starlight Model School - UI behaviours */
(function () {
  "use strict";

  var ICONS = {
    success: "fa-circle-check",
    danger: "fa-circle-exclamation",
    warning: "fa-triangle-exclamation",
    info: "fa-circle-info",
    message: "fa-circle-info"
  };

  /* ---------------------------------------------------------
     Toasts
     --------------------------------------------------------- */
  var stack = document.getElementById("toastStack");

  function showToast(message, category) {
    if (!stack) return;
    category = category || "message";

    var el = document.createElement("div");
    el.className = "app-toast " + category;
    el.setAttribute("role", category === "danger" ? "alert" : "status");

    var icon = ICONS[category] || ICONS.message;
    el.innerHTML =
      '<i class="fa-solid ' + icon + ' toast-icon" aria-hidden="true"></i>' +
      '<div class="toast-body"></div>' +
      '<button type="button" class="toast-close" aria-label="Dismiss">' +
      '<i class="fa-solid fa-xmark" aria-hidden="true"></i></button>';

    // textContent, never innerHTML - flash messages can contain user data
    el.querySelector(".toast-body").textContent = message;

    stack.appendChild(el);

    var timer = setTimeout(function () { dismiss(el); }, 5200);
    el.querySelector(".toast-close").addEventListener("click", function () {
      clearTimeout(timer);
      dismiss(el);
    });
  }

  function dismiss(el) {
    el.classList.add("is-leaving");
    setTimeout(function () { el.remove(); }, 220);
  }

  // Move the server-rendered flash alerts into the toast stack
  function harvestFlashes() {
    if (!stack) return;
    var alerts = document.querySelectorAll(".main-content > .alert");
    Array.prototype.forEach.call(alerts, function (alert) {
      var clone = alert.cloneNode(true);
      var btn = clone.querySelector(".btn-close");
      if (btn) btn.remove();
      alert.remove();
      showToast(clone.textContent.trim(), alert.className.match(/alert-(\w+)/)[1]);
    });
  }

  /* ---------------------------------------------------------
     Theme toggle
     --------------------------------------------------------- */
  function initTheme() {
    var btn = document.getElementById("themeToggle");
    var icon = document.getElementById("themeIcon");
    if (!btn) return;

    function paint() {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      icon.className = "fa-solid " + (dark ? "fa-sun" : "fa-moon");
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
    }

    btn.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("smc-theme", next); } catch (e) {}
      paint();
    });

    paint();
  }

  /* ---------------------------------------------------------
     Mobile sidebar
     --------------------------------------------------------- */
  function initSidebar() {
    var toggle = document.getElementById("mobileToggle");
    var overlay = document.getElementById("sidebarOverlay");
    var sidebar = document.querySelector(".sidebar");
    var closeBtn = document.getElementById("sidebarClose");
    if (!toggle || !sidebar) return;

    function isOpen() { return sidebar.classList.contains("show"); }

    function open() {
      sidebar.classList.add("show");
      if (overlay) overlay.classList.add("show");
      toggle.setAttribute("aria-expanded", "true");
      document.body.classList.add("nav-open");
      // move focus into the drawer so keyboard users land where they clicked
      var first = sidebar.querySelector("a, button");
      if (first) setTimeout(function () { first.focus(); }, 260);
    }

    function close() {
      sidebar.classList.remove("show");
      if (overlay) overlay.classList.remove("show");
      toggle.setAttribute("aria-expanded", "false");
      document.body.classList.remove("nav-open");
    }

    toggle.addEventListener("click", function () {
      if (isOpen()) { close(); } else { open(); }
    });
    if (overlay) overlay.addEventListener("click", close);
    if (closeBtn) closeBtn.addEventListener("click", close);

    // close after navigating on small screens
    sidebar.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth < 992) setTimeout(close, 120);
      });
    });

    // Escape closes, and Tab cycles inside the drawer while it is open
    document.addEventListener("keydown", function (e) {
      if (!isOpen()) return;
      if (e.key === "Escape") { close(); toggle.focus(); return; }
      if (e.key !== "Tab") return;

      var focusable = sidebar.querySelectorAll(
        'a[href], button:not([disabled]), input, select, textarea'
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth >= 992) close();
    });
  }

  /* ---------------------------------------------------------
     Submit-button loading states
     --------------------------------------------------------- */
  function initLoadingStates() {
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function () {
        // let validation failures (e.g. HTML5 required) stop the spinner
        if (!form.checkValidity()) return;
        var btn = form.querySelector('button[type="submit"], input[type="submit"]');
        if (!btn || btn.classList.contains("is-loading")) return;
        btn.classList.add("is-loading");
        btn.dataset.originalText = btn.textContent;
        setTimeout(function () {
          // if the page did not navigate, restore the button
          if (document.body.contains(btn)) {
            btn.classList.remove("is-loading");
          }
        }, 15000);
      });
    });
  }

  /* ---------------------------------------------------------
     Auto-dismiss inline alerts left in templates
     --------------------------------------------------------- */
  function autoHideInlineAlerts() {
    document.querySelectorAll(".main-content .alert").forEach(function (alert) {
      setTimeout(function () {
        alert.style.transition = "opacity .3s ease, transform .3s ease";
        alert.style.opacity = "0";
        alert.style.transform = "translateY(-6px)";
        setTimeout(function () { alert.remove(); }, 320);
      }, 7000);
    });
  }

  /* ---------------------------------------------------------
     Confirm-once guard for destructive forms
     --------------------------------------------------------- */
  function initConfirmGuard() {
    document.querySelectorAll("form[onsubmit*='confirm']").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (form.dataset.confirmed === "1") {
          e.preventDefault();
          return;
        }
        // the inline onsubmit already showed the prompt
        form.dataset.confirmed = "1";
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    harvestFlashes();
    initTheme();
    initSidebar();
    initLoadingStates();
    initConfirmGuard();
    autoHideInlineAlerts();
  });

  window.StarlightUI = { showToast: showToast };
})();
