"""Import all check modules so their @check decorators register.
Consumers must `import engram.eval.checks` before resolving names."""
from engram.eval.checks import (  # noqa: F401
    abstention,
    behavior,
    concepts,
    dedup,
    edges,
    importance,
    integrity,
    knowledge_update,
    lifecycle,
    preferences,
    recall_probes,
)
