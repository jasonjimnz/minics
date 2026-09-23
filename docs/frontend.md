# Frontend

The MiniCS UI is a **no-build single-page application** served from
`minics/server/static/` and rendered by `templates/index.html`. There is no
framework, no bundler and no `node_modules` — plain ES2020 JavaScript in four
IIFE modules, one stylesheet, and browser-native `fetch`, `EventSource`,
`ReadableStream` and CSS custom properties.

```
templates/index.html      shell: sidebar, topbar, view container, modal, toasts
static/css/app.css        theme system + all component styles
static/js/api.js          fetch wrapper, upload, SSE parsing, EventSource
static/js/ui.js           DOM helpers, markdown renderer, toasts, modal, themes
static/js/views.js        the nine views (≈1200 lines)
static/js/app.js          hash router, event wiring, job tracking, health poll
```

Load order in `index.html` matters: `api.js` → `ui.js` → `views.js` →
`app.js`. A single inline script injects `window.MINICS = {version, config}`
(Jinja-rendered from `Config.public_dict()`), and every asset URL carries
`?v={{ version }}` for cache busting.

---

## 1. The shell (`templates/index.html`)

- **Sidebar**: brand, the nine nav buttons (`data-route` attributes), the
  theme picker, and a status line showing the home path.
- **Topbar**: menu toggle (mobile), a global search box, the **ready/setup
  pill** and a Refresh button.
- **`<section id="view">`**: the router target.
- **`#toasts`** and **`#modal-root`**: overlay layers used by every view.

## 2. `api.js` — the HTTP client

- `API.get/post/put/patch/del(path, json)` — JSON requests through `request()`.
- `API.upload(path, files, fields)` — multipart `FormData` upload (used by the
  document dropzone).
- `handle(response)` unwraps the `{ok, data}` envelope, throwing
  `Error(body.error)` with `.status` and `.body` attached on failure.
- `API.stream(path, body, onEvent, signal)` — POST + `response.body`
  `.getReader()`, buffering chunks, splitting on `\n\n` frames and handing
  parsed SSE events to `onEvent`. An `AbortSignal` powers the chat **Stop**
  button.
- `API.events(onEvent, afterId)` — `EventSource` on `/api/events?after=<id>`;
  the browser auto-reconnects and replays missed events from the bus history.

## 3. `ui.js` — the toolkit

- **`UI.el(tag, attrs, ...children)`** — hyperscript-style element builder
  (`class`, `text`, `html`, `dataset`, `style` objects, `on*` listeners,
  boolean attributes). All views are built with it; `UI.clear(node)` empties a
  container.
- **Markdown renderer** (`UI.markdown`) — a small line-based renderer:
  fenced code blocks, `#`–`######` headings, ordered/unordered lists,
  blockquotes, pipe tables, paragraphs; inline `code`, **bold**, *italic*,
  links. Input is HTML-escaped first (`UI.escapeHtml`), so model output is
  rendered safely. Used for assistant bubbles and the document preview.
- **Toasts** — `UI.toast(message, level, detail?, timeout?)`, levels styled
  per theme; auto-dismisses with a fade.
- **Modal** — `UI.modal.open({title, body, actions, onMount})` (Esc/backdrop
  close) and `UI.modal.confirm({...})` returning a Promise — the standard
  delete/confirm flow.
- **Formatters** — `fmtDate`, `fmtBytes`, `fmtDuration`.
- **Themes** — `UI.applyTheme` sets `data-theme` on `<html>` and persists the
  choice in `localStorage`; `UI.themeOptions(selected)` builds a grouped
  (Light / Dark optgroup) picker shared by the sidebar and the Settings view;
  `UI.initThemes` wires the sidebar select from the `UI.THEMES` list
  (`[id, label, kind]` entries).

## 4. `app.js` — routing & lifecycle

- **Hash router**: `#/route?query` with nine routes — `dashboard`, `datasets`,
  `entries`, `collections`, `documents`, `chat`, `graph`, `jobs`, `settings`.
  `hashchange` re-renders; unknown routes fall back to the dashboard.
- **`render()`** highlights the active nav item, shows a loading state, then
  delegates to `window.Views[route](view, params)`.
- **Job tracking**: `App.watchJob(id, callback)` polls
  `GET /api/jobs/<id>` every ~800 ms until terminal, toasting errors and
  invoking the callback with `job.result`. `App.trackJob` registers ids
  without polling.
- **SSE wiring**: `job.finished` → toast + Activity refresh; warnings → toasts;
  any event carrying `progress` updates the matching job row's bar and label
  live.
- **Health**: `refreshHealth()` updates the ready pill from `/api/health` on
  load and every 30 s.
- **Global search**: Enter in the topbar routes to the current context's
  search (documents/datasets/collections keep the current route; everything
  else searches entries).
- **Theme select** writes the choice to `/api/config` (`app.theme`) so the
  server-side preference matches.

## 5. The views (`views.js`)

Each view is an async function receiving the container (and hash params).
Shared state lives in a module-level `state` object so selections survive
re-renders.

### Dashboard
Six stat cards (datasets, entries, approved, documents, chunks indexed, graph
entities) that navigate on click; a **Getting started** checklist whose six
steps read live counts; recent activity from `/api/events/history`.

### Datasets
Card grid with per-dataset entry/approved counts and tag chips; create/edit
modal (name, description, tags); confirm-delete. Clicking a card opens its
entries filtered by dataset.

### Entries
Two-pane layout: filterable list (dataset, status, free-text with debounce)
and an editor pane. The editor lets you **reorder/delete/re-role messages**
(role select + ↑/↓/✕ per message), edit tags/notes/status inline, and shows
structural validation problems. Toolbar actions:

- **Save** — `PATCH /api/entries/<ref>` (auto-versioned server-side),
- **✦ Enhance assistant** / **✦ Suggest tags** / **✓ Evaluate** — background
  jobs; enhance results open a **suggestion modal** showing the improved text,
  rationale and change chips, evaluate toasts the score and refreshes,
- **Grounding** — modal previewing the chunks this entry would be grounded
  with (fused scores and per-retriever ranks),
- **Collect** — add to an existing collection or create one on the fly,

"+ New entry" offers manual fields **or LLM generation from a topic**
(grounded) as a background job.

### Collections
Card grid; the open-modal combines membership management (search-and-add
picker, per-entry remove) and one-click export buttons for all five formats.

### Documents
A **drag-and-drop dropzone** (plus click-to-browse) uploading via
`API.upload`; the import job is tracked and refreshes on completion.
Toolbar: Reindex all, New markdown note. The table lists kind, status,
chunk count, size and updated time. **Open** launches the document modal:

- status/kind/chunks pills, Clean with LLM, Enrich graph, Reindex actions,
- a **markdown toolbar** (bold, italic, H2, list, quote, inline code, code
  block, link) operating on the textarea selection,
- a **live split editor**: textarea on the left, `UI.markdown` preview on the
  right, re-rendered on every keystroke,
- Save persists via `PUT /markdown` with `reindex: true`; Delete confirms.

### Chat
Two-pane: conversation list + chat pane. Per-conversation **switches for RAG,
Graph and Grounding** (each PATCHes the conversation immediately), an editable
system prompt, and a streaming composer:

1. the user bubble is appended and an empty assistant bubble created,
2. `API.stream` consumes `/stream`: `retrieval` stores citations and marks
   grounding; `token` appends text (auto-scroll); `error` toasts; `done`
   renders the numbered citations under the bubble,
3. **Stop** aborts via `AbortController`,
4. assistant bubbles render markdown; user bubbles stay plain text.

### Graph
Stats cards from `/api/retrieval/status`, a query box, and a **circular SVG
layout** drawn client-side (`drawGraph`): nodes sized by mention count,
`CO_OCCURS` edges between them, all using theme CSS variables so it re-skins
automatically. Rebuild triggers the graph rebuild job.

### Activity (jobs)
Live list of background jobs — status pill, animated progress bar, current
message, duration, Cancel button — kept up to date by the SSE handler, plus a
capped event-log card and a "Cancel all" action.

### Settings
Four cards mirroring the config schema (LLM endpoint, embedding endpoint,
retrieval defaults, application):

- **Load** buttons fetch `/api/config/models` to populate model dropdowns,
- **Detect** probes `/api/config/embedding-dimension`,
- **Test connection** saves, runs `/api/config/test`, and renders per-endpoint
  ok/failure pills with details,
- **Finish setup** calls `/api/config/setup`,
- a setup-required banner appears when `missing_requirements` is non-empty,
- Saving `PUT`s the whole patch; missing-requirements are recomputed by the
  server and the ready pill updates on the next health poll.

## 6. Theming

`app.css` defines every visual token as CSS custom properties on `:root`
(light defaults), with `[data-theme="…"]` blocks overriding them. Fifteen
themes ship out of the box:

- **system** — follows `prefers-color-scheme` via a media query,
- **light family** — `light`, `ocean`, `forest`, `sunset`, `rose`, `paper`,
  `mono`, `grape`, `solarized` (tinted surfaces + chromatic accent pairings),
- **dark family** — `dark`, `nord`, `midnight`, `dracula`, `mocha`
  (Catppuccin Mocha).

Token families (documented in the CSS header): surfaces (`--bg`,
`--bg-elev`, `--bg-sunken`, `--bg-hover`), ink (`--text`, `--text-muted`),
lines (`--border`), chrome (`--sidebar-bg`, `--topbar-bg`, `--code-bg`),
brand (`--accent`, `--accent-contrast`, `--accent-2`), status (`--success`,
`--warning`, `--danger`), depth (`--shadow-sm|lg`, `--backdrop`) and shape
(`--radius*`). Components never hardcode colours — they consume the tokens,
so a theme is purely a variable swap. Some themes tweak shape too (e.g.
`paper` and `mono` reduce radii).

Quality rules every theme follows:

- **Tinted surfaces, no raw white** — light themes derive `--bg`, `--bg-elev`,
  `--sidebar-bg`, `--topbar-bg` and `--code-bg` from their own hue (cards are
  near-white with a tint, never `#ffffff` on a coloured page), so each theme
  has an atmosphere instead of white cards floating on a tinted void.
- **Chromatic pairing** — `--accent` and `--accent-2` (used together in the
  brand-mark gradient) follow a deliberate colour-wheel harmony: complementary
  (sunset ↔ teal, paper ↔ slate-blue), split-complementary (ocean ↔ coral,
  forest ↔ ochre) or analogous (rose ↔ violet, grape ↔ magenta); `mono` is
  strictly achromatic and `solarized` keeps its canonical complements.
- **`color-scheme`** — dark themes set `color-scheme: dark` so native
  controls (select dropdowns, scrollbars, number inputs) match the palette;
  `system` flips it with the media query.
- **Full token coverage** — each theme tunes shadows to its own hue (no
  blue-tinted shadows on warm palettes) and adapts the status colors
  (success/warning/danger, kept in the green/amber/red wheel sectors) for
  readable contrast on its surfaces.
- **Shared polish** — themed scrollbars (`scrollbar-color` +
  `::-webkit-scrollbar`), accent-tinted `::selection`, `:focus-visible`
  rings on buttons/links/nav, and a tokenized modal backdrop (`--backdrop`)
  that darkens appropriately on dark themes.

## 7. Adding a view (recipe)

1. Add the route name to `ROUTES` in `app.js` and a nav button with
   `data-route` in `index.html`.
2. Write `async function myView(view, params)` in `views.js`, build UI with
   `UI.el`, fetch through `API.*`, and export it on `window.Views`.
3. Long work? `const job = await API.post(...); jobToast(job, "Label");
   App.watchJob(job.id, refresh)` — progress and toasts come for free.
4. Style with existing classes (`card`, `grid cols-3`, `toolbar`, `field`,
   `pill`, `chip`, `job`) or add tokens-based CSS to `app.css`.
