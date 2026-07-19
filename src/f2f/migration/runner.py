"""Orchestrates a migration run: build a plan, print a dry-run report, and
(only with --yes) apply it against Fakturoid while recording a run log.
"""

from __future__ import annotations

from pgdumplib.dump import Dump
from rich.console import Console
from rich.table import Table

from f2f.fakturoid.client import FakturoidClient
from f2f.flexibee import backup
from f2f.flexibee.models import FlexContact
from f2f.migration.mapper import ContactMigrationPlan, plan_contacts_migration
from f2f.migration.run_log import RunLog

console = Console()


def load_contacts(dump: Dump) -> list[FlexContact]:
    return [FlexContact.from_row(row) for row in backup.rows(dump, "aadresar")]


def load_country_lookup(dump: Dump) -> dict[str, str]:
    return backup.lookup_table(dump, "astaty", "idstatu", "kod")


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
) -> ContactMigrationPlan:
    existing = await client.list_subjects()
    existing_registration_nos = {
        s["registration_no"] for s in existing if s.get("registration_no")
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
