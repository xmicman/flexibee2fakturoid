"""A minimal stand-in for pgdumplib.Dump, used so backup.py can be unit
tested without a real .winstrom-backup file (see CLAUDE.md — no real
backup ever gets committed).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeEntry:
    copy_stmt: str | None


class FakeDump:
    def __init__(self, tables: dict[str, tuple[list[str], list[tuple[object, ...]]]]) -> None:
        """`tables` maps table name -> (column_names, rows)."""
        self._tables = tables

    def lookup_entry(self, desc: str, namespace: str, tag: str) -> FakeEntry | None:
        if tag not in self._tables:
            return None
        columns, _ = self._tables[tag]
        return FakeEntry(copy_stmt=f"COPY {namespace}.{tag} ({', '.join(columns)}) FROM stdin;")

    def table_data(self, namespace: str, table: str):
        _, rows = self._tables[table]
        yield from rows
