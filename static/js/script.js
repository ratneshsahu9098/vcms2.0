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
    });
  }
});
