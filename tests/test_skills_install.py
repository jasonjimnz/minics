"""Pi project-trust integration for the skills installer."""

from __future__ import annotations

import json

from minics.skills_install import (
    pi_trust_decision,
    read_pi_trust,
    register_pi_trust,
)


def test_register_and_read_trust(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CONFIG_DIR", str(tmp_path / "pi-agent"))
    project = tmp_path / "some-project"
    project.mkdir()
    assert read_pi_trust() == {}
    assert pi_trust_decision(project) is None

    register_pi_trust(project, trusted=True)
    assert pi_trust_decision(project) is True
    saved = json.loads((tmp_path / "pi-agent" / "trust.json").read_text())
    assert saved[str(project.resolve())] is True

    # Idempotent, and explicit decline overwrites a previous grant.
    register_pi_trust(project, trusted=True)
    register_pi_trust(project, trusted=False)
    assert pi_trust_decision(project) is False


def test_description_yaml_issue_detection():
    from minics.skills_install import BundledSkill, description_yaml_issue

    # Unquoted colon+space breaks Pi's frontmatter parser.
    broken = BundledSkill(
        name="x",
        description="Covers the workflow: setup and scan",
        source=__import__("pathlib").Path("."),
        description_quoted=False,
    )
    assert description_yaml_issue(broken) is not None

    # The same value quoted is fine.
    quoted = BundledSkill(
        name="x",
        description="Covers the workflow: setup and scan",
        source=__import__("pathlib").Path("."),
        description_quoted=True,
    )
    assert description_yaml_issue(quoted) is None

    # Plain descriptions are fine.
    plain = BundledSkill(
        name="x",
        description="Grounded chat in MiniCS with citations.",
        source=__import__("pathlib").Path("."),
        description_quoted=False,
    )
    assert description_yaml_issue(plain) is None


def test_bundled_skills_descriptions_are_pi_safe():
    from minics.skills_install import bundled_skills, description_yaml_issue

    for skill in bundled_skills():
        assert description_yaml_issue(skill) is None, skill.name
