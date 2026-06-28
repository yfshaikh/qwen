"""Render sweep/behavior results as markdown + CSV, plus the demo headline line."""
from __future__ import annotations

import csv
import io
from typing import Any


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def render_markdown(rows: list[dict], *, target: str, best: dict) -> str:
    cols = _columns(rows)
    out = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for r in rows:
        cells = [f"{r.get(c, '')}" for c in cols]
        if r is best or (best and all(r.get(k) == v for k, v in best.items())):
            cells[0] += " ⭐"
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def render_csv(rows: list[dict]) -> str:
    cols = _columns(rows)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue().strip() + "\n"


def headline(on: dict[str, Any], baseline: dict[str, Any]) -> str:
    return (
        "With memory: re-explanation-rate "
        f"{on['re_explanation_rate']:.2f} vs baseline "
        f"{baseline['re_explanation_rate']:.2f}; "
        f"preference-honored {on['preference_honored_rate']:.2f} vs "
        f"{baseline['preference_honored_rate']:.2f}."
    )
