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
