"""Install the MiniCS agent skillset bundled inside the package.

The skills live as package data under ``minics/skills/`` — each skill is a
directory with a ``SKILL.md`` (YAML frontmatter with ``name`` and
``description``), the format understood by Pi, OpenCode, Codex and any other
agent that reads ``.agents/skills/``.  Installing never touches the network:
everything is copied straight from the installed ``minichat-studio`` package.
"""

from __future__ import annotations

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
        if match:
            for line in match.group(1).splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
        skills.append(BundledSkill(name=name, description=description, source=skill_dir))
    return skills


def default_target(global_install: bool) -> Path:
    """Local default is ``./.agents/skills``; global is ``~/.agents/skills``."""
    if global_install:
        return Path.home() / ".agents" / "skills"
    return Path.cwd() / ".agents" / "skills"


def installed_version(target: Path, name: str) -> bool:
    return (target / name / "SKILL.md").is_file()


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
