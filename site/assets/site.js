// MiniCS docs: theme toggle, search, TOC highlighting
(function () {
  "use strict";

  /* ---------- Theme ---------- */
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");
  var stored = null;
  try { stored = localStorage.getItem("docs-theme"); } catch (e) {}

  function apply(mode) {
    root.setAttribute("data-color-mode", mode);
  }
  apply(stored || "auto");

  toggle.addEventListener("click", function () {
    var cur = root.getAttribute("data-color-mode");
    var isDark = cur === "dark" ||
      (cur === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var next = isDark ? "light" : "dark";
    apply(next);
    try { localStorage.setItem("docs-theme", next); } catch (e) {}
  });

  /* ---------- Search ---------- */
  var input = document.getElementById("search-input");
  var box = document.getElementById("search-results");
  var index = [];
  fetch("assets/search.json")
    .then(function (r) { return r.json(); })
    .then(function (data) { index = data; })
    .catch(function () {});

  var selected = -1;
  var results = [];

  function snippet(text, q) {
    var lower = text.toLowerCase();
    var pos = lower.indexOf(q);
    if (pos === -1) return text.slice(0, 120);
    var start = Math.max(0, pos - 40);
    var frag = text.slice(start, start + 140);
    var re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
    return frag.replace(re, "<mark>$1</mark>");
  }

  function render() {
    if (!box.hidden) box.hidden = true;
    var q = input.value.trim().toLowerCase();
    if (q.length < 2) { box.hidden = true; return; }
    results = [];
    var seen = {};
    for (var i = 0; i < index.length && results.length < 12; i++) {
      var item = index[i];
      var hay = (item.h + " " + item.x + " " + item.t).toLowerCase();
      if (hay.indexOf(q) !== -1 && !seen[item.p + "#" + item.a]) {
        seen[item.p + "#" + item.a] = true;
        results.push(item);
      }
    }
    selected = -1;
    if (!results.length) {
      box.innerHTML = '<div class="search-empty">No results for "' +
        input.value.replace(/</g, "&lt;") + '"</div>';
      box.hidden = false;
      return;
    }
    box.innerHTML = results.map(function (item, i) {
      var href = item.p === "index" && !item.a
        ? "index.html"
        : item.p + ".html" + (item.a ? "#" + item.a : "");
      return '<a class="search-result" href="' + href + '" data-i="' + i + '">' +
        '<div class="sr-page">' + item.t + "</div>" +
        (item.h ? '<div class="sr-heading">' + item.h + "</div>" : "") +
        '<div class="sr-snippet">' + snippet(item.x, q) + "</div></a>";
    }).join("");
    box.hidden = false;
    box.querySelectorAll(".search-result").forEach(function (el) {
      el.addEventListener("mousedown", function (e) {
        e.preventDefault();
        window.location.href = el.getAttribute("href");
      });
    });
  }

  input.addEventListener("input", render);
  input.addEventListener("focus", render);
  document.addEventListener("click", function (e) {
    if (!document.getElementById("search-box").contains(e.target)) box.hidden = true;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== input) {
      e.preventDefault();
      input.focus();
      input.select();
      return;
    }
    if (e.key === "Escape") { box.hidden = true; input.blur(); }
    if (box.hidden || !results.length) return;
    var items = box.querySelectorAll(".search-result");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selected = Math.min(selected + 1, items.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selected = Math.max(selected - 1, 0);
    } else if (e.key === "Enter" && selected >= 0) {
      window.location.href = items[selected].getAttribute("href");
      return;
    } else {
      return;
    }
    items.forEach(function (el, i) {
      el.classList.toggle("selected", i === selected);
    });
    if (items[selected]) items[selected].scrollIntoView({ block: "nearest" });
  });

  /* ---------- TOC active highlight ---------- */
  var tocLinks = document.querySelectorAll(".toc a");
  if (tocLinks.length && "IntersectionObserver" in window) {
    var map = {};
    tocLinks.forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      var el = document.getElementById(id);
      if (el) map[id] = a;
    });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          tocLinks.forEach(function (a) { a.classList.remove("active"); });
          var link = map[entry.target.id];
          if (link) link.classList.add("active");
        }
      });
    }, { rootMargin: "-80px 0px -70% 0px" });
    Object.keys(map).forEach(function (id) {
      observer.observe(document.getElementById(id));
    });
  }
})();
