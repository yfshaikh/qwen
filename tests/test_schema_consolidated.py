"""migrations/schema.sql is the consolidated fresh-install schema. It drifts
the moment someone adds migration 000N without folding it in — this test makes
that loud without needing a database: every numbered migration must be listed
in schema.sql's header, and every table/index/column a migration creates must
appear in schema.sql.
"""
import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
SCHEMA = (MIGRATIONS / "schema.sql").read_text()


def _numbered():
    return sorted(p for p in MIGRATIONS.glob("[0-9]*.sql"))


def test_every_migration_is_listed_in_the_header():
    for p in _numbered():
        assert p.name in SCHEMA, (
            f"{p.name} is not mentioned in migrations/schema.sql — fold its DDL "
            "into the consolidated schema and add it to the 'Covers:' list")


def test_every_created_object_and_column_is_present():
    ddl = "\n".join(p.read_text() for p in _numbered())
    objects = re.findall(
        r"CREATE (?:UNIQUE )?(?:TABLE|INDEX) IF NOT EXISTS (\w+)", ddl)
    columns = re.findall(
        r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", ddl)
    assert objects and columns  # the regexes must keep matching real DDL
    for name in objects:
        assert name in SCHEMA, f"object {name!r} missing from schema.sql"
    for table, col in columns:
        table_ddl = SCHEMA[SCHEMA.index(table):]
        assert re.search(rf"^\s+{col}\s", table_ddl, re.M), (
            f"column {table}.{col} missing from schema.sql")
