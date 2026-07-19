"""Reading FlexiBee .winstrom-backup files (PostgreSQL custom-format dumps).

Uses pgdumplib to read the dump directly, without needing pg_restore or a
running PostgreSQL server. See docs/spec.md for why the backup is a Postgres
dump rather than the ZIP+XML originally assumed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pgdumplib
from pgdumplib.dump import Dump

_COPY_COLUMNS_RE = re.compile(r"\((.*?)\)\s*FROM", re.S)


def load(path: str | Path) -> Dump:
    """Load a .winstrom-backup file."""
    return pgdumplib.load(str(path))


def columns_for(dump: Dump, table: str, namespace: str = "public") -> list[str]:
    """Return the column names for `table`, in the order pgdumplib yields row values."""
    entry = dump.lookup_entry("TABLE DATA", namespace, table)
    if entry is None or not entry.copy_stmt:
        raise ValueError(f"No COPY statement found for table {namespace}.{table}")
    match = _COPY_COLUMNS_RE.search(entry.copy_stmt)
    if not match:
        raise ValueError(f"Could not parse columns from COPY statement for {table}")
    return [c.strip() for c in match.group(1).split(",")]


def rows(dump: Dump, table: str, namespace: str = "public") -> Iterator[dict[str, object]]:
    """Yield rows of `table` as dicts keyed by column name."""
    columns = columns_for(dump, table, namespace)
    for row in dump.table_data(namespace, table):
        yield dict(zip(columns, row, strict=True))


def lookup_table(
    dump: Dump, table: str, key_column: str, value_column: str, namespace: str = "public"
) -> dict[str, str]:
    """Build a `key_column -> value_column` dict from a reference table.

    Used to resolve FKs like `aadresar.idfastatu -> astaty.kod` or
    `ddoklfak.idmeny -> umeny.kod` without a second pass over the dump.
    """
    return {
        str(row[key_column]): row[value_column]
        for row in rows(dump, table, namespace)
        if row.get(key_column) is not None
    }
