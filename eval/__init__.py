"""Engram ablation / EVAL harness.

A small, deterministic proof-of-concept that shows Engram's synthesized + decaying
graph memory beats a naive "dump the last N raw events" baseline on the classic
limited-context problem. No API key, no database, no network -- a scripted
``FakeLLM`` drives consolidation and a ``HashingEmbedder`` drives recall.

See :mod:`eval.harness` for the mechanics and :mod:`eval.run` for the CLI.
"""

from __future__ import annotations

from eval.harness import ArmResult, EvalResult, load_scenario, run_eval

__all__ = ["ArmResult", "EvalResult", "load_scenario", "run_eval"]
