"""Allow ``python -m minics``."""

from __future__ import annotations

from minics.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
