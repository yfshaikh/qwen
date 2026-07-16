"""The benchmark is the referee. This test is what stops the players editing it.

WHY THIS EXISTS
em-frozen-v1 is handed to an agent with "make these checks pass". Two paths lead
there: fix Engram's dedup, or widen `max_concepts` to 15. The second is one line
and always works. An agent that has failed the first way three times will find the
second — not from malice, but because "adjust accordingly" is exactly what it was
told to do, and nothing in the repo says the fixture is off-limits. The YAML says
READ-ONLY-TO-AUTOMATION in a comment; comments do not enforce.

Ground truth and the code that reads it are therefore pinned by digest. Editing
either fails the suite loudly, in the same run that would otherwise have gone
green. This does not prevent an edit — nothing can, an agent with write access can
edit this file too — it makes the edit IMPOSSIBLE TO MISS in a diff nobody was
going to read closely.

WHEN THIS FAILS ON YOU
If you changed ground truth deliberately — recalibrated an alias, added a check,
retuned a cap — then update PINNED below to the digest printed in the failure. That
is a two-second edit, and being deliberate about it is the entire point: it is a
decision about what "correct" means, and it belongs to a human, not to whatever is
iterating this week.
"""
from __future__ import annotations

import hashlib
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "eval" / "scenarios"
# Both frozen benchmarks. The holdout is covered for the same reason as the main
# fixture, and more so: it is the only thing that can tell "Engram improved" from
# "Engram memorised em-frozen-v1", and it is the one file whose edits nobody would
# be watching for.
FIXTURES = [SCENARIOS / "em-frozen-v1.yaml", SCENARIOS / "sat-linear-holdout-v1.yaml"]
CHECKS = ROOT / "src" / "engram" / "eval" / "checks"

# Update ONLY when changing ground truth on purpose. See module docstring.
PINNED = "a8efb2a6112727f904f44d7937147349c371eaab02347413c7afccddfb0d9c08"


def _digest() -> tuple[str, list[str]]:
    """Digest of the fixture + every check module, and the files covered.

    Filenames are hashed alongside contents so that deleting a check — the other
    way to make it stop failing — moves the digest too.
    """
    h = hashlib.sha256()
    covered: list[str] = []
    for p in FIXTURES + sorted(CHECKS.glob("*.py")):
        rel = str(p.relative_to(ROOT))
        covered.append(rel)
        h.update(rel.encode())
        h.update(p.read_bytes())
    return h.hexdigest(), covered


def test_benchmark_ground_truth_is_unmodified():
    got, covered = _digest()
    assert got == PINNED, (
        "\n\nThe benchmark's ground truth or check code changed.\n\n"
        f"  expected: {PINNED}\n"
        f"  actual:   {got}\n\n"
        f"Covered ({len(covered)} files):\n  " + "\n  ".join(covered) + "\n\n"
        "If you are an agent iterating on Engram: you are meant to change Engram, "
        "not the checks that grade it. Widening a threshold or dropping an "
        "assertion makes the number go green while the bug ships. Revert your edit "
        "here and fix the code under test.\n\n"
        "If you are a human changing ground truth on purpose: set PINNED to the "
        "actual digest above.\n"
    )
