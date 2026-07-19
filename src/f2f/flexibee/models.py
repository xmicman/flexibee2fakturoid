"""Pydantic models for the FlexiBee entities we migrate.

Field selection follows docs/spec.md — Field Mapping. Only columns actually
used by the mapper are modelled; the source tables have ~100-200 columns
each, most irrelevant to this migration.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, field_validator


def _clean_row(row: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k in fields}


class FlexContact(BaseModel):
    """A row from `aadresar` — suppliers and customers share this table."""

    idfirmy: int
    kod: str
    nazev: str
    ic: str | None = None
    dic: str | None = None
    email: str | None = None
    tel: str | None = None
    ulice: str | None = None
    mesto: str | None = None
    psc: str | None = None
    idfastatu: int | None = None
    typvztahuk: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FlexContact:
        return cls(**_clean_row(row, set(cls.model_fields)))


class FlexInvoiceLine(BaseModel):
    """A row from `dpolfak` — invoice line items."""

    iddoklfak: int
    nazev: str | None = None  # observed NULL in real data — see mapper for fallback
    mnozmj: Decimal
    cenamj: Decimal
    szbdph: Decimal

    @field_validator("mnozmj", "cenamj", "szbdph", mode="before")
    @classmethod
    def _to_decimal(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        return Decimal(str(value))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FlexInvoiceLine:
        return cls(**_clean_row(row, set(cls.model_fields)))


class FlexInvoice(BaseModel):
    """A row from `ddoklfak` filtered to `modul in ('FAV', 'FAP')`.

    `modul` distinguishes issued (FAV) from received (FAP) invoices — both
    live in the same table. Currency and payment status are resolved via FK
    (`idmeny`, `stavuhrk`), not a plain text column, despite earlier drafts
    of this spec assuming a `mena` column that does not exist in the real
    schema.
    """

    iddoklfak: int
    kod: str
    modul: str
    datvyst: date
    datsplat: date | None = None
    duzppuv: date | None = None
    datuhr: date | None = None
    idfirmy: int | None = None
    varsym: str | None = None
    sumcelkem: Decimal
    idmeny: int | None = None
    idtypdokl: int | None = None
    storno: bool = False
    stavuhrk: str | None = None

    @field_validator("sumcelkem", mode="before")
    @classmethod
    def _to_decimal(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        return Decimal(str(value))

    @field_validator("storno", mode="before")
    @classmethod
    def _to_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        return value == "t"

    @field_validator("datvyst", "datsplat", "duzppuv", "datuhr", mode="before")
    @classmethod
    def _to_date(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        # Defensive: dates observed as plain YYYY-MM-DD, but truncate any
        # accidental time component rather than fail parsing.
        return date.fromisoformat(str(value)[:10])

    @property
    def is_paid(self) -> bool:
        return self.stavuhrk is not None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FlexInvoice:
        return cls(**_clean_row(row, set(cls.model_fields)))
