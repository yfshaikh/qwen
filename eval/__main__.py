"""Allow ``python -m eval`` (delegates to the run CLI)."""

from __future__ import annotations

from eval.run import main

if __name__ == "__main__":
    raise SystemExit(main())
