"""Orchestrates a migration run: build a plan, print a dry-run report, and
(only with --yes) apply it against Fakturoid while recording a run log.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

import httpx
from pgdumplib.dump import Dump
from rich.console import Console
from rich.table import Table

from f2f.fakturoid.client import FakturoidClient, FakturoidError
from f2f.flexibee import backup
from f2f.flexibee.models import FlexContact, FlexInvoice, FlexInvoiceLine
from f2f.migration.mapper import (
    ContactMigrationPlan,
    InvoiceMigrationPlan,
    plan_contacts_migration,
    plan_invoices_migration,
)
from f2f.migration.run_log import RunLog

console = Console()


def load_contacts(dump: Dump) -> list[FlexContact]:
    return [FlexContact.from_row(row) for row in backup.rows(dump, "aadresar")]


def load_country_lookup(dump: Dump) -> dict[str, str]:
    return backup.lookup_table(dump, "astaty", "idstatu", "kod")


def load_currency_lookup(dump: Dump) -> dict[str, str]:
    return backup.lookup_table(dump, "umeny", "idmeny", "kod")


def load_invoices(dump: Dump, modul: str) -> list[FlexInvoice]:
    return [
        FlexInvoice.from_row(row)
        for row in backup.rows(dump, "ddoklfak")
        if row.get("modul") == modul
    ]


def load_invoice_lines(dump: Dump) -> dict[int, list[FlexInvoiceLine]]:
    lines_by_invoice: dict[int, list[FlexInvoiceLine]] = defaultdict(list)
    for row in backup.rows(dump, "dpolfak"):
        line = FlexInvoiceLine.from_row(row)
        lines_by_invoice[line.iddoklfak].append(line)
    return lines_by_invoice


def build_idfirmy_to_subject_id(
    contacts: list[FlexContact], existing_subjects: list[dict[str, object]]
) -> dict[int, int]:
    """Resolve FlexiBee's numeric contact id to a Fakturoid subject id via
    IČO — invoices reference `idfirmy`, Fakturoid subjects are matched by
    `registration_no`. Requires contacts to already exist in Fakturoid
    (run the contacts migration first)."""
    subject_id_by_registration_no = {
        s["registration_no"]: s["id"] for s in existing_subjects if s.get("registration_no")
    }
    result: dict[int, int] = {}
    for contact in contacts:
        if not contact.ic:
            continue
        subject_id = subject_id_by_registration_no.get(contact.ic.strip())
        if subject_id is not None:
            result[contact.idfirmy] = subject_id
    return result


def print_contact_plan(plan: ContactMigrationPlan) -> None:
    table = Table(title="Kontakty")
    table.add_column("Akce")
    table.add_column("Počet", justify="right")
    table.add_row("K vytvoření", str(len(plan.to_create)))
    table.add_row("Přeskočeno (už existuje ve Fakturoidu)", str(len(plan.to_skip_existing)))
    table.add_row("Přeskočeno (institucionální kontakt)", str(len(plan.to_skip_institutional)))
    console.print(table)
    if plan.no_dedup_key_warning:
        console.print(
            f"[yellow]Pozor:[/yellow] {len(plan.no_dedup_key_warning)} kontaktů bez IČO — "
            "nelze bezpečně deduplikovat, opakovaný běh je může vytvořit znovu."
        )


async def build_contact_plan(
    client: FakturoidClient,
    contacts: list[FlexContact],
    country_lookup: dict[str, str],
    include_institutional: bool = False,
    existing_subjects: list[dict[str, object]] | None = None,
) -> ContactMigrationPlan:
    if existing_subjects is None:
        existing_subjects = await client.list_subjects()
    existing_registration_nos = {
        s["registration_no"] for s in existing_subjects if s.get("registration_no")
    }
    return plan_contacts_migration(
        contacts, country_lookup, existing_registration_nos, include_institutional
    )


async def apply_contact_plan(
    client: FakturoidClient, plan: ContactMigrationPlan, run_log: RunLog
) -> int:
    created_count = 0
    for contact, subject in plan.to_create:
        created = await client.create_subject(subject.model_dump(exclude_none=True))
        run_log.record("subject", created["id"], str(contact.idfirmy))
        created_count += 1
    return created_count


def print_invoice_plan(plan: InvoiceMigrationPlan, title: str) -> None:
    table = Table(title=title)
    table.add_column("Akce")
    table.add_column("Počet", justify="right")
    table.add_row("K vytvoření", str(len(plan.to_create)))
    table.add_row("Přeskočeno (už existuje ve Fakturoidu)", str(len(plan.to_skip_existing)))
    table.add_row("Přeskočeno (stornováno)", str(len(plan.to_skip_storno)))
    table.add_row("Přeskočeno (kontakt chybí ve Fakturoidu)", str(len(plan.to_skip_missing_subject)))
    console.print(table)
    if plan.to_skip_missing_subject:
        console.print(
            "[yellow]Pozor:[/yellow] některé faktury odkazují na kontakt, který ve Fakturoidu "
            "ještě neexistuje — spusť napřed migraci kontaktů (--only contacts)."
        )


async def build_invoice_plan(
    client: FakturoidClient,
    invoices: list[FlexInvoice],
    lines_by_invoice: dict[int, list[FlexInvoiceLine]],
    idfirmy_to_subject_id: dict[int, int],
    currency_lookup: dict[str, str],
    modul: str,
    since: date | None,
    until: date | None,
) -> InvoiceMigrationPlan:
    existing = (
        await client.list_invoices() if modul == "FAV" else await client.list_inbox_invoices()
    )
    existing_numbers = {inv["number"] for inv in existing if inv.get("number")}
    return plan_invoices_migration(
        invoices,
        lines_by_invoice,
        idfirmy_to_subject_id,
        currency_lookup,
        existing_numbers,
        since,
        until,
    )


async def apply_invoice_plan(
    client: FakturoidClient, plan: InvoiceMigrationPlan, run_log: RunLog, modul: str
) -> int:
    entity_type = "invoice" if modul == "FAV" else "inbox_invoice"
    created_count = 0
    for invoice, payload in plan.to_create:
        body = payload.model_dump(mode="json", exclude_none=True)
        created = (
            await client.create_invoice(body)
            if modul == "FAV"
            else await client.create_inbox_invoice(body)
        )
        run_log.record(entity_type, created["id"], str(invoice.iddoklfak))
        created_count += 1
    return created_count


def print_run_log_summary(run_log: RunLog, title: str) -> None:
    counts = Counter(record.entity_type for record in run_log.created)
    table = Table(title=title)
    table.add_column("Typ záznamu")
    table.add_column("Počet", justify="right")
    for entity_type, count in sorted(counts.items()):
        table.add_row(entity_type, str(count))
    table.add_row("celkem", str(len(run_log.created)), style="bold")
    console.print(table)


_DELETE_METHOD_BY_ENTITY_TYPE = {
    "subject": "delete_subject",
    "invoice": "delete_invoice",
    "inbox_invoice": "delete_inbox_invoice",
}


async def apply_rollback(client: FakturoidClient, run_log: RunLog) -> tuple[int, list[str]]:
    """Delete exactly what `run_log` recorded as created — nothing else.
    Continues past individual failures (e.g. already deleted by hand) and
    reports them instead of aborting the whole rollback. See
    docs/spec.md#rollback--failure-recovery.
    """
    deleted = 0
    failures: list[str] = []
    for record in run_log.created:
        delete_fn = getattr(client, _DELETE_METHOD_BY_ENTITY_TYPE[record.entity_type])
        try:
            await delete_fn(record.fakturoid_id)
            deleted += 1
        except (httpx.HTTPStatusError, FakturoidError) as exc:
            failures.append(f"{record.entity_type} {record.fakturoid_id}: {exc}")
    return deleted, failures
