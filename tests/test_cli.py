"""CLI wiring: the default command must launch the desktop app."""

from __future__ import annotations

from minics import cli


def test_default_command_launches_app(monkeypatch, home):
    captured = {}

    def fake_run_app(home_arg=None, **kwargs):
        captured["home"] = home_arg
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr("minics.desktop.run_app", fake_run_app)
    assert cli.main([]) == 0
    assert captured["home"] is None
    assert captured["kwargs"]["port"] is None


def test_home_flag_is_honoured(monkeypatch, home):
    captured = {}

    def fake_run_app(home_arg=None, **kwargs):
        captured["home"] = home_arg
        return 0

    monkeypatch.setattr("minics.desktop.run_app", fake_run_app)
    assert cli.main(["--home", str(home)]) == 0
    assert captured["home"] == str(home)


def test_app_and_serve_subcommands(monkeypatch, home):
    captured = {}

    monkeypatch.setattr(
        "minics.desktop.run_app",
        lambda home_arg=None, **kwargs: captured.update(kind="app", **kwargs) or 0,
    )
    monkeypatch.setattr(
        "minics.desktop.run_browser",
        lambda home_arg=None, **kwargs: captured.update(kind="serve", **kwargs) or 0,
    )
    assert cli.main(["app", "--port", "1234"]) == 0
    assert captured["kind"] == "app" and captured["port"] == 1234
    assert cli.main(["serve", "--no-browser"]) == 0
    assert captured["kind"] == "serve" and captured["open_browser"] is False


def test_info_command(home, capsys):
    import json
    from pathlib import Path

    assert cli.main(["info"]) == 0
    output = capsys.readouterr().out
    assert "minics.sqlite3" in output
    assert Path(json.loads(output)["home"]).name == home.name


def test_store_command_auto_creates_home(home):
    """First-time users: a store-touching command bootstraps the whole home."""
    assert cli.main(["--home", str(home), "datasets"]) == 0
    assert (home / "minics.sqlite3").exists()
    assert (home / "documents" / "originals").exists()
    assert (home / "documents" / "markdown").exists()


def test_serve_auto_initializes_home(monkeypatch, home):
    """`minics serve` must work with an empty home and honour --home."""
    captured = {}

    def fake_run_server(host=None, port=None, *, debug=False, ctx=None, open_browser=None):
        captured["open_browser"] = open_browser

    # Stub only the blocking server; the real run_browser still runs and
    # performs the first-run initialisation we want to verify.
    monkeypatch.setattr("minics.server.app.run_server", fake_run_server)
    assert cli.main(["serve", "--no-browser", "--home", str(home)]) == 0
    assert captured["open_browser"] is False
    assert (home / "minics.sqlite3").exists()
    assert (home / "documents").exists()


# ---------------------------------------------------------------------------
# minics scan
# ---------------------------------------------------------------------------
def test_scan_imports_directory(home, tmp_path, capsys):
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "a.md").write_text("# Hello\n\nWorld", encoding="utf-8")
    (docs / "sub" / "b.txt").write_text("plain text", encoding="utf-8")
    (docs / "skip.log").write_text("ignored", encoding="utf-8")

    assert cli.main(["--home", str(home), "scan", str(docs), "--no-index"]) == 0
    out = capsys.readouterr().out
    assert "2 document(s)" in out
    assert "2 imported, 0 duplicate(s) skipped, 0 failed" in out

    # A second scan must skip everything as duplicates (same SHA-256).
    assert cli.main(["--home", str(home), "scan", str(docs), "--no-index"]) == 0
    out = capsys.readouterr().out
    assert "0 imported, 2 duplicate(s) skipped" in out


def test_scan_dry_run_changes_nothing(home, tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# Hello", encoding="utf-8")

    assert cli.main(["--home", str(home), "scan", str(docs), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would import" in out
    assert not (home / "minics.sqlite3").exists()


def test_scan_format_flags_filter_files(home, tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# Hello", encoding="utf-8")

    assert cli.main(["--home", str(home), "scan", str(docs), "--pdf", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "No compatible documents found" in out


def test_scan_missing_directory(home, capsys):
    assert cli.main(["--home", str(home), "scan", "does-not-exist"]) == 1
    assert "not a directory" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# minics skills
# ---------------------------------------------------------------------------
def test_skills_list(home, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # away from any real .agents/skills
    assert cli.main(["--home", str(home), "skills", "list"]) == 0
    out = capsys.readouterr().out
    assert "minics" in out and "minics-documents" in out
    assert "not installed" in out


def test_skills_install_local_and_skip(home, tmp_path, capsys):
    target = tmp_path / "agents"
    assert cli.main(["--home", str(home), "skills", "install", "--dir", str(target)]) == 0
    out = capsys.readouterr().out
    assert "11 installed" in out
    assert (target / "minics" / "SKILL.md").is_file()
    assert (target / "minics-documents" / "SKILL.md").is_file()

    # Without --force everything is skipped; with --force it overwrites.
    assert cli.main(["--home", str(home), "skills", "install", "--dir", str(target)]) == 0
    assert "0 installed, 11 skipped" in capsys.readouterr().out
    assert cli.main(
        ["--home", str(home), "skills", "install", "--dir", str(target), "--force"]
    ) == 0
    assert "11 installed" in capsys.readouterr().out


def test_skills_install_interactive_selection(home, tmp_path, capsys, monkeypatch):
    target = tmp_path / "agents"
    monkeypatch.setattr("builtins.input", lambda *a: "minics, minics-setup")
    assert cli.main(
        ["--home", str(home), "skills", "install", "--dir", str(target), "--interactive"]
    ) == 0
    out = capsys.readouterr().out
    assert "2 installed" in out
    assert (target / "minics" / "SKILL.md").is_file()
    assert (target / "minics-setup" / "SKILL.md").is_file()
    assert not (target / "minics-chat").exists()


def test_skills_install_unknown_name_fails(home, tmp_path, capsys, monkeypatch):
    target = tmp_path / "agents"
    monkeypatch.setattr("builtins.input", lambda *a: "not-a-skill")
    assert cli.main(
        ["--home", str(home), "skills", "install", "--dir", str(target), "--interactive"]
    ) == 1
    assert "Unknown skill" in capsys.readouterr().err
