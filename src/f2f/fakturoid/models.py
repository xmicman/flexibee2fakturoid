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
    """Payload shape for POST /accounts/{slug}/invoices.json (issued invoices).

    Verified against https://www.fakturoid.cz/api/v3/invoices (2026-07-19).
    `number` is settable, but must match the account's configured
    `number_format` or the API rejects it with "The number does not match
    the number format in the settings" — see docs/spec.md Open Question Q3.
    Payment status is NOT a field here — Fakturoid marks a document paid via
    a separate `POST .../invoices/{id}/payments.json` call, done by the
    caller after creation (see FakturoidClient.create_invoice_payment and
    migration.runner.apply_invoice_plan).

    `due` is the number of days until the invoice is overdue (relative to
    `issued_on`), not an absolute date — the API's response has a computed
    `due_on`, but create only accepts `due`.
    """

    number: str
    subject_id: int
    issued_on: date
    due: int | None = None
    taxable_fulfillment_due: date | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    lines: list[InvoiceLine] = []


class Expense(BaseModel):
    """Payload shape for POST /accounts/{slug}/expenses.json (received invoices).

    Verified against https://www.fakturoid.cz/api/v3/expenses (2026-07-19).
    Unlike Invoice, `due_on` here IS an absolute date, and the docs don't
    mention a number_format constraint on `number` for expenses. Payment
    status is likewise a separate `POST .../expenses/{id}/payments.json`
    call, not a field here.
    """

    number: str
    subject_id: int
    issued_on: date
    received_on: date | None = None
    due_on: date | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    lines: list[InvoiceLine] = []


class Payment(BaseModel):
    """Payload shape for POST .../invoices/{id}/payments.json or
    .../expenses/{id}/payments.json — how a document gets marked paid."""

    paid_on: date
