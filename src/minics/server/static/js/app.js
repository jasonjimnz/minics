/* MiniCS app shell: routing, events, job tracking. */
(function () {
  "use strict";

  const ROUTES = ["dashboard", "datasets", "entries", "collections", "documents", "chat", "graph", "jobs", "settings", "about"];
  const trackedJobs = new Map();

  function parseHash() {
    const raw = (location.hash || "#dashboard").slice(1);
    const [route, queryString] = raw.split("?");
    const params = {};
    if (queryString) new URLSearchParams(queryString).forEach((value, key) => { params[key] = value; });
    return { route: ROUTES.includes(route) ? route : "dashboard", params };
  }

  function navigate(route, params) {
    const query = params ? new URLSearchParams(params).toString() : "";
    location.hash = `#${route}${query ? "?" + query : ""}`;
  }

  function refresh() {
    render().catch((error) => {
      console.error(error);
      UI.toast("Could not render view", "error", error.message);
    });
  }

  async function render() {
    const { route, params } = parseHash();
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.route === route);
    });
    const view = document.getElementById("view");
    view.scrollTop = 0;
    UI.clear(view).appendChild(
      UI.el("div", { class: "empty" }, UI.el("div", { class: "big", text: "⟳" }), UI.el("p", { text: "Loading…" }))
    );
    const handler = window.Views[route] || window.Views.dashboard;
    UI.clear(view);
    await handler(view, params);
    if (route === "settings") await refreshHealth();
  }

  function trackJob(id) {
    trackedJobs.set(id, true);
  }

  function watchJob(id, callback) {
    trackJob(id);
    const poll = async () => {
      try {
        const job = await API.get(`/api/jobs/${id}`);
        if (["success", "error", "cancelled"].includes(job.status)) {
          trackedJobs.delete(id);
          if (job.status === "error") UI.toast(`${job.name} failed`, "error", job.error || "");
          callback && callback(job.result, job);
          if (parseHash().route === "jobs") refresh();
          return;
        }
        setTimeout(poll, 800);
      } catch (error) {
        trackedJobs.delete(id);
      }
    };
    setTimeout(poll, 600);
  }

  async function refreshHealth() {
    try {
      const health = await API.get("/api/health");
      const pill = document.getElementById("ready-pill");
      if (pill) {
        pill.textContent = health.ready ? "ready" : "setup";
        pill.className = `pill ${health.ready ? "ok" : "warn"}`;
        pill.title = health.ready ? `LLM ready · ${health.home}` : `Missing: ${health.missing.join(", ")}`;
      }
      const status = document.getElementById("status-line");
      if (status) status.textContent = `${health.home}`;
      return health;
    } catch (error) {
      const pill = document.getElementById("ready-pill");
      if (pill) { pill.textContent = "offline"; pill.className = "pill err"; }
      return null;
    }
  }

  function initEvents() {
    API.events((event) => {
      if (event.type === "job.finished") {
        const level = event.level === "error" ? "error" : "success";
        UI.toast(event.message || "Job finished", level);
        if (parseHash().route === "jobs") refresh();
      } else if (event.type === "job.started" || event.type === "job.queued") {
        if (parseHash().route === "jobs") refresh();
      } else if (event.type && event.level === "warning") {
        UI.toast(event.message || event.type, "warning");
      }
      const row = document.getElementById(`job-${event.job_id}`);
      if (row && typeof event.progress === "number") {
        const bar = row.querySelector(".bar > span");
        if (bar) bar.style.width = `${Math.round(event.progress * 100)}%`;
        const label = row.querySelector(".muted.tiny");
        if (label && event.message) label.textContent = event.message;
      }
    });
  }

  function initSearch() {
    const input = document.getElementById("global-search");
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const value = input.value.trim();
      if (!value) return;
      const route = parseHash().route;
      if (route === "documents") navigate("documents", { search: value });
      else if (route === "datasets" || route === "collections") navigate(route, { search: value });
      else navigate("entries", { search: value });
    });
  }

  function initShell() {
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.addEventListener("click", () => {
        navigate(item.dataset.route);
        document.body.classList.remove("nav-open");
      });
    });
    document.getElementById("menu-toggle").addEventListener("click", () => document.body.classList.toggle("nav-open"));
    document.getElementById("refresh-btn").addEventListener("click", () => refresh());
    document.getElementById("theme-select").addEventListener("change", () => {
      const config = window.MINICS.config;
      config.app.theme = document.getElementById("theme-select").value;
      API.put("/api/config", { app: { theme: config.app.theme } }).catch(() => {});
    });
    window.addEventListener("hashchange", refresh);
  }

  window.App = { navigate, refresh, trackJob, watchJob };

  document.addEventListener("DOMContentLoaded", () => {
    UI.initThemes();
    initShell();
    initSearch();
    initEvents();
    refreshHealth();
    if (!location.hash) location.hash = "#dashboard";
    refresh();
    setInterval(refreshHealth, 30000);
  });
})();
