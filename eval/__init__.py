"""Engram eval/ablation harness — deterministic, offline (no API key, no DB).

Runs the same scripted multi-session learner arc through two arms:

- **memory**: Engram's full ingest → consolidate → recall pipeline (scripted
  FakeLLM extractor + HashingEmbedder, InMemoryStorage).
- **baseline**: the naive "dump the last N raw events" context window.

and reports, per probe concept, whether each arm re-explains material the
learner already mastered and whether it surfaces prior-session context at all.
"""
