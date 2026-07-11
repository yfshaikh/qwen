"""Import all check modules so their @check decorators register.
Consumers must `import engram.eval.checks` before resolving names."""
from engram.eval.checks import behavior, dedup, importance, integrity, lifecycle, recall_probes  # noqa: F401
