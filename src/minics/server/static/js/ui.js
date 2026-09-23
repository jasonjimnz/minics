/* MiniCS UI toolkit: DOM helpers, toasts, modal, markdown, themes. */
(function () {
  "use strict";

  /* id, label, kind — kind drives the optgroup in pickers ("auto" floats first). */
  const THEMES = [
    ["system", "System", "auto"],
    ["light", "Light", "light"],
    ["ocean", "Ocean", "light"],
    ["forest", "Forest", "light"],
    ["sunset", "Sunset", "light"],
    ["rose", "Rose", "light"],
    ["paper", "Paper", "light"],
    ["mono", "Mono", "light"],
    ["grape", "Grape", "light"],
    ["solarized", "Solarized", "light"],
    ["dark", "Dark", "dark"],
    ["nord", "Nord", "dark"],
    ["midnight", "Midnight", "dark"],
    ["dracula", "Dracula", "dark"],
    ["mocha", "Catppuccin Mocha", "dark"],
  ];

  function el(tag, attrs) {
    const node = document.createElement(tag);
    const children = Array.prototype.slice.call(arguments, 2);
    if (attrs && typeof attrs === "object") {
      Object.entries(attrs).forEach(([key, value]) => {
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "html") node.innerHTML = value;
        else if (key === "text") node.textContent = value;
        else if (key === "dataset") Object.assign(node.dataset, value);
        else if (key.startsWith("on") && typeof value === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (key === "style" && typeof value === "object") {
          Object.assign(node.style, value);
        } else if (value === true) node.setAttribute(key, "");
        else node.setAttribute(key, value);
      });
    }
    children.flat().forEach((child) => {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" || typeof child === "number"
        ? document.createTextNode(String(child))
        : child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* -- markdown ---------------------------------------------------------- */
  function inline(text) {
    let out = escapeHtml(text);
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return out;
  }

  function markdown(text) {
    const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let i = 0;
    let listOpen = null;

    const closeList = () => {
      if (listOpen) { html.push(`</${listOpen}>`); listOpen = null; }
    };

    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line.trim())) {
        closeList();
        const buffer = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i].trim())) { buffer.push(lines[i]); i += 1; }
        html.push(`<pre><code>${escapeHtml(buffer.join("\n"))}</code></pre>`);
        i += 1;
        continue;
      }
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        closeList();
        const level = heading[1].length;
        html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        i += 1;
        continue;
      }
      if (/^\s*([-*+])\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
        const ordered = /^\s*\d+\.\s+/.test(line);
        const tag = ordered ? "ol" : "ul";
        if (listOpen !== tag) { closeList(); html.push(`<${tag}>`); listOpen = tag; }
        html.push(`<li>${inline(line.replace(/^\s*(?:[-*+]|\d+\.)\s+/, ""))}</li>`);
        i += 1;
        continue;
      }
      if (/^\s*>/.test(line)) {
        closeList();
        const buffer = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { buffer.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
        html.push(`<blockquote>${inline(buffer.join(" "))}</blockquote>`);
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s\-:|]+\|\s*$/.test(lines[i + 1])) {
        closeList();
        const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
        const head = cells(line);
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(cells(lines[i])); i += 1; }
        html.push(
          `<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>` +
          `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`
        );
        continue;
      }
      if (!line.trim()) { closeList(); i += 1; continue; }
      closeList();
      const buffer = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*[-*+]\s|\s*\d+\.\s|\s*>|\s*\|)/.test(lines[i])) {
        buffer.push(lines[i]); i += 1;
      }
      html.push(`<p>${inline(buffer.join(" "))}</p>`);
    }
    closeList();
    return html.join("\n");
  }

  /* -- toasts ------------------------------------------------------------ */
  function toast(message, level, detail, timeout) {
    const root = document.getElementById("toasts");
    if (!root) return;
    const node = el("div", { class: `toast ${level || "info"}` },
      el("div", { text: message }),
      detail ? el("small", { text: detail }) : null
    );
    root.appendChild(node);
    setTimeout(() => {
      node.style.opacity = "0";
      node.style.transform = "translateY(8px)";
      setTimeout(() => node.remove(), 220);
    }, timeout || 4200);
  }

  /* -- modal ------------------------------------------------------------- */
  const modalRoot = () => document.getElementById("modal-root");
  let modalKeyHandler = null;

  function openModal(options) {
    options = options || {};
    const root = modalRoot();
    document.getElementById("modal-title").textContent = options.title || "";
    const body = clear(document.getElementById("modal-body"));
    if (typeof options.body === "string") body.innerHTML = options.body;
    else if (options.body) body.appendChild(options.body);

    const foot = clear(document.getElementById("modal-foot"));
    (options.actions || []).forEach((action) => {
      foot.appendChild(el("button", {
        class: `btn ${action.class || ""}`.trim(),
        text: action.label,
        onclick: () => action.onClick && action.onClick({ close: closeModal }),
      }));
    });
    if (!options.actions || !options.actions.length) {
      foot.appendChild(el("button", { class: "btn ghost", text: "Close", onclick: closeModal }));
    }
    root.classList.remove("hidden");
    modalKeyHandler = (event) => { if (event.key === "Escape") closeModal(); };
    document.addEventListener("keydown", modalKeyHandler);
    if (options.onMount) options.onMount(body);
    return { close: closeModal, body };
  }

  function closeModal() {
    const root = modalRoot();
    if (root) root.classList.add("hidden");
    if (modalKeyHandler) document.removeEventListener("keydown", modalKeyHandler);
    modalKeyHandler = null;
  }

  document.addEventListener("click", (event) => {
    if (event.target.dataset && event.target.dataset.close) closeModal();
  });

  function confirm(options) {
    return new Promise((resolve) => {
      openModal({
        title: options.title || "Are you sure?",
        body: el("p", { text: options.message || "" }),
        actions: [
          { label: "Cancel", class: "ghost", onClick: ({ close }) => { close(); resolve(false); } },
          { label: options.confirm || "Confirm", class: options.danger ? "danger" : "", onClick: ({ close }) => { close(); resolve(true); } },
        ],
      });
    });
  }

  /* -- formatting -------------------------------------------------------- */
  function fmtDate(value) {
    if (!value) return "—";
    const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function fmtBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined) return "";
    if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
    return `${seconds.toFixed(1)} s`;
  }

  /* -- themes ------------------------------------------------------------ */
  function applyTheme(name) {
    const theme = THEMES.some(([id]) => id === name) ? name : "system";
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("minics.theme", theme); } catch (error) { /* ignore */ }
    const select = document.getElementById("theme-select");
    if (select) select.value = theme;
  }

  function themeOptions(selected) {
    /* "System" floats above grouped Light / Dark optgroups. */
    const fragment = document.createDocumentFragment();
    const add = (id, label) =>
      fragment.appendChild(el("option", { value: id, text: label, selected: id === selected }));
    const groups = {
      light: el("optgroup", { label: "Light" }),
      dark: el("optgroup", { label: "Dark" }),
    };
    THEMES.forEach(([id, label, kind]) => {
      if (kind === "auto") { add(id, label); return; }
      groups[kind].appendChild(el("option", { value: id, text: label, selected: id === selected }));
    });
    fragment.appendChild(groups.light);
    fragment.appendChild(groups.dark);
    return fragment;
  }

  function initThemes() {
    const select = document.getElementById("theme-select");
    if (!select) return;
    clear(select);
    let stored = "system";
    try { stored = localStorage.getItem("minics.theme") || "system"; } catch (error) { /* ignore */ }
    select.appendChild(themeOptions(stored));
    applyTheme(stored);
    select.addEventListener("change", () => applyTheme(select.value));
  }

  window.UI = {
    THEMES,
    el,
    clear,
    escapeHtml,
    markdown,
    toast,
    modal: { open: openModal, close: closeModal, confirm },
    fmtDate,
    fmtBytes,
    fmtDuration,
    applyTheme,
    themeOptions,
    initThemes,
  };
})();
