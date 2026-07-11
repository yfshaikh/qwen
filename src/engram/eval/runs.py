"""Filesystem run store: eval/runs/<id>/ holds run.json, events.jsonl,
transcript.jsonl, snapshots/. Atomic writes; corrupt dirs skipped on list."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

RUNS_DIR = Path("eval/runs")


def new_run(scenario_id: str, base_dir: Path = RUNS_DIR) -> tuple[str, Path]:
    run_id = uuid.uuid4().hex[:8]
    run_dir = Path(base_dir) / f"{scenario_id}-{run_id}"
    (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def write_run(run_dir: Path, data: dict) -> None:
    tmp = Path(run_dir) / "run.json.tmp"
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, Path(run_dir) / "run.json")


def read_run(run_dir: Path) -> dict:
    return json.loads((Path(run_dir) / "run.json").read_text())


def list_runs(base_dir: Path = RUNS_DIR) -> list[dict]:
    out: list[dict] = []
    base = Path(base_dir)
    if not base.exists():
        return out
    for d in base.iterdir():
        if d.name == "baselines" or not d.is_dir():
            continue
        try:
            out.append({**read_run(d), "dir": d.name})
        except (OSError, json.JSONDecodeError, FileNotFoundError):
            continue  # corrupt/incomplete run dir
    out.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return out


def append_event(run_dir: Path, event: dict) -> None:
    with open(Path(run_dir) / "events.jsonl", "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def read_events(run_dir: Path, after_line: int = 0) -> tuple[list[dict], int]:
    p = Path(run_dir) / "events.jsonl"
    if not p.exists():
        return [], after_line
    lines = p.read_text().splitlines()
    new = lines[after_line:]
    return [json.loads(x) for x in new if x.strip()], after_line + len(new)
