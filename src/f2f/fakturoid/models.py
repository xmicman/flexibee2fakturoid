from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Subject(BaseModel):
    """Payload shape for POST /accounts/{slug}/subjects.json."""

    name: str
    registration_no: str | None = None
    vat_no: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country: str | None = None


class InvoiceLine(BaseModel):
    name: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal


class Invoice(BaseModel):
    """Payload shape for POST .../invoices.json or .../inbox_invoices.json.

    `number` and `paid_on` are best-effort — see docs/spec.md Open
    Questions Q3 (whether a literal historical invoice number is
    settable) and the payment-status note in Field Mapping. Verify
    against a real Fakturoid sandbox account before the first
    production run, ideally on the small current-year cutover batch
    (see docs/spec.md#cutover-strategie-postupný-import).
    """

    number: str
    subject_id: int
    issued_on: date
    due_on: date | None = None
    taxable_fulfillment_due: date | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    paid_on: date | None = None
    lines: list[InvoiceLine] = []
