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

  // Auto-dismiss flash messages with slide-out
  document.querySelectorAll(".flash").forEach(function (flash) {
    setTimeout(function () {
      flash.style.transition = "opacity 0.4s ease, transform 0.4s ease";
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-8px)";
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
    });
  }

  // Number counter animation for stat values
  function animateCounters() {
    document.querySelectorAll(".stat-value").forEach(function (el) {
      var text = el.textContent.trim();
      var target = parseInt(text, 10);
      if (isNaN(target) || target === 0) return;

      var duration = 600;
      var start = performance.now();
      el.textContent = "0";

      function step(now) {
        var elapsed = now - start;
        var progress = Math.min(elapsed / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(eased * target);
        if (progress < 1) {
          requestAnimationFrame(step);
        } else {
          el.textContent = text;
        }
      }
      requestAnimationFrame(step);
    });
  }
  animateCounters();

  // Button loading state on form submit
  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector('button[type="submit"]');
      if (btn && !btn.classList.contains("btn-loading")) {
        btn.classList.add("btn-loading");
        var originalHTML = btn.innerHTML;
        btn.setAttribute("data-original", originalHTML);
        setTimeout(function () {
          btn.classList.remove("btn-loading");
          if (btn.hasAttribute("data-original")) {
            btn.innerHTML = btn.getAttribute("data-original");
            btn.removeAttribute("data-original");
          }
        }, 8000);
      }
    });
  });

  // Select all checkbox animation
  var selectAll = document.getElementById("selectAll");
  var selectAllHead = document.getElementById("selectAllHead");
  if (selectAll && selectAllHead) {
    function syncCheckboxes(source) {
      var checked = source.checked;
      selectAll.checked = checked;
      selectAllHead.checked = checked;
      document.querySelectorAll(".row-check").forEach(function (cb) {
        cb.checked = checked;
      });
      updateBulkButtons();
    }
    selectAll.addEventListener("change", function () { syncCheckboxes(selectAll); });
    selectAllHead.addEventListener("change", function () { syncCheckboxes(selectAllHead); });
  }

  function updateBulkButtons() {
    var checked = document.querySelectorAll(".row-check:checked");
    var count = checked.length;
    var printBtn = document.getElementById("btnPrintSelected");
    var qrBtn = document.getElementById("btnPrintQR");
    var countSpan = document.getElementById("selectedCount");
    var qrCountSpan = document.getElementById("selectedQRCount");
    if (printBtn) printBtn.disabled = count === 0;
    if (qrBtn) qrBtn.disabled = count === 0;
    if (countSpan) countSpan.textContent = count;
    if (qrCountSpan) qrCountSpan.textContent = count;
  }

  document.querySelectorAll(".row-check").forEach(function (cb) {
    cb.addEventListener("change", updateBulkButtons);
  });

  // Print selected vehicles
  var btnPrint = document.getElementById("btnPrintSelected");
  if (btnPrint) {
    btnPrint.addEventListener("click", function () {
      var ids = [];
      document.querySelectorAll(".row-check:checked").forEach(function (cb) {
        ids.push(cb.value);
      });
      if (ids.length > 0) {
        window.open("/vehicles/print?ids=" + ids.join(","), "_blank");
      }
    });
  }

  // Print QR codes
  var btnQR = document.getElementById("btnPrintQR");
  if (btnQR) {
    btnQR.addEventListener("click", function () {
      var ids = [];
      document.querySelectorAll(".row-check:checked").forEach(function (cb) {
        ids.push(cb.value);
      });
      if (ids.length > 0) {
        window.open("/vehicles/print-qr?ids=" + ids.join(","), "_blank");
      }
    });
  }
});
