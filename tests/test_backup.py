from __future__ import annotations

import pytest

from f2f.flexibee import backup

from .fixtures.fake_dump import FakeDump


@pytest.fixture
def fake_dump() -> FakeDump:
    return FakeDump(
        {
            "aadresar": (
                ["idfirmy", "kod", "nazev"],
                [(1, "FIRMA001", "Firma s.r.o."), (2, "FIRMA002", "Jiná firma a.s.")],
            ),
            "astaty": (
                ["idstatu", "kod"],
                [(1, "CZ"), (2, "SK")],
            ),
        }
    )


def test_columns_for_parses_copy_statement(fake_dump: FakeDump) -> None:
    assert backup.columns_for(fake_dump, "aadresar") == ["idfirmy", "kod", "nazev"]


def test_columns_for_unknown_table_raises(fake_dump: FakeDump) -> None:
    with pytest.raises(ValueError, match="No COPY statement"):
        backup.columns_for(fake_dump, "nope")


def test_rows_yields_dicts_keyed_by_column(fake_dump: FakeDump) -> None:
    rows = list(backup.rows(fake_dump, "aadresar"))
    assert rows == [
        {"idfirmy": 1, "kod": "FIRMA001", "nazev": "Firma s.r.o."},
        {"idfirmy": 2, "kod": "FIRMA002", "nazev": "Jiná firma a.s."},
    ]


def test_lookup_table_builds_key_value_dict(fake_dump: FakeDump) -> None:
    assert backup.lookup_table(fake_dump, "astaty", "idstatu", "kod") == {"1": "CZ", "2": "SK"}
