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

    `number_format_id` matters if the account has more than one number
    format (common: a default one plus a custom one for migrated
    numbers) — confirmed live (2026-07-19) that a `number` matching a
    *non-default* format still gets rejected unless `number_format_id`
    explicitly selects that format. There's no API to look this up (GET
    on number formats/generator endpoints all 404 live); find it via
    browser devtools on the "New invoice" form — the `<select
    name="invoice[number_format_id]">` element's `<option value="...">`.
    """

    number: str
    subject_id: int
    issued_on: date
    due: int | None = None
    taxable_fulfillment_due: date | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    number_format_id: int | None = None
    lines: list[InvoiceLine] = []


class Expense(BaseModel):
    """Payload shape for POST /accounts/{slug}/expenses.json (received invoices).

    Verified against https://www.fakturoid.cz/api/v3/expenses (2026-07-19).
    Unlike Invoice, `due_on` here IS an absolute date. Payment status is
    likewise a separate `POST .../expenses/{id}/payments.json` call, not
    a field here.

    Unlike Invoice, `number` is deliberately NOT set here. Confirmed live
    (2026-07-19): expenses reject a custom `number` the same way invoices
    do ("Číslo neodpovídá formátu čísla v nastavení"), but — unlike
    invoices — there is no configurable number_format for expenses (no
    such option in Fakturoid's "Náklady" UI, no number_format_id in the
    docs). Fakturoid auto-generates its own number; the original
    FlexiBee number goes in `custom_id` instead, which dedup keys off of
    (see mapper.plan_invoices_migration) since the auto-generated number
    can never match anything from the source data. This is a deliberate
    decision, not a workaround someone should "fix" later — see
    docs/spec.md Open Question Q3.
    """

    subject_id: int
    issued_on: date
    received_on: date | None = None
    due_on: date | None = None
    variable_symbol: str | None = None
    currency: str | None = None
    custom_id: str | None = None
    lines: list[InvoiceLine] = []


class Payment(BaseModel):
    """Payload shape for POST .../invoices/{id}/payments.json or
    .../expenses/{id}/payments.json — how a document gets marked paid."""

    paid_on: date
