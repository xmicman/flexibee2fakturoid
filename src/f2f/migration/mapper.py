"""FlexiBee -> Fakturoid field mapping and migration planning (dedup).

See docs/spec.md — Field Mapping for the source of these mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from f2f.fakturoid.models import Expense, Invoice, InvoiceLine, Subject
from f2f.flexibee.models import FlexContact, FlexInvoice, FlexInvoiceLine

# typvztahuk values observed in real data for institutional contacts
# (health insurance, social security, tax office) rather than actual
# customers/suppliers. See docs/spec.md Open Questions Q7 — excluded by
# default, override with --include-institutional-contacts.
INSTITUTIONAL_RELATION_TYPES = {
    "typVztahu.zdravotka",
    "typVztahu.socialka",
    "typVztahu.financniUrad",
}


def is_institutional_contact(contact: FlexContact) -> bool:
    return contact.typvztahuk in INSTITUTIONAL_RELATION_TYPES


def _clean_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip()
    # Legacy records observed with a stray "EMAIL" prefix, e.g.
    # " EMAILinfo@vzp.cz" — see docs/spec.md Field Mapping notes.
    if cleaned.upper().startswith("EMAIL"):
        cleaned = cleaned[len("EMAIL") :]
    return cleaned.strip() or None


def map_contact(contact: FlexContact, country_lookup: dict[str, str]) -> Subject:
    country = country_lookup.get(str(contact.idfastatu)) if contact.idfastatu is not None else None
    return Subject(
        name=contact.nazev.strip(),
        registration_no=contact.ic.strip() if contact.ic else None,
        vat_no=contact.dic.strip() if contact.dic else None,
        email=_clean_email(contact.email),
        phone=contact.tel.strip() if contact.tel else None,
        street=contact.ulice.strip() if contact.ulice else None,
        city=contact.mesto.strip() if contact.mesto else None,
        zip=contact.psc.strip() if contact.psc else None,
        country=country,
    )


@dataclass
class ContactMigrationPlan:
    to_create: list[tuple[FlexContact, Subject]] = field(default_factory=list)
    to_skip_existing: list[FlexContact] = field(default_factory=list)
    to_skip_institutional: list[FlexContact] = field(default_factory=list)
    no_dedup_key_warning: list[FlexContact] = field(default_factory=list)


def plan_contacts_migration(
    contacts: list[FlexContact],
    country_lookup: dict[str, str],
    existing_registration_nos: set[str],
    include_institutional: bool = False,
) -> ContactMigrationPlan:
    """Decide what to create/skip. Does not talk to the network — the
    caller fetches `existing_registration_nos` once via
    `FakturoidClient.list_subjects()`, not per contact.
    """
    plan = ContactMigrationPlan()
    seen_in_this_run: set[str] = set()
    for contact in contacts:
        if not include_institutional and is_institutional_contact(contact):
            plan.to_skip_institutional.append(contact)
            continue

        dedup_key = contact.ic.strip() if contact.ic else None
        if not dedup_key:
            plan.no_dedup_key_warning.append(contact)
        elif dedup_key in existing_registration_nos or dedup_key in seen_in_this_run:
            plan.to_skip_existing.append(contact)
            continue
        else:
            seen_in_this_run.add(dedup_key)

        plan.to_create.append((contact, map_contact(contact, country_lookup)))
    return plan


def _normalize_invoice_number(kod: str) -> str:
    """Fakturoid number formats only allow digits, A-Z, and a hyphen — no
    slash. FlexiBee numbers observed as e.g. "VF1-0009/2024" or
    "F0083/23"; confirmed live (2026-07-19) that "/" makes number
    validation fail against a configured number_format. "-" is the
    closest allowed substitute. See docs/spec.md Open Question Q3."""
    return kod.replace("/", "-")


def map_invoice_line(line: FlexInvoiceLine) -> InvoiceLine:
    # nazev observed NULL in real data (e.g. old records with no line
    # description) — Fakturoid requires a non-empty name.
    name = line.nazev.strip() if line.nazev else "(bez názvu)"
    return InvoiceLine(
        name=name or "(bez názvu)",
        quantity=line.mnozmj,
        unit_price=line.cenamj,
        vat_rate=line.szbdph,
    )


def map_invoice_lines(lines: list[FlexInvoiceLine]) -> list[InvoiceLine]:
    """Fakturoid requires quantity > 0 — confirmed live (2026-07-19):
    a zero-quantity "Zaokrouhleno" (rounding) line from FlexiBee got
    422'd. Observed with unit_price=0 too, so dropping it doesn't lose
    any monetary value; the actual rounding is already reflected in the
    document's header totals, not in this line."""
    return [map_invoice_line(line) for line in lines if line.mnozmj != 0]


def map_issued_invoice(
    invoice: FlexInvoice,
    lines: list[FlexInvoiceLine],
    subject_id: int,
    currency_lookup: dict[str, str],
    number_format_id: int | None = None,
) -> Invoice:
    """FAV -> POST /invoices.json payload. Payment status is NOT included
    here — Fakturoid marks a document paid via a separate payments call,
    see apply_invoice_plan. `due` is a day-count, not a date — see
    Invoice model docstring.

    `number_format_id` must be passed explicitly if the account has more
    than one number format — see Invoice model docstring for why."""
    currency = currency_lookup.get(str(invoice.idmeny)) if invoice.idmeny is not None else None
    due = (invoice.datsplat - invoice.datvyst).days if invoice.datsplat else None
    return Invoice(
        number=_normalize_invoice_number(invoice.kod),
        subject_id=subject_id,
        issued_on=invoice.datvyst,
        due=due,
        taxable_fulfillment_due=invoice.duzppuv,
        variable_symbol=invoice.varsym,
        currency=currency,
        number_format_id=number_format_id,
        lines=map_invoice_lines(lines),
    )


def map_received_expense(
    invoice: FlexInvoice,
    lines: list[FlexInvoiceLine],
    subject_id: int,
    currency_lookup: dict[str, str],
) -> Expense:
    """FAP -> POST /expenses.json payload. `received_on` has no distinct
    source field in FlexiBee's ddoklfak — defaults to `datvyst` (issue
    date) as the best available approximation.

    No `number` — see Expense model docstring for why. Original FlexiBee
    number goes in `custom_id` (raw, not normalized — no format
    constraint applies to a free-text field)."""
    currency = currency_lookup.get(str(invoice.idmeny)) if invoice.idmeny is not None else None
    return Expense(
        subject_id=subject_id,
        issued_on=invoice.datvyst,
        received_on=invoice.datvyst,
        due_on=invoice.datsplat,
        variable_symbol=invoice.varsym,
        currency=currency,
        custom_id=invoice.kod,
        lines=map_invoice_lines(lines),
    )


@dataclass
class InvoiceMigrationPlan:
    to_create: list[tuple[FlexInvoice, Invoice | Expense]] = field(default_factory=list)
    to_skip_existing: list[FlexInvoice] = field(default_factory=list)
    to_skip_storno: list[FlexInvoice] = field(default_factory=list)
    to_skip_missing_subject: list[FlexInvoice] = field(default_factory=list)


def plan_invoices_migration(
    invoices: list[FlexInvoice],
    lines_by_invoice: dict[int, list[FlexInvoiceLine]],
    idfirmy_to_subject_id: dict[int, int],
    currency_lookup: dict[str, str],
    existing_dedup_keys: set[str],
    modul: str,
    since: date | None = None,
    until: date | None = None,
    number_format_id: int | None = None,
) -> InvoiceMigrationPlan:
    """Decide what to create/skip for issued (modul='FAV') or received
    (modul='FAP') invoices.

    `since`/`until` scope the run to a date window on `datvyst` (see
    docs/spec.md#cutover-strategie-postupný-import) — invoices outside the
    window are silently excluded from the plan entirely, not counted as
    "skipped", since they are simply out of scope for this run.

    `idfirmy_to_subject_id` must come from a single upfront lookup (built
    by the caller from FlexiBee contacts + a cached Fakturoid subjects
    list), not a per-invoice API call — see docs/spec.md#idempotence.

    `number_format_id` (issued invoices only — see Invoice model
    docstring) selects which of the account's number formats to validate
    `number` against, if there's more than one.
    """
    plan = InvoiceMigrationPlan()
    seen_in_this_run: set[str] = set()
    # Processed oldest-issued-first: source table order from pgdumplib is
    # not chronological, and it's safest to create sequence-numbered
    # documents in the order their numbers imply.
    for invoice in sorted(invoices, key=lambda i: (i.datvyst, i.kod)):
        if since is not None and invoice.datvyst < since:
            continue
        if until is not None and invoice.datvyst >= until:
            continue

        if invoice.storno:
            plan.to_skip_storno.append(invoice)
            continue

        # FAV dedups on the normalized `number` (Fakturoid stores "-" not
        # "/"). FAP has no controllable `number` (see Expense model
        # docstring) — dedups on `custom_id` (raw, unnormalized) instead.
        dedup_key = _normalize_invoice_number(invoice.kod) if modul == "FAV" else invoice.kod
        if dedup_key in existing_dedup_keys or dedup_key in seen_in_this_run:
            plan.to_skip_existing.append(invoice)
            continue

        subject_id = (
            idfirmy_to_subject_id.get(invoice.idfirmy) if invoice.idfirmy is not None else None
        )
        if subject_id is None:
            plan.to_skip_missing_subject.append(invoice)
            continue

        seen_in_this_run.add(dedup_key)
        lines = lines_by_invoice.get(invoice.iddoklfak, [])
        if modul == "FAV":
            mapped = map_issued_invoice(invoice, lines, subject_id, currency_lookup, number_format_id)
        else:
            mapped = map_received_expense(invoice, lines, subject_id, currency_lookup)
        plan.to_create.append((invoice, mapped))
    return plan
