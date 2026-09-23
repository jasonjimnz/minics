/* MiniCS views: dashboard, datasets, entries, collections, documents, chat, graph, jobs, settings. */
(function () {
  "use strict";

  const el = UI.el;
  const T = UI.toast;

  const state = {
    datasets: [],
    entries: { list: [], selected: null, dataset: "", status: "", search: "" },
    collections: { list: [], selected: null },
    documents: { list: [], selected: null },
    chat: { list: [], selected: null, controller: null },
    graph: { data: null, query: "" },
    settings: { config: null, models: { chat: [], embedding: [] } },
  };

  /* -- shared helpers ---------------------------------------------------- */
  function head(title, subtitle, actions) {
    return el("div", { class: "page-head" },
      el("div", null,
        el("h1", { text: title }),
        subtitle ? el("div", { class: "muted", text: subtitle }) : null
      ),
      el("div", { class: "spacer" }),
      actions || null
    );
  }

  function empty(icon, title, hint) {
    return el("div", { class: "empty" },
      el("div", { class: "big", text: icon }),
      el("h3", { text: title }),
      hint ? el("p", { text: hint }) : null
    );
  }

  function statusBadge(status) {
    return el("span", { class: `badge ${status}`, text: status });
  }

  function spinner(label) {
    return el("div", { class: "empty" }, el("div", { class: "big", text: "⟳" }), el("p", { text: label || "Loading…" }));
  }

  async function datasetOptions(selected) {
    const data = await API.get("/api/datasets");
    state.datasets = data.items || [];
    const select = el("select", null);
    select.appendChild(el("option", { value: "", text: "All datasets" }));
    state.datasets.forEach((item) => {
      select.appendChild(el("option", { value: item.public_id, text: item.name, selected: item.public_id === selected }));
    });
    return select;
  }

  function jobToast(job, label) {
    T(`${label || job.name} started`, "info", "Track progress in Activity");
    App.trackJob(job.id);
    return job.id;
  }

  /* -- dashboard --------------------------------------------------------- */
  async function dashboard(view) {
    view.appendChild(head("Dashboard", "Your dataset studio at a glance"));
    const [overview, history] = await Promise.all([
      API.get("/api/overview"),
      API.get("/api/events/history?limit=12"),
    ]);

    const stats = [
      ["Datasets", overview.datasets, "datasets"],
      ["Entries", overview.entries, "entries"],
      ["Approved", overview.approved, "collections"],
      ["Documents", overview.documents.documents, "documents"],
      ["Chunks indexed", overview.chunks.chunks, "graph"],
      ["Graph entities", (overview.graph && overview.graph.entities) || 0, "graph"],
    ];
    view.appendChild(el("div", { class: "grid cols-3" },
      stats.map(([label, value, route]) =>
        el("div", { class: "card interactive", onclick: () => App.navigate(route) },
          el("div", { class: "stat-value", text: String(value) }),
          el("div", { class: "muted", text: label })
        )
      )
    ));

    const ready = overview.ready;
    const steps = [
      { done: ready, label: "Configure the LLM & embedding endpoints", route: "settings" },
      { done: overview.datasets > 0, label: "Create your first dataset", route: "datasets" },
      { done: overview.documents.documents > 0, label: "Import documents for grounding", route: "documents" },
      { done: overview.entries > 0, label: "Author ChatML entries", route: "entries" },
      { done: overview.chunks.chunks > 0, label: "Index documents for RAG", route: "documents" },
      { done: overview.approved > 0, label: "Approve entries and build collections", route: "collections" },
    ];
    view.appendChild(el("div", { class: "section-title", text: "Getting started" }));
    view.appendChild(el("div", { class: "card" },
      steps.map((step) =>
        el("div", { class: "job", style: { marginBottom: "8px", cursor: "pointer" }, onclick: () => App.navigate(step.route) },
          el("span", { class: `pill ${step.done ? "ok" : "warn"}`, text: step.done ? "done" : "todo" }),
          el("div", { style: { flex: "1" }, text: step.label })
        )
      )
    ));

    view.appendChild(el("div", { class: "section-title", text: "Recent activity" }));
    const activity = el("div", { class: "card" });
    if (!history.items.length) activity.appendChild(el("div", { class: "muted", text: "No activity yet." }));
    history.items.slice().reverse().forEach((event) => {
      activity.appendChild(el("div", { class: "job", style: { marginBottom: "6px", border: "0", padding: "6px 0" } },
        el("span", { class: `pill ${event.level === "error" ? "err" : event.level === "success" ? "ok" : ""}`, text: event.type }),
        el("div", { style: { flex: "1" }, text: event.message || "" }),
        el("span", { class: "muted tiny", text: UI.fmtDate(event.ts) })
      ));
    });
    view.appendChild(activity);
  }

  /* -- datasets ---------------------------------------------------------- */
  async function datasets(view) {
    view.appendChild(head("Datasets", "Groups of ChatML entries", el("button", { class: "btn", text: "+ New dataset", onclick: () => newDataset() })));
    const data = await API.get("/api/datasets");
    state.datasets = data.items || [];
    if (!state.datasets.length) {
      view.appendChild(empty("▤", "No datasets yet", "Create a dataset to start collecting entries."));
      return;
    }
    view.appendChild(el("div", { class: "grid cols-3" },
      state.datasets.map((dataset) =>
        el("div", { class: "card interactive", onclick: () => App.navigate("entries", { dataset: dataset.public_id }) },
          el("h3", { text: dataset.name }),
          el("div", { class: "muted", text: dataset.description || "No description" }),
          el("div", { class: "meta", style: { marginTop: "10px" } },
            el("span", { text: `${dataset.stats.entries} entries` }),
            el("span", { text: `${dataset.stats.approved} approved` })
          ),
          el("div", { class: "chips", style: { marginTop: "10px" } },
            (dataset.tags || []).map((tag) => el("span", { class: "chip", text: tag }))
          ),
          el("div", { class: "toolbar", style: { marginTop: "12px", marginBottom: "0" } },
            el("button", { class: "btn small ghost", text: "Edit", onclick: (event) => { event.stopPropagation(); newDataset(dataset); } }),
            el("button", { class: "btn small ghost", text: "Delete", onclick: async (event) => {
              event.stopPropagation();
              if (await UI.modal.confirm({ title: "Delete dataset?", message: dataset.name, confirm: "Delete", danger: true })) {
                await API.del(`/api/datasets/${dataset.public_id}`);
                T("Dataset deleted", "success");
                App.refresh();
              }
            } })
          )
        )
      )
    ));
  }

  async function newDataset(existing) {
    const name = el("input", { type: "text", value: existing ? existing.name : "", placeholder: "Support QA" });
    const description = el("textarea", { rows: "3", placeholder: "What is this dataset for?" });
    description.value = existing ? existing.description : "";
    const tags = el("input", { type: "text", placeholder: "comma, separated, tags" });
    tags.value = existing ? (existing.tags || []).join(", ") : "";
    UI.modal.open({
      title: existing ? "Edit dataset" : "New dataset",
      body: el("div", null,
        el("label", { class: "field" }, el("span", { text: "Name" }), name),
        el("label", { class: "field", style: { marginTop: "12px" } }, el("span", { text: "Description" }), description),
        el("label", { class: "field", style: { marginTop: "12px" } }, el("span", { text: "Tags" }), tags)
      ),
      actions: [
        { label: "Cancel", class: "ghost", onClick: ({ close }) => close() },
        { label: existing ? "Save" : "Create", onClick: async ({ close }) => {
          const payload = {
            name: name.value.trim(),
            description: description.value,
            tags: tags.value.split(",").map((s) => s.trim()).filter(Boolean),
          };
          if (existing) await API.patch(`/api/datasets/${existing.public_id}`, payload);
          else await API.post("/api/datasets", payload);
          close();
          T(existing ? "Dataset updated" : "Dataset created", "success");
          App.refresh();
        } },
      ],
    });
  }

  /* -- entries ----------------------------------------------------------- */
  async function entries(view, params) {
    state.entries.dataset = (params && params.dataset) || state.entries.dataset || "";
    view.appendChild(head("Entries", "Author, review and improve ChatML samples",
      el("button", { class: "btn", text: "+ New entry", onclick: () => newEntry() })));

    const filters = el("div", { class: "toolbar" });
    const datasetSelect = await datasetOptions(state.entries.dataset);
    datasetSelect.onchange = () => { state.entries.dataset = datasetSelect.value; App.refresh(); };
    const statusSelect = el("select", null,
      ["", "draft", "in_review", "approved", "rejected"].map((s) => el("option", { value: s, text: s || "All statuses", selected: s === state.entries.status })));
    statusSelect.onchange = () => { state.entries.status = statusSelect.value; App.refresh(); };
    const search = el("input", { type: "search", placeholder: "Search entries…", value: state.entries.search });
    search.oninput = debounce(() => { state.entries.search = search.value; App.refresh(); }, 350);
    filters.appendChild(datasetSelect);
    filters.appendChild(statusSelect);
    filters.appendChild(search);
    view.appendChild(filters);

    const query = new URLSearchParams();
    if (state.entries.dataset) query.set("dataset", state.entries.dataset);
    if (state.entries.status) query.set("status", state.entries.status);
    if (state.entries.search) query.set("search", state.entries.search);
    const data = await API.get(`/api/entries?${query.toString()}`);
    state.entries.list = data.items || [];

    const layout = el("div", { class: "grid", style: { gridTemplateColumns: "minmax(260px, 360px) 1fr" } });
    const list = el("div", { class: "chat-list" });
    if (!state.entries.list.length) list.appendChild(el("div", { class: "muted", text: "No entries match." }));
    state.entries.list.forEach((entry) => {
      const preview = (entry.messages.find((m) => m.role === "user") || {}).content || "(no user message)";
      list.appendChild(el("div", {
        class: `chat-item ${state.entries.selected === entry.public_id ? "active" : ""}`,
        onclick: () => { state.entries.selected = entry.public_id; openEntry(entry.public_id, pane); },
      },
        el("div", { style: { display: "flex", gap: "8px", alignItems: "center" } },
          statusBadge(entry.status),
          el("span", { class: "muted tiny", text: `#${entry.position}` }),
          entry.quality !== null && entry.quality !== undefined ? el("span", { class: "pill", text: entry.quality.toFixed(2) }) : null
        ),
        el("div", { style: { marginTop: "6px" }, text: preview.slice(0, 90) })
      ));
    });
    const pane = el("div", { class: "card", style: { minHeight: "420px" } });
    if (state.entries.selected) openEntry(state.entries.selected, pane);
    else pane.appendChild(empty("▦", "Select an entry", "Pick an entry on the left, or create a new one."));
    layout.appendChild(el("div", { class: "card", style: { maxHeight: "70vh", overflow: "auto" } }, list));
    layout.appendChild(pane);
    view.appendChild(layout);
  }

  async function openEntry(ref, pane) {
    UI.clear(pane).appendChild(spinner("Loading entry…"));
    const data = await API.get(`/api/entries/${ref}`);
    const entry = data.entry;
    let messages = entry.messages.map((m) => ({ ...m }));

    const renderMessages = () => {
      const container = el("div", { class: "msg-list" });
      messages.forEach((message, index) => {
        const roleSelect = el("select", null,
          ["system", "user", "assistant", "tool"].map((r) => el("option", { value: r, text: r, selected: r === message.role })));
        roleSelect.onchange = () => { messages[index].role = roleSelect.value; };
        const textarea = el("textarea", { style: { minHeight: "110px" } });
        textarea.value = message.content;
        textarea.oninput = () => { messages[index].content = textarea.value; };
        container.appendChild(el("div", { class: `msg ${message.role}` },
          el("div", { class: "msg-head" },
            roleSelect,
            el("span", { class: "spacer" }),
            el("button", { class: "btn small ghost", text: "↑", title: "Move up", onclick: () => { if (index > 0) { [messages[index - 1], messages[index]] = [messages[index], messages[index - 1]]; renderMessages(); } } }),
            el("button", { class: "btn small ghost", text: "↓", title: "Move down", onclick: () => { if (index < messages.length - 1) { [messages[index + 1], messages[index]] = [messages[index], messages[index + 1]]; renderMessages(); } } }),
            el("button", { class: "btn small ghost", text: "✕", title: "Remove", onclick: () => { messages.splice(index, 1); renderMessages(); } })
          ),
          textarea
        ));
      });
      const holder = pane.querySelector("#messages-holder");
      if (holder) { UI.clear(holder); holder.appendChild(container); }
    };

    const tagsInput = el("input", { type: "text", value: (entry.tags || []).join(", ") });
    const notes = el("textarea", { rows: "2" });
    notes.value = entry.notes || "";
    const statusSelect = el("select", null,
      ["draft", "in_review", "approved", "rejected"].map((s) => el("option", { value: s, text: s, selected: s === entry.status })));

    const header = el("div", { class: "page-head", style: { marginBottom: "12px" } },
      el("h3", { text: `Entry ${entry.public_id}` }),
      statusBadge(entry.status),
      el("span", { class: "spacer" }),
      el("span", { class: "muted tiny", text: `v${entry.version} · updated ${UI.fmtDate(entry.updated_at)}` })
    );

    const actions = el("div", { class: "toolbar" },
      el("button", { class: "btn", text: "Save", onclick: async () => {
        await API.patch(`/api/entries/${entry.public_id}`, {
          messages, tags: tagsInput.value.split(",").map((s) => s.trim()).filter(Boolean),
          notes: notes.value, status: statusSelect.value,
        });
        T("Entry saved", "success");
        App.refresh();
      } }),
      el("button", { class: "btn subtle", text: "✦ Enhance assistant", onclick: () => runAuthoring(entry.public_id, "enhance", { fields: ["assistant"] }) }),
      el("button", { class: "btn subtle", text: "✦ Suggest tags", onclick: () => runAuthoring(entry.public_id, "suggest-tags", {}) }),
      el("button", { class: "btn subtle", text: "✓ Evaluate", onclick: () => runAuthoring(entry.public_id, "evaluate", {}) }),
      el("button", { class: "btn ghost", text: "Grounding", onclick: () => showGrounding(entry.public_id) }),
      el("button", { class: "btn ghost", text: "Collect", onclick: () => addToCollection(entry.public_id) }),
      el("button", { class: "btn ghost", text: "Delete", onclick: async () => {
        if (await UI.modal.confirm({ title: "Delete entry?", confirm: "Delete", danger: true })) {
          await API.del(`/api/entries/${entry.public_id}`);
          state.entries.selected = null; T("Entry deleted", "success"); App.refresh();
        }
      } })
    );

    const validation = data.validation && data.validation.problems.length
      ? el("div", { class: "card", style: { borderColor: "var(--warning)" } },
          el("strong", { text: "Structural issues" }),
          el("ul", null, data.validation.problems.map((p) => el("li", { text: p }))))
      : el("div", { class: "pill ok", text: "Valid ChatML" });

    UI.clear(pane).appendChild(header);
    pane.appendChild(actions);
    pane.appendChild(el("div", { id: "messages-holder" }));
    renderMessages();
    pane.appendChild(el("div", { style: { marginTop: "12px", display: "grid", gap: "12px" } },
      validation,
      el("label", { class: "field" }, el("span", { text: "Tags" }), tagsInput),
      el("label", { class: "field" }, el("span", { text: "Notes" }), notes),
      el("label", { class: "field" }, el("span", { text: "Status" }), statusSelect)
    ));
    if (entry.evaluation) {
      const evaluation = entry.evaluation;
      pane.appendChild(el("div", { class: "card", style: { marginTop: "14px" } },
        el("strong", { text: `Evaluation · ${(evaluation.score * 100).toFixed(0)}%` }),
        el("p", { class: "muted", text: evaluation.summary || "" }),
        el("div", { class: "chips" }, Object.entries(evaluation.dimensions || {}).map(([k, v]) => el("span", { class: "chip", text: `${k}: ${v}` }))),
        evaluation.issues && evaluation.issues.length ? el("ul", null, evaluation.issues.map((i) => el("li", { text: i }))) : null
      ));
    }
  }

  async function runAuthoring(ref, action, body) {
    const job = await API.post(`/api/entries/${ref}/${action}`, body);
    jobToast(job, action);
    App.watchJob(job.id, (result) => {
      if (!result) return;
      if (action === "enhance") {
        const fields = result.fields || {};
        Object.entries(fields).forEach(([role, data]) => {
          T(`Improved ${role}`, "info", data.rationale || "");
        });
        showDiffModal(result);
      } else if (action === "suggest-tags") {
        T("Tag suggestions", "info", (result.tags || []).join(", "));
      } else if (action === "evaluate") {
        T(`Score ${(result.score * 100).toFixed(0)}%`, "success", result.summary || "");
        App.refresh();
      }
    });
  }

  function showDiffModal(result) {
    UI.modal.open({
      title: "Suggested improvements",
      body: el("div", null, Object.entries(result.fields || {}).map(([role, data]) =>
        el("div", { class: "card", style: { marginBottom: "10px" } },
          el("strong", { text: role }),
          el("p", { class: "muted", text: data.rationale || "" }),
          el("pre", { class: "mono", style: { whiteSpace: "pre-wrap" }, text: data.improved || "" }),
          el("div", { class: "chips" }, (data.changes || []).map((c) => el("span", { class: "chip", text: c })))
        )
      )),
      actions: [{ label: "Close", class: "ghost", onClick: ({ close }) => close() }],
    });
  }

  async function addToCollection(entryRef) {
    const data = await API.get("/api/collections");
    const name = el("input", { type: "text", placeholder: "New collection name" });
    const existing = el("select", null, el("option", { value: "", text: "Choose an existing collection…" }));
    (data.items || []).forEach((collection) =>
      existing.appendChild(el("option", {
        value: collection.public_id,
        text: `${collection.name} (${(collection.entry_ids || []).length})`,
      })));
    UI.modal.open({
      title: "Add entry to collection",
      body: el("div", null,
        el("label", { class: "field" }, el("span", { text: "Existing collection" }), existing),
        el("div", { class: "muted", style: { margin: "10px 0" }, text: "or" }),
        el("label", { class: "field" }, el("span", { text: "Create a new collection" }), name)
      ),
      actions: [
        { label: "Cancel", class: "ghost", onClick: ({ close }) => close() },
        { label: "Add", onClick: async ({ close }) => {
          let targetId = existing.value;
          if (!targetId && name.value.trim()) {
            const created = await API.post("/api/collections", { name: name.value.trim() });
            targetId = created.public_id;
          }
          if (!targetId) { T("Pick or name a collection", "warning"); return; }
          await API.post(`/api/collections/${targetId}/entries`, { entries: [entryRef] });
          close(); T("Added to collection", "success");
        } },
      ],
    });
  }

  async function showGrounding(ref) {
    const data = await API.post(`/api/entries/${ref}/grounding`, {});
    UI.modal.open({
      title: "Grounding preview",
      body: el("div", null,
        el("p", { class: "muted", text: `${data.chunks.length} chunks · used RAG: ${data.used_rag} · graph: ${data.used_graph}` }),
        data.chunks.map((chunk, index) => el("div", { class: "card", style: { marginBottom: "8px" } },
          el("strong", { text: `[${index + 1}] ${chunk.document_title} — ${chunk.heading || "chunk"}` }),
          el("p", { text: chunk.text.slice(0, 400) }),
          el("div", { class: "chips" },
            el("span", { class: "chip", text: `fused ${chunk.fused_score.toFixed(4)}` }),
            Object.entries(chunk.ranks || {}).map(([k, v]) => el("span", { class: "chip", text: `${k} #${v}` }))
          )
        ))
      ),
    });
  }

  async function newEntry(datasetRef) {
    const datasetSelect = await datasetOptions(datasetRef || state.entries.dataset);
    const system = el("textarea", { rows: "3", placeholder: "You are a helpful assistant…" });
    const user = el("textarea", { rows: "3", placeholder: "User request" });
    const assistant = el("textarea", { rows: "4", placeholder: "Assistant answer" });
    const generateTopic = el("input", { type: "text", placeholder: "or generate from a topic…" });
    UI.modal.open({
      title: "New entry",
      body: el("div", null,
        el("label", { class: "field" }, el("span", { text: "Dataset" }), datasetSelect),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "System" }), system),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "User" }), user),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "Assistant" }), assistant),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "Generate with LLM (grounded)" }), generateTopic)
      ),
      actions: [
        { label: "Cancel", class: "ghost", onClick: ({ close }) => close() },
        { label: "Generate", class: "subtle", onClick: async ({ close }) => {
          if (!generateTopic.value.trim()) { T("Enter a topic first", "warning"); return; }
          const job = await API.post("/api/entries/generate", { topic: generateTopic.value, dataset: datasetSelect.value, use_grounding: true });
          close();
          jobToast(job, "Generate entry");
          App.watchJob(job.id, () => App.refresh());
        } },
        { label: "Create", onClick: async ({ close }) => {
          const created = await API.post("/api/entries", {
            dataset: datasetSelect.value || null, system: system.value, user: user.value, assistant: assistant.value,
          });
          close(); T("Entry created", "success");
          state.entries.selected = created.public_id;
          App.refresh();
        } },
      ],
    });
  }

  /* -- collections ------------------------------------------------------- */
  async function collections(view) {
    view.appendChild(head("Collections", "Curated, exportable selections of entries",
      el("button", { class: "btn", text: "+ New collection", onclick: () => newCollection() })));
    const data = await API.get("/api/collections");
    state.collections.list = data.items || [];
    if (!state.collections.list.length) {
      view.appendChild(empty("▩", "No collections yet", "Group entries into a collection to export them."));
      return;
    }
    view.appendChild(el("div", { class: "grid cols-3" },
      state.collections.list.map((collection) =>
        el("div", { class: "card" },
          el("h3", { text: collection.name }),
          el("div", { class: "muted", text: collection.description || "No description" }),
          el("div", { class: "meta", style: { marginTop: "8px" } },
            el("span", { text: `${(collection.entry_ids || []).length} entries` }),
            el("span", { text: UI.fmtDate(collection.updated_at) })
          ),
          el("div", { class: "toolbar", style: { marginTop: "12px", marginBottom: "0" } },
            el("button", { class: "btn small", text: "Open", onclick: () => openCollection(collection.public_id) }),
            el("select", { onchange: async (event) => {
              const fmt = event.target.value;
              window.location = `/api/collections/${collection.public_id}/export?format=${fmt}`;
            } },
              [["chatml", "chatml"], ["jsonl", "jsonl"], ["alpaca", "alpaca"], ["sharegpt", "sharegpt"], ["markdown", "markdown"]]
                .map(([value, label]) => el("option", { value, text: `Export ${label}` }))
            ),
            el("button", { class: "btn small ghost", text: "Delete", onclick: async () => {
              if (await UI.modal.confirm({ title: "Delete collection?", confirm: "Delete", danger: true })) {
                await API.del(`/api/collections/${collection.public_id}`);
                T("Collection deleted", "success"); App.refresh();
              }
            } })
          )
        )
      )
    ));
  }

  async function openCollection(ref) {
    const collection = await API.get(`/api/collections/${ref}`);
    const entriesHolder = el("div", { style: { display: "grid", gap: "8px" } });

    const renderEntries = (items) => {
      UI.clear(entriesHolder);
      if (!items.length) {
        entriesHolder.appendChild(el("div", { class: "muted", text: "No entries yet." }));
        return;
      }
      items.forEach((entry) => {
        const preview = (entry.messages.find((m) => m.role === "user") || {}).content || "";
        entriesHolder.appendChild(el("div", { class: "job" },
          statusBadge(entry.status),
          el("div", { style: { flex: "1" }, text: preview.slice(0, 110) || entry.public_id }),
          el("button", { class: "btn small ghost", text: "Remove", onclick: async () => {
            await API.del(`/api/collections/${ref}/entries`, { entries: [entry.public_id] });
            await reload();
          } })
        ));
      });
    };

    const reload = async () => {
      const fresh = await API.get(`/api/collections/${ref}`);
      renderEntries(fresh.entries || []);
    };

    const picker = el("div", { style: { display: "grid", gap: "8px" } });
    const searchInput = el("input", { type: "search", placeholder: "Search entries to add…" });
    const results = el("div", { style: { display: "grid", gap: "6px", maxHeight: "220px", overflow: "auto" } });
    const loadPicker = async () => {
      const query = new URLSearchParams();
      if (searchInput.value.trim()) query.set("search", searchInput.value.trim());
      query.set("limit", "25");
      const data = await API.get(`/api/entries?${query.toString()}`);
      UI.clear(results);
      const existing = new Set(collection.entry_ids || []);
      (data.items || []).filter((entry) => !existing.has(entry.id)).forEach((entry) => {
        const preview = (entry.messages.find((m) => m.role === "user") || {}).content || "";
        results.appendChild(el("div", { class: "job" },
          el("div", { style: { flex: "1" }, text: preview.slice(0, 90) || entry.public_id }),
          el("button", { class: "btn small", text: "Add", onclick: async () => {
            await API.post(`/api/collections/${ref}/entries`, { entries: [entry.public_id] });
            await reload();
            await loadPicker();
          } })
        ));
      });
      if (!results.childNodes.length) results.appendChild(el("div", { class: "muted", text: "Nothing to add." }));
    };
    searchInput.oninput = debounce(loadPicker, 300);
    picker.appendChild(searchInput);
    picker.appendChild(results);

    UI.modal.open({
      title: collection.name,
      body: el("div", null,
        el("p", { class: "muted", text: collection.description || "No description" }),
        el("div", { class: "section-title", text: "Entries" }),
        entriesHolder,
        el("div", { class: "section-title", text: "Add entries" }),
        picker,
        el("div", { class: "section-title", text: "Export" }),
        el("div", { class: "toolbar" },
          ["chatml", "jsonl", "alpaca", "sharegpt", "markdown"].map((fmt) =>
            el("button", { class: "btn small ghost", text: fmt, onclick: () => {
              window.location = `/api/collections/${ref}/export?format=${fmt}`;
            } }))
        )
      ),
      actions: [{ label: "Close", class: "ghost", onClick: ({ close }) => close() }],
      onMount: () => { renderEntries(collection.entries || []); loadPicker(); },
    });
  }

  async function newCollection() {
    const name = el("input", { type: "text", placeholder: "Collection name" });
    const description = el("textarea", { rows: "2" });
    UI.modal.open({
      title: "New collection",
      body: el("div", null,
        el("label", { class: "field" }, el("span", { text: "Name" }), name),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "Description" }), description)
      ),
      actions: [
        { label: "Cancel", class: "ghost", onClick: ({ close }) => close() },
        { label: "Create", onClick: async ({ close }) => {
          await API.post("/api/collections", { name: name.value, description: description.value });
          close(); T("Collection created", "success"); App.refresh();
        } },
      ],
    });
  }

  /* -- documents --------------------------------------------------------- */
  async function documents(view) {
    view.appendChild(head("Documents", "Import sources for RAG + graph grounding"));
    const dropzone = el("div", { class: "card", style: { textAlign: "center", borderStyle: "dashed", cursor: "pointer" } },
      el("div", { class: "big", style: { fontSize: "30px", opacity: "0.5" }, text: "⇪" }),
      el("div", { text: "Drop PDF, DOCX, TXT, Markdown or LaTeX files here" }),
      el("div", { class: "muted tiny", text: "or click to browse" })
    );
    const fileInput = el("input", { type: "file", multiple: true, style: { display: "none" } });
    const send = async (files) => {
      if (!files || !files.length) return;
      const job = await API.upload("/api/documents", files, { index: "true" });
      jobToast(job, "Import documents");
      App.watchJob(job.id, () => App.refresh());
    };
    dropzone.onclick = () => fileInput.click();
    fileInput.onchange = () => send(fileInput.files);
    dropzone.addEventListener("dragover", (event) => { event.preventDefault(); dropzone.style.borderColor = "var(--accent)"; });
    dropzone.addEventListener("dragleave", () => { dropzone.style.borderColor = ""; });
    dropzone.addEventListener("drop", (event) => {
      event.preventDefault(); dropzone.style.borderColor = "";
      send(event.dataTransfer.files);
    });
    view.appendChild(dropzone);
    view.appendChild(fileInput);

    view.appendChild(el("div", { class: "toolbar", style: { marginTop: "16px" } },
      el("button", { class: "btn ghost", text: "Reindex all", onclick: async () => {
        const job = await API.post("/api/documents/reindex", { graph: true });
        jobToast(job, "Reindex");
      } }),
      el("button", { class: "btn ghost", text: "+ New markdown note", onclick: () => newNote() })
    ));

    const data = await API.get("/api/documents");
    state.documents.list = data.items || [];
    if (!state.documents.list.length) {
      view.appendChild(empty("▣", "No documents yet", "Import a document to give the LLM something to ground on."));
      return;
    }
    const table = el("table", { class: "data" },
      el("thead", null, el("tr", null,
        el("th", { text: "Title" }), el("th", { text: "Kind" }), el("th", { text: "Status" }),
        el("th", { text: "Chunks" }), el("th", { text: "Size" }), el("th", { text: "Updated" }), el("th", { text: "" })
      )),
      el("tbody", null, state.documents.list.map((document) =>
        el("tr", null,
          el("td", { text: document.title }),
          el("td", { text: document.kind }),
          el("td", null, el("span", { class: `badge ${document.status === "ready" ? "approved" : "draft"}`, text: document.status })),
          el("td", { text: String(document.chunk_count) }),
          el("td", { text: UI.fmtBytes(document.size_bytes) }),
          el("td", { text: UI.fmtDate(document.updated_at) }),
          el("td", null,
            el("button", { class: "btn small ghost", text: "Open", onclick: () => openDocument(document.public_id) })
          )
        )
      ))
    );
    view.appendChild(el("div", { class: "card", style: { padding: "0", overflow: "auto" } }, table));
  }

  async function newNote() {
    const title = el("input", { type: "text", placeholder: "Note title" });
    const markdown = el("textarea", { rows: "10", placeholder: "# Markdown\n\nContent…" });
    UI.modal.open({
      title: "New markdown note",
      body: el("div", null,
        el("label", { class: "field" }, el("span", { text: "Title" }), title),
        el("label", { class: "field", style: { marginTop: "10px" } }, el("span", { text: "Markdown" }), markdown)
      ),
      actions: [
        { label: "Cancel", class: "ghost", onClick: ({ close }) => close() },
        { label: "Create & index", onClick: async ({ close }) => {
          const result = await API.post("/api/documents", { title: title.value || "Note", markdown: markdown.value, index: true });
          close(); T("Note created", "success");
          if (result.job) App.trackJob(result.job.id);
          App.refresh();
        } },
      ],
    });
  }

  function mdToolbar(editor) {
    const wrap = (before, after, placeholder) => () => {
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      const value = editor.value;
      const selected = value.slice(start, end) || placeholder || "";
      editor.value = value.slice(0, start) + before + selected + after + value.slice(end);
      editor.focus();
      editor.selectionStart = start + before.length;
      editor.selectionEnd = start + before.length + selected.length;
      editor.dispatchEvent(new Event("input"));
    };
    const line = (prefix) => () => {
      const start = editor.selectionStart;
      const value = editor.value;
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      editor.value = value.slice(0, lineStart) + prefix + value.slice(lineStart);
      editor.focus();
      editor.dispatchEvent(new Event("input"));
    };
    return el("div", { class: "toolbar", style: { marginBottom: "8px" } },
      el("button", { class: "btn small ghost", text: "B", title: "Bold", onclick: wrap("**", "**", "bold") }),
      el("button", { class: "btn small ghost", text: "I", title: "Italic", onclick: wrap("*", "*", "italic") }),
      el("button", { class: "btn small ghost", text: "H2", title: "Heading", onclick: line("## ") }),
      el("button", { class: "btn small ghost", text: "•", title: "List", onclick: line("- ") }),
      el("button", { class: "btn small ghost", text: "❝", title: "Quote", onclick: line("> ") }),
      el("button", { class: "btn small ghost", text: "‹›", title: "Inline code", onclick: wrap("`", "`", "code") }),
      el("button", { class: "btn small ghost", text: "```", title: "Code block", onclick: wrap("\n```\n", "\n```\n", "code") }),
      el("button", { class: "btn small ghost", text: "🔗", title: "Link", onclick: wrap("[", "](https://)", "label") })
    );
  }

  async function openDocument(ref) {
    const document = await API.get(`/api/documents/${ref}`);
    const editor = el("textarea", { rows: "22", style: { minHeight: "420px" } });
    editor.value = document.markdown || "";
    const preview = el("div", { class: "md-preview", html: UI.markdown(document.markdown || "") });
    editor.oninput = () => { preview.innerHTML = UI.markdown(editor.value); };
    UI.modal.open({
      title: document.title,
      body: el("div", null,
        el("div", { class: "toolbar" },
          el("span", { class: `badge ${document.status === "ready" ? "approved" : "draft"}`, text: document.status }),
          el("span", { class: "pill", text: `${document.chunk_count} chunks` }),
          el("span", { class: "pill", text: document.kind }),
          el("span", { class: "spacer" }),
          el("button", { class: "btn small ghost", text: "Clean with LLM", onclick: async () => {
            const job = await API.post(`/api/documents/${document.public_id}/clean`, {});
            jobToast(job, "Clean markdown");
            App.watchJob(job.id, () => T("Markdown cleaned", "success"));
          } }),
          el("button", { class: "btn small ghost", text: "Enrich graph", onclick: async () => {
            const job = await API.post(`/api/documents/${document.public_id}/enrich-graph`, {});
            jobToast(job, "Enrich graph");
          } }),
          el("button", { class: "btn small ghost", text: "Reindex", onclick: async () => {
            const job = await API.post(`/api/documents/${document.public_id}/index`, {});
            jobToast(job, "Index document");
          } })
        ),
        mdToolbar(editor),
        el("div", { class: "md-editor" }, editor, preview)
      ),
      actions: [
        { label: "Delete", class: "danger", onClick: async ({ close }) => {
          if (await UI.modal.confirm({ title: "Delete document?", confirm: "Delete", danger: true })) {
            await API.del(`/api/documents/${document.public_id}`); close(); T("Document deleted", "success"); App.refresh();
          }
        } },
        { label: "Save", onClick: async ({ close }) => {
          await API.put(`/api/documents/${document.public_id}/markdown`, { markdown: editor.value, reindex: true });
          close(); T("Markdown saved & reindexed", "success");
        } },
      ],
    });
  }

  /* -- chat -------------------------------------------------------------- */
  async function chat(view) {
    view.appendChild(head("Chat", "Talk to the model with optional grounding"));
    const layout = el("div", { class: "chat-layout" });
    const listCard = el("div", { class: "card" },
      el("button", { class: "btn", style: { width: "100%" }, text: "+ New conversation", onclick: async () => {
        const created = await API.post("/api/chat/conversations", { title: "New conversation" });
        state.chat.selected = created.public_id; App.refresh();
      } }),
      el("div", { class: "chat-list", id: "chat-list", style: { marginTop: "12px" } })
    );
    const pane = el("div", { class: "card chat-pane", id: "chat-pane" });
    layout.appendChild(listCard);
    layout.appendChild(pane);
    view.appendChild(layout);

    const data = await API.get("/api/chat/conversations");
    state.chat.list = data.items || [];
    const list = view.querySelector("#chat-list");
    if (!state.chat.list.length) list.appendChild(el("div", { class: "muted", text: "No conversations." }));
    state.chat.list.forEach((item) => {
      list.appendChild(el("div", {
        class: `chat-item ${state.chat.selected === item.conversation.public_id ? "active" : ""}`,
        onclick: () => { state.chat.selected = item.conversation.public_id; App.refresh(); },
      },
        el("div", { text: item.conversation.title }),
        el("div", { class: "muted tiny", text: `${item.message_count} messages` })
      ));
    });
    if (state.chat.selected) openChat(state.chat.selected, pane);
    else pane.appendChild(empty("✦", "Start a conversation", "Create a conversation to chat with your model."));
  }

  async function openChat(ref, pane) {
    const conversation = await API.get(`/api/chat/conversations/${ref}`);
    const scroll = el("div", { class: "chat-scroll", id: "chat-scroll" });
    (conversation.messages || []).forEach((message) => scroll.appendChild(bubble(message)));

    const toggles = el("div", { class: "toolbar" },
      toggle("RAG", conversation.use_rag, (v) => API.patch(`/api/chat/conversations/${ref}`, { use_rag: v })),
      toggle("Graph", conversation.use_graph, (v) => API.patch(`/api/chat/conversations/${ref}`, { use_graph: v })),
      toggle("Grounding", conversation.use_grounding, (v) => API.patch(`/api/chat/conversations/${ref}`, { use_grounding: v }))
    );

    const systemPrompt = el("textarea", { rows: "2", placeholder: "System prompt (optional)" });
    systemPrompt.value = conversation.system_prompt || "";
    systemPrompt.onchange = () => API.patch(`/api/chat/conversations/${ref}`, { system_prompt: systemPrompt.value });

    const input = el("textarea", { rows: "2", placeholder: "Message MiniCS…" });
    const sendBtn = el("button", { class: "btn", text: "Send" });
    const stopBtn = el("button", { class: "btn ghost hidden", text: "Stop" });

    const send = async () => {
      const content = input.value.trim();
      if (!content) return;
      input.value = "";
      scroll.appendChild(bubble({ role: "user", content }));
      const reply = bubble({ role: "assistant", content: "" });
      scroll.appendChild(reply);
      scroll.scrollTop = scroll.scrollHeight;
      sendBtn.disabled = true; stopBtn.classList.remove("hidden");
      const controller = new AbortController();
      state.chat.controller = controller;
      let citations = [];
      try {
        await API.stream(`/api/chat/conversations/${ref}/stream`, { content }, (event) => {
          if (event.type === "retrieval" && event.retrieval) {
            citations = event.retrieval.citations || [];
            reply.dataset.grounding = event.grounding ? "1" : "0";
          } else if (event.type === "token") {
            reply.body.textContent += event.text;
            scroll.scrollTop = scroll.scrollHeight;
          } else if (event.type === "error") {
            T("Chat error", "error", event.error);
          } else if (event.type === "done") {
            if (citations.length) renderCitations(reply, citations);
          }
        }, controller.signal);
      } catch (error) {
        if (error.name !== "AbortError") T("Chat failed", "error", error.message);
      } finally {
        sendBtn.disabled = false; stopBtn.classList.add("hidden");
        state.chat.controller = null;
      }
    };
    sendBtn.onclick = send;
    stopBtn.onclick = () => state.chat.controller && state.chat.controller.abort();
    input.onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } };

    UI.clear(pane);
    pane.appendChild(el("div", { class: "page-head", style: { marginBottom: "8px" } },
      el("h3", { text: conversation.title }),
      el("span", { class: "spacer" }),
      el("button", { class: "btn small ghost", text: "Clear", onclick: async () => {
        await API.del(`/api/chat/conversations/${ref}/messages`); App.refresh();
      } })
    ));
    pane.appendChild(toggles);
    pane.appendChild(systemPrompt);
    pane.appendChild(scroll);
    pane.appendChild(el("div", { class: "composer" }, input, el("div", { style: { display: "flex", gap: "6px" } }, sendBtn, stopBtn)));
    scroll.scrollTop = scroll.scrollHeight;
  }

  function toggle(label, checked, onChange) {
    const input = el("input", { type: "checkbox", checked });
    input.onchange = () => onChange(input.checked);
    return el("label", { class: "switch" }, input, el("span", { text: label }));
  }

  function bubble(message) {
    const body = el("div", null);
    if (message.role === "assistant") body.innerHTML = UI.markdown(message.content || "");
    else body.textContent = message.content || "";
    const node = el("div", { class: `bubble ${message.role === "assistant" ? "assistant" : "user"}` }, body);
    node.body = body;
    if (message.citations && message.citations.length) renderCitations(node, message.citations);
    return node;
  }

  function renderCitations(node, citations) {
    const holder = el("div", { class: "cites" });
    citations.forEach((citation, index) => {
      holder.appendChild(el("div", { class: "cite" },
        el("strong", { text: `[${index + 1}] ${citation.title || citation.ref}` }),
        el("div", { class: "muted", text: (citation.snippet || "").slice(0, 160) })
      ));
    });
    node.appendChild(holder);
  }

  /* -- graph ------------------------------------------------------------- */
  async function graph(view) {
    view.appendChild(head("Graph", "Entity topology extracted from your documents",
      el("button", { class: "btn ghost", text: "Rebuild", onclick: async () => {
        const job = await API.post("/api/graph/rebuild", {});
        jobToast(job, "Rebuild graph");
      } })));
    const status = await API.get("/api/retrieval/status");
    const stats = status.graph || {};
    view.appendChild(el("div", { class: "grid cols-4" },
      Object.entries(stats).map(([key, value]) =>
        el("div", { class: "card" }, el("div", { class: "stat-value", text: String(value) }), el("div", { class: "muted", text: key }))
      )
    ));
    const query = el("input", { type: "search", placeholder: "Entities to explore (e.g. RRF graph)", value: state.graph.query });
    query.onkeydown = (event) => { if (event.key === "Enter") drawGraph(query.value, canvas); };
    view.appendChild(el("div", { class: "toolbar", style: { marginTop: "16px" } }, query,
      el("button", { class: "btn", text: "Explore", onclick: () => drawGraph(query.value, canvas) })));
    const canvas = el("div", { class: "graph-canvas", id: "graph-canvas" });
    view.appendChild(canvas);
    drawGraph(state.graph.query || "", canvas);
  }

  async function drawGraph(query, canvas) {
    state.graph.query = query;
    UI.clear(canvas);
    if (!query.trim()) {
      canvas.appendChild(empty("◈", "Explore the graph", "Type a term to see related entities."));
      return;
    }
    const data = await API.get(`/api/graph/subgraph?q=${encodeURIComponent(query)}`);
    if (!data.nodes.length) { canvas.appendChild(empty("◈", "No matching entities")); return; }
    const width = canvas.clientWidth || 800;
    const height = 520;
    const radius = Math.min(width, height) / 2 - 60;
    const cx = width / 2, cy = height / 2;
    const positions = {};
    data.nodes.forEach((node, index) => {
      const angle = (index / data.nodes.length) * Math.PI * 2;
      positions[node.id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
    });
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", width); svg.setAttribute("height", height);
    (data.edges || []).forEach((edge) => {
      const a = positions[edge.source], b = positions[edge.target];
      if (!a || !b) return;
      const line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
      line.setAttribute("stroke", "var(--border)");
      line.setAttribute("stroke-width", "1.5");
      svg.appendChild(line);
    });
    data.nodes.forEach((node) => {
      const position = positions[node.id];
      const group = document.createElementNS(svgNS, "g");
      group.setAttribute("class", "graph-node");
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", position.x); circle.setAttribute("cy", position.y);
      circle.setAttribute("r", 8 + Math.min(14, (node.weight || 1) * 1.5));
      circle.setAttribute("fill", "var(--accent)");
      circle.setAttribute("opacity", "0.85");
      const label = document.createElementNS(svgNS, "text");
      label.setAttribute("x", position.x + 14); label.setAttribute("y", position.y + 4);
      label.textContent = node.label;
      group.appendChild(circle); group.appendChild(label);
      svg.appendChild(group);
    });
    canvas.appendChild(svg);
  }

  /* -- jobs -------------------------------------------------------------- */
  async function jobs(view) {
    view.appendChild(head("Activity", "Background jobs and live progress",
      el("button", { class: "btn ghost", text: "Cancel all", onclick: () => API.post("/api/jobs/cancel-all", {}) })));
    const data = await API.get("/api/jobs");
    const list = el("div", { class: "grid", id: "job-list" });
    if (!data.items.length) list.appendChild(empty("⟳", "Nothing running", "Long operations appear here with live progress."));
    data.items.slice().reverse().forEach((job) => list.appendChild(jobRow(job)));
    view.appendChild(list);
    view.appendChild(el("div", { class: "section-title", text: "Event log" }));
    const history = await API.get("/api/events/history?limit=60");
    const log = el("div", { class: "card", style: { maxHeight: "340px", overflow: "auto" } });
    history.items.slice().reverse().forEach((event) => {
      log.appendChild(el("div", { class: "muted tiny", text: `[${UI.fmtDate(event.ts)}] ${event.type}: ${event.message || ""}` }));
    });
    view.appendChild(log);
  }

  function jobRow(job) {
    const bar = el("span", { style: { width: `${Math.round((job.progress || 0) * 100)}%` } });
    const label = el("span", { class: "muted tiny", text: job.message || "" });
    return el("div", { class: `job ${job.status}`, id: `job-${job.id}` },
      el("span", { class: `pill ${job.status === "error" ? "err" : job.status === "success" ? "ok" : job.status === "running" ? "warn" : ""}`, text: job.status }),
      el("div", { style: { flex: "1", minWidth: "160px" } },
        el("div", { text: job.name }),
        el("div", { class: "bar" }, bar),
        label
      ),
      el("span", { class: "muted tiny", text: UI.fmtDuration(job.duration) }),
      job.status === "running" || job.status === "queued"
        ? el("button", { class: "btn small ghost", text: "Cancel", onclick: () => API.post(`/api/jobs/${job.id}/cancel`, {}) })
        : null
    );
  }

  /* -- settings ---------------------------------------------------------- */
  async function settings(view) {
    const config = await API.get("/api/config");
    state.settings.config = config;
    view.appendChild(head("Settings", "Endpoints, retrieval defaults and appearance"));
    if (config.missing_requirements.length) {
      view.appendChild(el("div", { class: "card", style: { borderColor: "var(--warning)" } },
        el("strong", { text: "Setup required" }),
        el("div", { class: "muted", text: `Missing: ${config.missing_requirements.join(", ")}` })
      ));
    }

    const llm = config.llm;
    const emb = config.embedding;
    const app = config.app;
    const retrieval = config.retrieval;

    const field = (label, input, hint) => el("label", { class: "field" },
      el("span", { text: label }), input, hint ? el("small", { class: "muted", text: hint }) : null);

    const baseUrl = el("input", { type: "text", value: llm.base_url, placeholder: "https://api.openai.com/v1" });
    const apiKey = el("input", { type: "password", value: llm.api_key, placeholder: "sk-…" });
    const modelInput = el("input", { type: "text", value: llm.model, placeholder: "gpt-4o-mini" });
    const modelSelect = el("select", null, el("option", { value: "", text: "Load models to choose…" }));
    modelSelect.onchange = () => { if (modelSelect.value) modelInput.value = modelSelect.value; };
    const temperature = el("input", { type: "number", step: "0.1", min: "0", max: "2", value: llm.temperature });
    const maxTokens = el("input", { type: "number", min: "1", value: llm.max_tokens });

    const embBaseUrl = el("input", { type: "text", value: emb.base_url, placeholder: "same as LLM by default" });
    const embApiKey = el("input", { type: "password", value: emb.api_key });
    const embModel = el("input", { type: "text", value: emb.model, placeholder: "text-embedding-3-small" });
    const embModelSelect = el("select", null, el("option", { value: "", text: "Load models to choose…" }));
    embModelSelect.onchange = () => { if (embModelSelect.value) embModel.value = embModelSelect.value; };
    const dimension = el("input", { type: "number", min: "0", value: emb.dimension });
    const chunkSize = el("input", { type: "number", min: "100", value: emb.chunk_size });
    const chunkOverlap = el("input", { type: "number", min: "0", value: emb.chunk_overlap });

    const topK = el("input", { type: "number", min: "1", value: retrieval.top_k });
    const rrfK = el("input", { type: "number", min: "1", value: retrieval.rrf_k });
    const graphHops = el("input", { type: "number", min: "1", max: "3", value: retrieval.graph_hops });
    const useRag = el("input", { type: "checkbox", checked: retrieval.use_rag });
    const useGraph = el("input", { type: "checkbox", checked: retrieval.use_graph });
    const useGrounding = el("input", { type: "checkbox", checked: retrieval.use_grounding });

    const themeSelect = el("select");
    themeSelect.appendChild(UI.themeOptions(app.theme));
    const workers = el("input", { type: "number", min: "1", max: "32", value: app.max_workers });
    const cleanImports = el("input", { type: "checkbox", checked: app.clean_imports_with_llm });

    const reportBox = el("div", { class: "muted" });

    const loadModels = async (kind) => {
      const target = kind === "embedding" ? embModelSelect : modelSelect;
      const url = (kind === "embedding" ? embBaseUrl.value : baseUrl.value).trim();
      const key = kind === "embedding" ? embApiKey.value : apiKey.value;
      const query = new URLSearchParams({ kind });
      if (url) query.set("base_url", url);
      if (key && key !== "********") query.set("api_key", key);
      UI.clear(target).appendChild(el("option", { value: "", text: "Loading…" }));
      try {
        const models = await API.get(`/api/config/models?${query.toString()}`);
        const list = models[kind] || [];
        UI.clear(target).appendChild(el("option", { value: "", text: "Choose a model…" }));
        list.forEach((id) => target.appendChild(el("option", { value: id, text: id })));
        if (!list.length) {
          UI.clear(target).appendChild(el("option", { value: "", text: "None returned — type manually" }));
          T("No models returned", "warning", `Check the ${kind} base URL`);
        }
      } catch (error) {
        UI.clear(target).appendChild(el("option", { value: "", text: "Unavailable — type manually" }));
        T("Could not load models", "warning", error.message);
      }
    };

    const detectDimension = async () => {
      await save(false);
      try {
        const result = await API.post("/api/config/embedding-dimension", {});
        dimension.value = result.dimension;
        T(`Embedding dimension detected: ${result.dimension}`, "success");
      } catch (error) { T("Detection failed", "error", error.message); }
    };

    async function save(showToast) {
      const payload = {
        llm: {
          base_url: baseUrl.value, api_key: apiKey.value, model: modelInput.value,
          temperature: Number(temperature.value), max_tokens: Number(maxTokens.value),
        },
        embedding: {
          base_url: embBaseUrl.value, api_key: embApiKey.value, model: embModel.value,
          dimension: Number(dimension.value), chunk_size: Number(chunkSize.value), chunk_overlap: Number(chunkOverlap.value),
        },
        retrieval: {
          top_k: Number(topK.value), rrf_k: Number(rrfK.value), graph_hops: Number(graphHops.value),
          use_rag: useRag.checked, use_graph: useGraph.checked, use_grounding: useGrounding.checked,
        },
        app: { theme: themeSelect.value, max_workers: Number(workers.value), clean_imports_with_llm: cleanImports.checked },
      };
      const updated = await API.put("/api/config", payload);
      state.settings.config = updated;
      UI.applyTheme(themeSelect.value);
      if (showToast !== false) T("Settings saved", "success");
      return updated;
    }

    const testConnection = async () => {
      await save(false);
      reportBox.textContent = "Testing…";
      try {
        const report = await API.post("/api/config/test", {});
        const chatText = report.chat.error || report.chat.model || "";
        const embText = report.embedding.error
          || `${report.embedding.model} (${report.embedding.dimension}d)`;
        UI.clear(reportBox);
        reportBox.appendChild(
          el("div", { style: { display: "grid", gap: "6px" } },
            el("div", null,
              el("span", { class: `pill ${report.chat.ok ? "ok" : "err"}`, text: report.chat.ok ? "chat ok" : "chat failed" }),
              el("span", { class: "muted", text: " " + chatText })
            ),
            el("div", null,
              el("span", { class: `pill ${report.embedding.ok ? "ok" : "err"}`, text: report.embedding.ok ? "embeddings ok" : "embeddings failed" }),
              el("span", { class: "muted", text: " " + embText })
            )
          )
        );
        if (report.embedding.ok && report.embedding.dimension) dimension.value = report.embedding.dimension;
      } catch (error) {
        reportBox.textContent = error.message;
      }
    };

    const card = (title, nodes) => el("div", { class: "card" }, el("h3", { text: title }), el("div", { style: { display: "grid", gap: "12px", marginTop: "12px" } }, nodes));

    view.appendChild(el("div", { class: "grid cols-2" },
      card("LLM endpoint (OpenAI-compatible)", [
        field("Base URL", baseUrl),
        field("API key", apiKey),
        el("div", { style: { display: "flex", gap: "8px" } },
          el("div", { style: { flex: "1" } }, field("Model", modelInput)),
          el("button", { class: "btn ghost small", style: { alignSelf: "end" }, text: "Load", onclick: () => loadModels("chat") })),
        field("Pick from endpoint", modelSelect),
        el("div", { style: { display: "flex", gap: "12px" } },
          el("div", { style: { flex: "1" } }, field("Temperature", temperature)),
          el("div", { style: { flex: "1" } }, field("Max tokens", maxTokens))),
      ]),
      card("Embeddings endpoint", [
        field("Base URL", embBaseUrl, "leave empty to reuse the LLM base URL"),
        field("API key", embApiKey),
        el("div", { style: { display: "flex", gap: "8px" } },
          el("div", { style: { flex: "1" } }, field("Model", embModel)),
          el("button", { class: "btn ghost small", style: { alignSelf: "end" }, text: "Load", onclick: () => loadModels("embedding") })),
        field("Pick from endpoint", embModelSelect),
        el("div", { style: { display: "flex", gap: "8px", alignItems: "end" } },
          el("div", { style: { flex: "1" } }, field("Dimension", dimension, "required — drives the vector store")),
          el("button", { class: "btn ghost small", text: "Detect", onclick: detectDimension })),
        el("div", { style: { display: "flex", gap: "12px" } },
          el("div", { style: { flex: "1" } }, field("Chunk size", chunkSize)),
          el("div", { style: { flex: "1" } }, field("Chunk overlap", chunkOverlap))),
      ]),
      card("Retrieval", [
        el("div", { style: { display: "flex", gap: "12px" } },
          el("div", { style: { flex: "1" } }, field("Top K", topK)),
          el("div", { style: { flex: "1" } }, field("RRF k", rrfK)),
          el("div", { style: { flex: "1" } }, field("Graph hops", graphHops))),
        el("label", { class: "switch" }, useRag, el("span", { text: "Use vector (RAG) by default" })),
        el("label", { class: "switch" }, useGraph, el("span", { text: "Use graph retrieval by default" })),
        el("label", { class: "switch" }, useGrounding, el("span", { text: "Inject grounding into prompts by default" })),
      ]),
      card("Application", [
        field("Theme", themeSelect),
        field("Background workers", workers),
        el("label", { class: "switch" }, cleanImports, el("span", { text: "Clean imported markdown with the LLM" })),
      ])
    ));

    const footer = el("div", { class: "toolbar", style: { marginTop: "18px" } },
      el("button", { class: "btn", text: "Save settings", onclick: () => save(true) }),
      el("button", { class: "btn subtle", text: "Test connection", onclick: testConnection }),
      el("button", { class: "btn ghost", text: "Finish setup", onclick: async () => {
        await save(false);
        const result = await API.post("/api/config/setup", {});
        T(result.report.ok ? "Setup complete" : "Setup saved with problems", result.report.ok ? "success" : "warning");
        reportBox.textContent = result.report.ok ? "All good." : "Check the endpoint settings.";
      } })
    );
    view.appendChild(footer);
    view.appendChild(reportBox);
  }

  function debounce(fn, wait) {
    let timer = null;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  /* -- about --------------------------------------------------------------- */
  async function about(view) {
    const info = await API.get("/api/about");
    view.appendChild(head("About", "Project info, links and feedback"));

    view.appendChild(el("div", { class: "card about-card" },
      el("div", { style: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" } },
        el("strong", { text: info.app }),
        el("span", { class: "pill warn", text: info.stage }),
        el("span", { class: "pill", text: `v${info.version}` })
      ),
      el("div", { class: "muted", style: { marginTop: "8px" }, text:
        "MiniCS is a mixed project combining ChatML Studio (datasets and entries) and Tyness (a tiny documental harness for LLM capabilities with embed databases). " +
        "The application is still in early phases: expect rough edges, and please report anything you find." })
    ));

    const openLink = (url) => API.post("/api/about/open", { url });

    const linkRow = (label, hint, url, cta) => el("div", { class: "card about-link" },
      el("div", { style: { flex: "1", minWidth: "200px" } },
        el("div", { text: label }),
        el("div", { class: "muted tiny", text: hint })
      ),
      el("button", { class: "btn small", text: cta, onclick: () => openLink(url).catch((e) => UI.toast("Could not open link", "error", e.message)) })
    );

    view.appendChild(el("div", { class: "section-title", text: "Links" }));
    const links = el("div", { class: "grid" });
    links.appendChild(linkRow("GitHub repository", "Source code, releases and README", info.repo, "Open repo"));
    links.appendChild(linkRow("Documentation", "Guides, API reference and architecture", info.docs, "Open docs"));
    links.appendChild(linkRow("Author on GitHub", "github.com/jasonjimnz", info.author_github, "Open profile"));
    links.appendChild(linkRow("Author on X", "x.com/cangri2k5", info.author_x, "Open X"));
    view.appendChild(links);

    view.appendChild(el("div", { class: "section-title", text: "Feedback" }));
    view.appendChild(el("div", { class: "card" },
      el("div", { text: "Suggestions, bugs and feature requests go through GitHub issues." }),
      el("div", { class: "muted", style: { marginTop: "4px" }, text:
        "Opening an issue keeps everything in one place and helps track what lands in the next release. " +
        "Everything here is free and open — no telemetry, no accounts." }),
      el("div", { style: { marginTop: "10px", display: "flex", gap: "8px", flexWrap: "wrap" } },
        el("button", { class: "btn", text: "Open an issue", onclick: () => openLink(info.new_issue).catch((e) => UI.toast("Could not open link", "error", e.message)) }),
        el("button", { class: "btn ghost", text: "Browse existing issues", onclick: () => openLink(info.issues).catch((e) => UI.toast("Could not open link", "error", e.message)) })
      )
    ));
  }

  window.Views = { dashboard, datasets, entries, collections, documents, chat, graph, jobs, settings, about };
})();
