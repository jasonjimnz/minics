"""Install the MiniCS agent skillset bundled inside the package.

The skills live as package data under ``minics/skills/`` — each skill is a
directory with a ``SKILL.md`` (YAML frontmatter with ``name`` and
``description``), the format understood by Pi, OpenCode, Codex and any other
agent that reads ``.agents/skills/``.  Installing never touches the network:
everything is copied straight from the installed ``minichat-studio`` package.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Fallback list of bundled skill directory names, used for ordering.
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class BundledSkill:
    """One skill bundled with the package."""

    name: str
    description: str
    source: Path
    description_quoted: bool = False

    @property
    def files(self) -> list[Path]:
        return sorted(p for p in self.source.rglob("*") if p.is_file())


def skills_root() -> Path:
    """Directory holding the bundled skills (inside the installed package)."""
    return Path(__file__).resolve().parent / "skills"


def bundled_skills() -> list[BundledSkill]:
    """Parse every bundled ``SKILL.md`` frontmatter, sorted by name."""
    skills: list[BundledSkill] = []
    root = skills_root()
    if not root.is_dir():
        return skills
    for skill_dir in sorted(root.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        match = FRONTMATTER_RE.match(skill_md.read_text(encoding="utf-8"))
        name, description = skill_dir.name, ""
        description_quoted = False
        if match:
            for line in match.group(1).splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip("\"'")
                elif line.startswith("description:"):
                    raw = line.split(":", 1)[1].strip()
                    description_quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
                    description = raw.strip("\"'")
        skills.append(
            BundledSkill(
                name=name,
                description=description,
                source=skill_dir,
                description_quoted=description_quoted,
            )
        )
    return skills


def description_yaml_issue(skill: BundledSkill) -> str | None:
    """Return a problem string when a description breaks strict YAML parsing.

    An unquoted plain scalar may not contain ``: `` (colon + space) — Pi's
    frontmatter parser rejects the whole skill in that case, so the skill is
    silently dropped from the agent's catalog. Detect it before shipping.
    """
    if skill.description_quoted:
        return None
    if ": " in skill.description or skill.description.rstrip().endswith(":"):
        return 'unquoted description contains ": " — wrap the value in double quotes'
    return None


def default_target(global_install: bool) -> Path:
    """Local default is ``./.agents/skills``; global is ``~/.agents/skills``."""
    if global_install:
        return Path.home() / ".agents" / "skills"
    return Path.cwd() / ".agents" / "skills"


def installed_version(target: Path, name: str) -> bool:
    return (target / name / "SKILL.md").is_file()


# --- Pi (pi.dev) project-trust integration ---------------------------------
#
# Pi discovers project-level ``.agents/skills`` only after the working
# directory has been granted *project trust* (a saved decision in
# ``~/.pi/agent/trust.json`` mapping a canonical directory to ``true``).
# Without it, Pi silently skips every installed skill — the most common
# reason skills "do not work" with Pi.  Registering a trust decision for the
# project directory fixes discovery on the next Pi start.

TRUST_TRUE = True


def pi_agent_dir() -> Path:
    """Pi's agent configuration directory (honours PI_CONFIG_DIR when set)."""
    override = os.environ.get("PI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".pi" / "agent"


def pi_installed() -> bool:
    """Heuristic: Pi is present when its agent directory exists."""
    return pi_agent_dir().is_dir()


def trust_file() -> Path:
    return pi_agent_dir() / "trust.json"


def read_pi_trust() -> dict[str, bool]:
    """Read Pi's saved project-trust decisions (empty when absent)."""
    path = trust_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, bool)} if isinstance(data, dict) else {}


def register_pi_trust(project_dir: Path, *, trusted: bool = True) -> bool:
    """Save a project-trust decision for ``project_dir`` in Pi's trust store.

    Returns ``True`` when the decision was written (or already existed).
    """
    canonical = str(project_dir.resolve())
    decisions = read_pi_trust()
    if decisions.get(canonical) is trusted:
        return True
    decisions[canonical] = trusted
    path = trust_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decisions, indent=2) + "\n", encoding="utf-8")
    return True


def pi_trust_decision(project_dir: Path) -> bool | None:
    """Return Pi's saved decision for ``project_dir`` (None = not decided)."""
    return read_pi_trust().get(str(project_dir.resolve()))


def install_skills(
    target: Path,
    *,
    names: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    """Copy bundled skills into ``target``.

    Returns ``(installed, skipped)`` skill names.  A skill is skipped when it
    already exists and ``force`` is false, or when it is not in ``names``.
    """
    wanted = {n.strip() for n in (names or []) if n and n.strip()}
    installed: list[str] = []
    skipped: list[str] = []
    for skill in bundled_skills():
        if wanted and skill.name not in wanted:
            skipped.append(skill.name)
            continue
        destination = target / skill.name
        if destination.exists() and not force:
            skipped.append(skill.name)
            continue
        if not dry_run:
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(skill.source, destination)
        installed.append(skill.name)
    unknown = wanted - {s.name for s in bundled_skills()}
    if unknown:
        raise KeyError(f"Unknown skill(s): {', '.join(sorted(unknown))}")
    return installed, skipped
