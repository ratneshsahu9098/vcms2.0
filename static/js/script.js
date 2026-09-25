document.addEventListener("DOMContentLoaded", function () {
  // Sidebar toggle
  var toggle = document.getElementById("sidebarToggle");
  var sidebar = document.querySelector(".sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      sidebar.classList.toggle("open");
    });
    document.addEventListener("click", function (e) {
      if (window.innerWidth <= 900 && sidebar.classList.contains("open")) {
        if (!sidebar.contains(e.target) && e.target !== toggle && !toggle.contains(e.target)) {
          sidebar.classList.remove("open");
        }
      }
    });
  }

  // Auto-dismiss flash messages after a few seconds
  document.querySelectorAll(".flash").forEach(function (flash) {
    setTimeout(function () {
      flash.style.transition = "opacity 0.4s ease";
      flash.style.opacity = "0";
      setTimeout(function () { flash.remove(); }, 400);
    }, 5000);
  });

  // Theme toggle
  var themeToggle = document.getElementById("themeToggle");
  var themeIcon = document.getElementById("themeIcon");
  if (themeToggle && themeIcon) {
    function updateIcon() {
      var current = document.documentElement.getAttribute("data-theme");
      if (current === "light") {
        themeIcon.classList.remove("fa-sun");
        themeIcon.classList.add("fa-moon");
      } else {
        themeIcon.classList.remove("fa-moon");
        themeIcon.classList.add("fa-sun");
      }
    }
    updateIcon();
    themeToggle.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      var next = current === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("vcms_theme", next);
      updateIcon();
      themeIcon.classList.remove("spin");
      void themeIcon.offsetWidth;
      themeIcon.classList.add("spin");
    });
  }

  // Escape closes the mobile sidebar
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sidebar && sidebar.classList.contains("open")) {
      sidebar.classList.remove("open");
    }
  });

  // ---- UI motion layer (progressive enhancement) ----
  try {
    (function motion() {
      if (!document.documentElement.classList.contains("js-motion")) return;
      window.__vcmsMotionReady = true;

      var supportsIO = "IntersectionObserver" in window;
      var revealSelector =
        ".stat-card, .doc-card, .panel, .detail-card, .table-wrap, " +
        ".form-card, .import-form, .export-form, " +
        ".table-main tbody tr, .reminder-entry";
      var targets = Array.prototype.slice.call(document.querySelectorAll(revealSelector));

      function countUp(el) {
        if (!el || el.dataset.counted) return;
        var raw = el.textContent.trim().replace(/,/g, "");
        if (!/^\d+$/.test(raw)) return;
        var target = parseInt(raw, 10);
        if (target < 1) return;
        el.dataset.counted = "1";
        var withComma = el.textContent.indexOf(",") !== -1;
        var dur = 800, t0 = null;
        function frame(now) {
          if (t0 === null) t0 = now;
          var p = Math.min((now - t0) / dur, 1);
          var eased = 1 - Math.pow(1 - p, 3);
          var val = Math.round(target * eased);
          el.textContent = withComma ? val.toLocaleString() : String(val);
          if (p < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
      }

      function onReveal(el) {
        el.classList.add("revealed");
        if (el.classList.contains("stat-card")) countUp(el.querySelector(".stat-value"));
      }

      if (!supportsIO) {
        targets.forEach(function (el) { el.classList.add("revealed"); });
        document.querySelectorAll(".stat-value").forEach(countUp);
        return;
      }

      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            onReveal(entry.target);
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -30px 0px", threshold: 0.04 });

      targets.forEach(function (el, i) {
        if (i < 40) {
          el.style.setProperty("--rev-d", Math.min(i * 55, 660) + "ms");
          io.observe(el);
        } else {
          onReveal(el);
        }
      });
    })();
  } catch (err) {
    // Motion failed: make sure content is never stuck hidden
    document.documentElement.classList.remove("js-motion");
    document.querySelectorAll(".revealed").forEach(function (el) { el.classList.remove("revealed"); });
  }
});
