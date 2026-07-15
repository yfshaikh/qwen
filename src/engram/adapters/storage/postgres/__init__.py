"""asyncpg-backed StoragePort with pgvector.

Implements the full storage surface: event/node/edge/evidence ingest, vector
recall reads, consolidation (locking, plan application, merge), audit and
voice-session persistence, and the insight queries (mastery history, evidence
and event counts).

`PostgresStorage` is composed from per-domain mixins (each mirroring one of
the original module's banner sections): `_WritesMixin`, `_ReadsMixin`,
`_ConsolidationMixin`, `_VoiceMixin`, `_InsightsMixin`. Shared plumbing (pool
lifecycle, `_require_pool`, row->model converters) lives in `_base._Base`.
"""

from __future__ import annotations

from ._consolidation import _ConsolidationMixin
from ._insights import _InsightsMixin
from ._reads import _ReadsMixin
from ._voice import _VoiceMixin
from ._writes import _WritesMixin

# Each mixin already subclasses `_Base` (so `self._require_pool` etc. type-check
# within the mixin file itself); listing it again here would create an
# inconsistent MRO (a base can't be both first and last in C3 linearization).
# The diamond collapses to one `_Base` at the tail of PostgresStorage.__mro__.


class PostgresStorage(
    _WritesMixin,
    _ReadsMixin,
    _ConsolidationMixin,
    _VoiceMixin,
    _InsightsMixin,
):
    pass


__all__ = ["PostgresStorage"]
