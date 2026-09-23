#!/usr/bin/env python3
"""Build the MiniCS documentation site for GitHub Pages.

Converts docs/*.md into a static, GitHub-Primer-styled website in site/
with sidebar navigation, on-this-page TOC, client-side search and a
light/dark theme toggle. Output is fully static — no JS framework, no
runtime build step.

Usage:
    python tools/build_docs.py            # build into ./site
    python tools/build_docs.py --out DIR  # build elsewhere
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPO_URL = "https://github.com/jasonjimnz/minics"

# (slug, title, blurb, group) — order defines sidebar and prev/next pager.
PAGES: list[tuple[str, str, str, str]] = [
    ("index", "Overview", "What MiniCS Lite is and how to read the docs.", "Getting started"),
    ("installation", "Installation", "Install from PyPI or source, requirements, verify and upgrade.", "Getting started"),
    ("getting-started", "Getting started", "Create the store, run the wizard, build your first grounded dataset.", "Getting started"),
    ("features", "Features", "The full feature tour: library, grounding, retrieval, LLM tools, UI.", "Getting started"),
    ("architecture", "Architecture", "Layers, request lifecycle, concurrency model and design decisions.", "Core"),
    ("libraries", "Libraries", "Every dependency: what it does, where it is used, why it was chosen.", "Core"),
    ("configuration", "Configuration", "Every config key, the setup wizard and API-key masking.", "Core"),
    ("backend", "Core & backend", "SQLite writer thread, event bus, job manager, entities, services, CLI.", "Core"),
    ("llm", "LLM layer", "OpenAI-protocol client, embeddings, structured output, prompt library.", "Core"),
    ("rag", "RAG & graph engine", "Conversion, chunking, entity extraction, ChromaDB, Ladybug graph, RRF.", "Core"),
    ("serving", "Serving with Flask", "minics serve, the app factory, reverse proxies and security notes.", "Running"),
    ("docker", "Docker", "Running MiniCS as a server container: build, volumes, operations.", "Running"),
    ("api", "HTTP API", "Every REST endpoint, the SSE stream, background jobs, error mapping.", "Reference"),
    ("frontend", "Frontend", "The no-build SPA: routing, SSE, theming, markdown renderer, graph canvas.", "Reference"),
    ("storage", "Data & storage", "The ~/.minics store, embedded databases, backups and portability.", "Reference"),
    ("development", "Development", "Dev environment, tests, fixtures, code style, schema migrations.", "Reference"),
]

MD_EXTENSIONS = [
    "fenced_code",
    "tables",
    "sane_lists",
    "admonition",
    "codehilite",
    "toc",
    "attr_list",
]

MD_EXTENSION_CONFIGS = {
    "codehilite": {"guess_lang": False, "css_class": "highlight", "linenums": False},
    "toc": {"permalink": True, "permalink_class": "heading-anchor", "toc_depth": "2-3"},
}


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


def rewrite_links(html: str) -> str:
    """Rewrite relative .md links to .html and externalise bare anchors."""

    def repl(m: re.Match) -> str:
        target, anchor = m.group(1), m.group(2) or ""
        if re.match(r"^[a-z]+://", target):
            return f'href="{target}{anchor}"'
        if target.endswith(".md"):
            return f'href="{target[:-3]}.html{anchor}"'
        return m.group(0)

    return re.sub(r'href="([^"#]+?\.md)(#[^"]*)?"', repl, html)


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def extract_sections(html: str) -> list[dict]:
    """Split rendered HTML into (anchor, heading, text) chunks for search."""
    sections: list[dict] = []
    pattern = re.compile(
        r'<h([23])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>', re.DOTALL
    )
    matches = list(pattern.finditer(html))
    # Preamble (before first h2)
    preamble = html[: matches[0].start()] if matches else html
    preamble_text = strip_tags(preamble)
    sections.append({"anchor": "", "heading": "", "text": preamble_text[:4000]})
    for i, m in enumerate(matches):
        heading_html = re.sub(
            r'<a[^>]*class="heading-anchor"[^>]*>.*?</a>', "", m.group(3), flags=re.DOTALL
        )
        heading = strip_tags(heading_html)
        body = html[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(html)]
        sections.append(
            {"anchor": m.group(2), "heading": heading, "text": strip_tags(body)[:6000]}
        )
    return sections


def build_search_index(pages: dict[str, dict]) -> str:
    index = []
    for slug, (_, title, blurb, _) in zip(pages.keys(), PAGES):
        data = pages[slug]
        for sec in data["sections"]:
            index.append(
                {
                    "p": slug,
                    "t": title,
                    "h": sec["heading"],
                    "a": sec["anchor"],
                    "x": f"{blurb}. {sec['text']}",
                }
            )
    return json.dumps(index, ensure_ascii=False)


def pygments_css() -> str:
    light = HtmlFormatter(style="default").get_style_defs('.markdown-body .highlight')
    try:
        dark = HtmlFormatter(style="github-dark").get_style_defs('.markdown-body .highlight')
    except Exception:
        dark = HtmlFormatter(style="monokai").get_style_defs('.markdown-body .highlight')
    return f"{light}\n\n[data-color-mode=\"dark\"] {dark}"


def render_page(slug: str, meta: tuple[str, str, str, str], body: str, toc_items: str) -> str:
    title, blurb, group = meta[1], meta[2], meta[3]
    nav = build_nav(slug)
    idx = [p[0] for p in PAGES].index(slug)
    prev_page = PAGES[idx - 1] if idx > 0 else None
    next_page = PAGES[idx + 1] if idx + 1 < len(PAGES) else None

    def pager(page: tuple[str, str, str, str] | None, direction: str) -> str:
        if not page:
            return "<div></div>"
        href = "index.html" if page[0] == "index" else f"{page[0]}.html"
        return (
            f'<a class="pager-card {direction}" href="{href}">'
            f'<span class="pager-label">{direction.capitalize()}</span>'
            f'<span class="pager-title">{escape(page[1])}</span></a>'
        )

    return TEMPLATE.format(
        title=f"{title} · MiniCS Docs" if slug != "index" else "MiniCS Lite Documentation",
        description=escape(blurb),
        nav=nav,
        body=body,
        toc=toc_items,
        group=escape(group),
        title_h1=escape(title),
        blurb=escape(blurb),
        edit_url=f"{REPO_URL}/edit/main/docs/{slug}.md",
        prev=pager(prev_page, "previous"),
        next=pager(next_page, "next"),
        repo_url=REPO_URL,
        year=datetime.now(timezone.utc).year,
    )


def build_nav(active: str) -> str:
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for slug, title, blurb, group in PAGES:
        groups.setdefault(group, []).append((slug, title, blurb))
    out = []
    for group, items in groups.items():
        out.append(f'<div class="nav-group"><h3>{escape(group)}</h3><ul>')
        for slug, title, _ in items:
            href = "index.html" if slug == "index" else f"{slug}.html"
            cls = ' class="active"' if slug == active else ""
            aria = ' aria-current="page"' if slug == active else ""
            out.append(f'<li><a href="{href}"{cls}{aria}>{escape(title)}</a></li>')
        out.append("</ul></div>")
    return "".join(out)


def build_toc(toc_tokens) -> str:
    if not toc_tokens:
        return ""
    out = ['<nav class="toc"><h4>On this page</h4><ul>']

    def walk(tokens):
        for tok in tokens:
            level, tid, name, children = tok["level"], tok["id"], tok["name"], tok["children"]
            out.append(f'<li class="toc-l{level}"><a href="#{tid}">{name}</a></li>')
            if children:
                walk(children)

    walk(toc_tokens)
    out.append("</ul></nav>")
    return "".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "site"))
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    md = markdown.Markdown(
        extensions=MD_EXTENSIONS, extension_configs=MD_EXTENSION_CONFIGS
    )

    pages: dict[str, dict] = {}
    for slug, *_ in PAGES:
        src = DOCS / f"{slug}.md"
        text = src.read_text(encoding="utf-8")
        # Drop the H1 — the template provides its own title header.
        body_lines = text.split("\n")
        if body_lines and body_lines[0].startswith("# "):
            body_lines = body_lines[1:]
            while body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
        text = "\n".join(body_lines)

        md.reset()
        md.toc_tokens = []
        html = md.convert(text)
        html = rewrite_links(html)
        toc_items = build_toc(md.toc_tokens)
        meta = next(p for p in PAGES if p[0] == slug)
        pages[slug] = {
            "html": html,
            "sections": extract_sections(html),
            "meta": meta,
        }

    for slug, data in pages.items():
        meta = data["meta"]
        page_html = render_page(slug, meta, data["html"], build_toc(
            _toc_tokens_for(pages, slug)))
        (out / f"{slug}.html").write_text(page_html, encoding="utf-8")

    (out / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (out / "assets" / "highlight.css").write_text(pygments_css(), encoding="utf-8")
    (out / "assets" / "site.js").write_text(SITE_JS, encoding="utf-8")
    (out / "assets" / "search.json").write_text(build_search_index(pages), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Built {len(pages)} pages into {out}")


def _toc_tokens_for(pages: dict, slug: str):
    """Re-run markdown to fetch toc tokens (md instance is stateful)."""
    src = DOCS / f"{slug}.md"
    text = src.read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    md = markdown.Markdown(
        extensions=MD_EXTENSIONS, extension_configs=MD_EXTENSION_CONFIGS
    )
    md.convert("\n".join(lines))
    return md.toc_tokens


TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-color-mode="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{description}">
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path fill='%230969da' d='M4 1.75C4 .784 4.784 0 5.75 0h5.586c.464 0 .909.184 1.237.513l2.914 2.914c.329.328.513.773.513 1.237v9.586A1.75 1.75 0 0 1 14.25 16h-8.5A1.75 1.75 0 0 1 4 14.25Zm1.75-.25a.25.25 0 0 0-.25.25v12.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25V4.664a.25.25 0 0 0-.073-.177l-2.914-2.914a.25.25 0 0 0-.177-.073ZM8.75 6a.75.75 0 0 1 1.5 0v4.19l1.22-1.22a.749.749 0 1 1 1.06 1.06l-2.5 2.5a.749.749 0 0 1-1.06 0l-2.5-2.5a.749.749 0 1 1 1.06-1.06l1.22 1.22Z'/></svg>">
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="assets/highlight.css">
<script src="assets/site.js" defer></script>
</head>
<body>
<a class="skip-link" href="#content">Skip to content</a>

<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="index.html">
      <svg class="octicon" viewBox="0 0 16 16" width="24" height="24" aria-hidden="true"><path fill="currentColor" d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.743 3.743 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75Zm7.251 10.324.004-5.073-.002-2.253A2.25 2.25 0 0 0 5.003 2.5H1.5v9h3.757a3.75 3.75 0 0 1 1.994.574ZM8.755 4.75l-.004 7.322a3.752 3.752 0 0 1 1.992-.572H14.5v-9h-3.495a2.25 2.25 0 0 0-2.25 2.25Z"/></svg>
      <span class="brand-text">minics</span>
      <span class="brand-divider">/</span>
      <span class="brand-strong">Docs</span>
      <span class="badge">v0.3.1</span>
    </a>
    <div class="header-actions">
      <div class="search-box" id="search-box">
        <svg class="octicon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"/></svg>
        <input type="search" id="search-input" placeholder="Search docs" autocomplete="off" spellcheck="false" aria-label="Search documentation">
        <kbd>/</kbd>
        <div class="search-results" id="search-results" hidden></div>
      </div>
      <button class="icon-btn" id="theme-toggle" aria-label="Toggle theme">
        <svg class="octicon theme-icon-light" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M8 12a4 4 0 1 1 0-8 4 4 0 0 1 0 8Zm0-1.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm5.657-8.157a.75.75 0 0 1 0 1.061l-1.061 1.06a.749.749 0 1 1-1.06-1.06l1.06-1.06a.75.75 0 0 1 1.06 0Zm-9.193 9.193a.75.75 0 0 1 0 1.06l-1.06 1.061a.75.75 0 1 1-1.061-1.06l1.06-1.061a.75.75 0 0 1 1.061 0ZM8 0a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0V.75A.75.75 0 0 1 8 0ZM3 8a.75.75 0 0 1-.75.75H.75a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 3 8Zm13 0a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 16 8ZM8 13a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 8 13Zm2.657-4.343a.75.75 0 0 1 1.06 0l1.061 1.06a.75.75 0 1 1-1.06 1.061l-1.061-1.06a.75.75 0 0 1 0-1.061Zm-9.193 9.193a.75.75 0 0 1 1.06 0l1.061-1.06a.75.75 0 1 1 1.061 1.06l-1.06 1.061a.75.75 0 0 1-1.061 0Zm0-9.193a.75.75 0 0 1 0-1.06L2.524 3.54a.75.75 0 0 1 1.06 1.06l-1.06 1.061a.75.75 0 0 1-1.06 0Zm9.193 9.193a.75.75 0 0 1 1.06 0l1.061 1.06a.75.75 0 1 1-1.06 1.061l-1.061-1.06a.75.75 0 0 1 0-1.061Z"/></svg>
        <svg class="octicon theme-icon-dark" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M9.598 1.591a.749.749 0 0 1 .785-.175 7.001 7.001 0 1 1-8.967 8.967.75.75 0 0 1 .961-.96 5.5 5.5 0 0 0 7.046-7.046.75.75 0 0 1 .175-.786Zm1.616 1.945a7 7 0 0 1-7.678 7.678 5.499 5.499 0 1 0 7.678-7.678Z"/></svg>
      </button>
      <a class="icon-btn" href="{repo_url}" target="_blank" rel="noopener" aria-label="GitHub repository">
        <svg class="octicon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/></svg>
      </a>
    </div>
  </div>
</header>

<div class="layout">
  <aside class="sidebar" id="sidebar">
    <nav aria-label="Documentation">{nav}</nav>
  </aside>
  <main class="content" id="content">
    <article class="markdown-body">
      <div class="page-header">
        <div class="page-header-text">
          <p class="page-kicker">{group}</p>
          <h1>{title_h1}</h1>
          <p class="page-blurb">{blurb}</p>
        </div>
        <a class="edit-link" href="{edit_url}" target="_blank" rel="noopener">
          <svg class="octicon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Zm.176 4.823L9.75 4.81l-6.286 6.287a.253.253 0 0 0-.064.108l-.558 1.953 1.953-.558a.253.253 0 0 0 .108-.064Zm1.238-3.763a.25.25 0 0 0-.354 0L10.811 3.75l1.439 1.44 1.263-1.263a.25.25 0 0 0 0-.354Z"/></svg>
          Edit this page
        </a>
      </div>
{body}
    </article>
    <nav class="pager" aria-label="Pagination">
{prev}
{next}
    </nav>
  </main>
  <aside class="toc-rail">
{toc}
  </aside>
</div>

<footer class="site-footer">
  <div class="footer-inner">
    <span>© {year} MiniCS Lite · Built from <a href="{repo_url}/tree/main/docs">docs/</a> · <a href="{repo_url}/issues">Report an issue</a></span>
  </div>
</footer>
</body>
</html>
"""

STYLE_CSS = """:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
}

[data-color-mode="light"] {
  --bg: #ffffff; --bg-inset: #f6f8fa; --bg-subtle: #f6f8fa;
  --border: #d0d7de; --border-muted: #d8dee4;
  --fg: #1f2328; --fg-muted: #59636e; --fg-subtle: #6e7781;
  --accent: #0969da; --accent-emphasis: #0550ae;
  --success: #1a7f37; --header-bg: #24292f; --header-fg: #ffffff;
  --btn-bg: #f6f8fa; --btn-hover: #eef1f4;
  --nav-active-bg: #ddf4ff; --nav-active-fg: #0969da;
  --shadow: 0 1px 0 rgba(31,35,40,.04);
  --code-bg: #f6f8fa; --kbd-bg: #f6f8fa;
}

[data-color-mode="dark"] {
  --bg: #0d1117; --bg-inset: #010409; --bg-subtle: #161b22;
  --border: #30363d; --border-muted: #21262d;
  --fg: #e6edf3; --fg-muted: #8b949e; --fg-subtle: #6e7681;
  --accent: #2f81f7; --accent-emphasis: #1f6feb;
  --success: #3fb950; --header-bg: #010409; --header-fg: #e6edf3;
  --btn-bg: #21262d; --btn-hover: #30363d;
  --nav-active-bg: #121d2f; --nav-active-fg: #2f81f7;
  --shadow: 0 0 transparent;
  --code-bg: #161b22; --kbd-bg: #21262d;
}

@media (prefers-color-scheme: dark) {
  [data-color-mode="auto"] {
    --bg: #0d1117; --bg-inset: #010409; --bg-subtle: #161b22;
    --border: #30363d; --border-muted: #21262d;
    --fg: #e6edf3; --fg-muted: #8b949e; --fg-subtle: #6e7681;
    --accent: #2f81f7; --accent-emphasis: #1f6feb;
    --success: #3fb950; --header-bg: #010409; --header-fg: #e6edf3;
    --btn-bg: #21262d; --btn-hover: #30363d;
    --nav-active-bg: #121d2f; --nav-active-fg: #2f81f7;
    --shadow: 0 0 transparent;
    --code-bg: #161b22; --kbd-bg: #21262d;
  }
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 5rem; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: var(--font-sans); font-size: 16px; line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.skip-link {
  position: absolute; left: -9999px; top: 0; background: var(--accent);
  color: #fff; padding: 8px 16px; z-index: 100; border-radius: 6px;
}
.skip-link:focus { left: 16px; top: 16px; }

/* ---------- Header ---------- */
.site-header {
  position: sticky; top: 0; z-index: 50;
  background: var(--header-bg); color: var(--header-fg);
  box-shadow: 0 1px 0 rgba(255,255,255,.08);
}
.header-inner {
  max-width: 1440px; margin: 0 auto; padding: 0 24px;
  display: flex; align-items: center; justify-content: space-between;
  height: 56px; gap: 16px;
}
.brand {
  display: flex; align-items: center; gap: 8px;
  color: var(--header-fg); text-decoration: none; font-size: 14px;
  white-space: nowrap;
}
.brand:hover .brand-text { text-decoration: underline; }
.brand-text, .brand-divider { color: rgba(255,255,255,.7); }
.brand-strong { font-weight: 600; }
.badge {
  font-size: 11px; font-weight: 500; padding: 1px 8px;
  border: 1px solid rgba(255,255,255,.35); border-radius: 999px;
  color: rgba(255,255,255,.85); margin-left: 4px;
}
.header-actions { display: flex; align-items: center; gap: 8px; }

.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 6px;
  background: transparent; border: 1px solid rgba(255,255,255,.2);
  color: var(--header-fg); cursor: pointer; transition: background .15s;
}
.icon-btn:hover { background: rgba(255,255,255,.12); }

/* ---------- Search ---------- */
.search-box { position: relative; }
.search-box svg { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); opacity: .6; }
.search-box input {
  width: 260px; height: 32px; padding: 0 44px 0 30px;
  background: rgba(255,255,255,.08); color: var(--header-fg);
  border: 1px solid rgba(255,255,255,.2); border-radius: 6px;
  font-size: 13px; font-family: inherit; outline: none;
  transition: width .2s, background .15s;
}
.search-box input::placeholder { color: rgba(255,255,255,.55); }
.search-box input:focus { background: rgba(255,255,255,.14); width: 320px; border-color: var(--accent); }
.search-box kbd {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  font-family: var(--font-sans); font-size: 11px; padding: 1px 5px;
  border: 1px solid rgba(255,255,255,.3); border-radius: 4px;
  color: rgba(255,255,255,.6); pointer-events: none;
}
.search-results {
  position: absolute; top: 40px; right: 0; width: 420px; max-height: 480px;
  overflow-y: auto; background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,.25); z-index: 60; padding: 4px;
}
[data-color-mode="auto"] .search-results { background: var(--bg); }
@media (prefers-color-scheme: light) {
  [data-color-mode="auto"] .search-results { box-shadow: 0 8px 24px rgba(66,74,83,.18); }
}
.search-result { display: block; padding: 8px 12px; border-radius: 6px; text-decoration: none; color: inherit; }
.search-result:hover, .search-result.selected { background: var(--nav-active-bg); }
.search-result .sr-page { font-size: 12px; color: var(--accent); font-weight: 600; }
.search-result .sr-heading { font-size: 13px; font-weight: 600; margin-top: 1px; }
.search-result .sr-snippet { font-size: 12px; color: var(--fg-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 1px; }
.search-empty { padding: 16px; text-align: center; color: var(--fg-muted); font-size: 13px; }
mark { background: rgba(255,212,0,.4); color: inherit; border-radius: 2px; padding: 0 1px; }
[data-color-mode="dark"] mark { background: rgba(187,128,9,.5); }

/* ---------- Layout ---------- */
.layout {
  max-width: 1440px; margin: 0 auto; padding: 32px 24px;
  display: grid; grid-template-columns: 256px minmax(0,1fr) 224px;
  gap: 40px;
}
.sidebar { position: sticky; top: 88px; align-self: start; max-height: calc(100vh - 110px); overflow-y: auto; }
.toc-rail { position: sticky; top: 88px; align-self: start; }

.nav-group { margin-bottom: 20px; }
.nav-group h3 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--fg-muted); margin: 0 0 6px; font-weight: 600;
}
.nav-group ul { list-style: none; margin: 0; padding: 0; }
.nav-group a {
  display: block; padding: 4px 10px; border-radius: 6px;
  color: var(--fg-muted); text-decoration: none; font-size: 14px;
  transition: background .1s;
}
.nav-group a:hover { background: var(--btn-hover); color: var(--fg); }
.nav-group a.active { background: var(--nav-active-bg); color: var(--nav-active-fg); font-weight: 600; }

/* ---------- Page header ---------- */
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; margin-bottom: 8px; padding-bottom: 16px;
  border-bottom: 1px solid var(--border-muted);
}
.page-kicker {
  margin: 0 0 4px; font-size: 12px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .05em; color: var(--accent);
}
.page-header h1 { margin: 0 0 4px; font-size: 30px; line-height: 1.2; border: 0; padding: 0; }
.page-blurb { margin: 0; color: var(--fg-muted); font-size: 15px; }
.edit-link {
  display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0;
  margin-top: 6px; font-size: 13px; color: var(--fg-muted);
  text-decoration: none; border: 1px solid var(--border);
  padding: 4px 10px; border-radius: 6px; transition: all .15s;
}
.edit-link:hover { color: var(--accent); border-color: var(--accent); }

/* ---------- Markdown body (Primer-flavoured) ---------- */
.markdown-body { min-width: 0; font-size: 16px; }
.markdown-body h2 {
  margin: 32px 0 16px; padding-bottom: 8px; font-size: 24px;
  font-weight: 600; border-bottom: 1px solid var(--border-muted);
}
.markdown-body h3 { margin: 28px 0 12px; font-size: 19px; font-weight: 600; }
.markdown-body h4 { margin: 24px 0 8px; font-size: 16px; font-weight: 600; }
.markdown-body p { margin: 0 0 16px; }
.markdown-body a { color: var(--accent); text-decoration: none; }
.markdown-body a:hover { text-decoration: underline; }
.markdown-body ul, .markdown-body ol { margin: 0 0 16px; padding-left: 28px; }
.markdown-body li + li { margin-top: 4px; }
.markdown-body blockquote {
  margin: 0 0 16px; padding: 0 16px; color: var(--fg-muted);
  border-left: 4px solid var(--border);
}
.markdown-body code {
  font-family: var(--font-mono); font-size: 85%;
  background: var(--code-bg); border-radius: 6px; padding: .2em .4em;
}
.markdown-body pre {
  margin: 0 0 16px; padding: 16px; overflow-x: auto;
  background: var(--code-bg); border-radius: 8px; line-height: 1.45;
}
.markdown-body pre code {
  background: transparent; padding: 0; font-size: 13.5px; line-height: 1.45;
}
.highlight { background: transparent; border-radius: 8px; }
.highlight pre { margin: 0; }
.markdown-body table {
  width: 100%; border-collapse: collapse; margin: 0 0 16px;
  display: block; overflow-x: auto; font-size: 14px;
}
.markdown-body th, .markdown-body td {
  border: 1px solid var(--border); padding: 6px 14px; text-align: left;
}
.markdown-body th { background: var(--bg-subtle); font-weight: 600; }
.markdown-body tr:nth-child(2n) td { background: var(--bg-subtle); }
.markdown-body hr { border: 0; border-top: 1px solid var(--border-muted); margin: 28px 0; }
.markdown-body img { max-width: 100%; }
.markdown-body .admonition {
  margin: 0 0 16px; padding: 12px 16px; border-radius: 8px;
  border: 1px solid var(--accent); border-left-width: 4px;
  background: var(--nav-active-bg);
}
.markdown-body .admonition-title { font-weight: 600; margin: 0 0 4px; color: var(--accent-emphasis); }
.heading-anchor { opacity: 0; margin-left: 6px; color: var(--accent); text-decoration: none; font-weight: 400; }
h2:hover .heading-anchor, h3:hover .heading-anchor { opacity: 1; }

/* ---------- TOC rail ---------- */
.toc h4 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--fg-muted); margin: 0 0 8px; font-weight: 600;
}
.toc ul { list-style: none; margin: 0; padding: 0; }
.toc a {
  display: block; padding: 3px 0 3px 12px; font-size: 13px;
  color: var(--fg-muted); text-decoration: none;
  border-left: 2px solid transparent;
}
.toc a:hover { color: var(--fg); }
.toc a.active { color: var(--accent); border-left-color: var(--accent); font-weight: 500; }
.toc-l3 a { padding-left: 24px; }

/* ---------- Pager ---------- */
.pager { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border-muted); }
.pager-card {
  display: flex; flex-direction: column; gap: 2px; padding: 12px 16px;
  border: 1px solid var(--border); border-radius: 8px;
  text-decoration: none; transition: border-color .15s;
}
.pager-card:hover { border-color: var(--accent); }
.pager-card.next { text-align: right; }
.pager-label { font-size: 12px; color: var(--fg-muted); }
.pager-title { font-size: 14px; font-weight: 600; color: var(--accent); }

/* ---------- Footer ---------- */
.site-footer { border-top: 1px solid var(--border-muted); margin-top: 48px; }
.footer-inner {
  max-width: 1440px; margin: 0 auto; padding: 20px 24px;
  font-size: 13px; color: var(--fg-muted);
}
.footer-inner a { color: var(--accent); text-decoration: none; }
.footer-inner a:hover { text-decoration: underline; }

/* ---------- Responsive ---------- */
@media (max-width: 1100px) {
  .layout { grid-template-columns: 220px minmax(0,1fr); }
  .toc-rail { display: none; }
}
@media (max-width: 820px) {
  .layout { grid-template-columns: 1fr; padding: 20px 16px; }
  .sidebar { position: static; max-height: none; border-bottom: 1px solid var(--border-muted); padding-bottom: 16px; margin-bottom: 8px; }
  .search-box input { width: 150px; }
  .search-box input:focus { width: 200px; }
  .pager { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .brand-text, .brand-divider, .badge { display: none; }
  .page-header { flex-direction: column; }
}
"""

SITE_JS = r"""// MiniCS docs: theme toggle, search, TOC highlighting
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
"""


if __name__ == "__main__":
    main()
