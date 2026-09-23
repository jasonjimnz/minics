# Installation

MiniCS Lite is a standard Python package with one entry-point command,
`minics`. It runs entirely on your machine — there is no cloud service, no
account and no telemetry. This page covers installing from PyPI, from the
repository, verifying the install and where your data will (and will not) go.

---

## 1. Requirements

| Requirement | Details |
| --- | --- |
| Python | **3.10 or newer** (the Docker image uses 3.13) |
| Operating system | Windows, macOS or Linux |
| A model endpoint | Any OpenAI-compatible chat endpoint and any embedding endpoint — OpenAI, vLLM, `llama.cpp` (`llama-server`), LM Studio, Ollama's OpenAI shim, Azure-style gateways. They may be two different servers. |
| Desktop shell (optional) | PyWebView needs a system webview: Edge WebView2 on Windows, WebKit on macOS, and GTK/Qt WebKit on Linux (`python3-gi`, `webkit2gtk` or the Qt equivalent). On headless machines MiniCS automatically falls back to opening the UI in your browser — nothing breaks. |

> **Heads-up on install size** — the dependency set includes ChromaDB,
> LadybugDB and the LangChain stack, so the first `pip install` downloads a
> few hundred MB of wheels. Subsequent installs are incremental.

## 2. Install from PyPI

The project is published to PyPI as **`minichat-studio`**:

```bash
pip install minichat-studio
```

Prefer an isolated environment (any tool you like):

```bash
# venv
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install minichat-studio

# or pipx — the `minics` CLI becomes available globally
pipx install minichat-studio
```

## 3. Install from the repository

If you want the latest code on `main`, or you plan to contribute:

```bash
# straight from GitHub
pip install git+https://github.com/jasonjimnz/minics.git

# or clone and install in editable mode with the dev toolchain
git clone git@github.com:jasonjimnz/minics.git
cd minics
pip install -e ".[dev]"
```

The `dev` extra adds `pytest`, `pytest-cov` and `ruff` — see
[development.md](development.md) for the test and style workflow.

## 4. Verify the installation

```bash
minics version      # prints the package version
minics info         # resolved paths and init state
minics --help       # every command
```

`minics info` shows where the store lives — by default `~/.minics`, overridable
with the `MINICS_HOME` environment variable (see [storage.md](storage.md)).

## 5. Upgrading and uninstalling

```bash
pip install --upgrade minichat-studio
```

Upgrades never touch your data: the store in `~/.minics` is independent of the
installed package, and SQLite schema migrations (if any) are applied
automatically and additively on the next start.

```bash
pip uninstall minichat-studio
```

Uninstalling removes only the package. Your datasets, documents, vector index
and config remain in `~/.minics` until you delete that folder yourself — see
[storage.md](storage.md) for what is inside and how to back it up or move it.

## 6. Next steps

1. [Getting started](getting-started.md) — create the store, run the setup
   wizard, launch the app and build your first dataset.
2. [Features](features.md) — the full tour of what the application can do.
3. [Docker](docker.md) — prefer a container? Run the same app as a server with
   one volume and no host-side Python.
