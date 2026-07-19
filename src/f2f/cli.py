from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from f2f.fakturoid.client import DEFAULT_BASE_URL, FakturoidClient
from f2f.flexibee import backup
from f2f.flexibee.models import FlexContact, FlexInvoice
from f2f.migration.run_log import RunLog
from f2f.migration.runner import apply_contact_plan, build_contact_plan, load_country_lookup, print_contact_plan
from f2f.migration.runner import load_contacts as load_flex_contacts

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """flexibee2fakturoid — migrace dat z FlexiBee do Fakturoidu."""


@app.command()
def inspect(
    backup_path: Path = typer.Argument(..., exists=True, readable=True, help="Cesta k .winstrom-backup souboru"),
) -> None:
    """Ukaž, co záloha obsahuje — počty entit a vzorový záznam každého typu. Bez importu."""
    dump = backup.load(backup_path)

    contacts = [FlexContact.from_row(row) for row in backup.rows(dump, "aadresar")]
    invoice_rows = list(backup.rows(dump, "ddoklfak"))
    issued = [FlexInvoice.from_row(row) for row in invoice_rows if row.get("modul") == "FAV"]
    received = [FlexInvoice.from_row(row) for row in invoice_rows if row.get("modul") == "FAP"]

    table = Table(title=f"Obsah zálohy: {backup_path.name}")
    table.add_column("Entita")
    table.add_column("Počet", justify="right")
    table.add_row("Kontakty (aadresar)", str(len(contacts)))
    table.add_row("Vydané faktury (FAV)", str(len(issued)))
    table.add_row("Přijaté faktury (FAP)", str(len(received)))
    console.print(table)

    if contacts:
        console.print("\n[bold]Vzorový kontakt:[/bold]")
        console.print(contacts[0].model_dump())
    if issued:
        console.print("\n[bold]Vzorová vydaná faktura:[/bold]")
        console.print(issued[0].model_dump())
    if received:
        console.print("\n[bold]Vzorová přijatá faktura:[/bold]")
        console.print(received[0].model_dump())


def _resolve_token(fakturoid_token: str | None) -> str:
    if fakturoid_token:
        return fakturoid_token
    env_token = os.environ.get("FAKTUROID_TOKEN")
    if env_token:
        return env_token
    return typer.prompt("Fakturoid token", hide_input=True)


@app.command()
def migrate(
    backup_path: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Cesta k .winstrom-backup souboru")
    ],
    fakturoid_slug: Annotated[str, typer.Option("--fakturoid-slug", help="Slug Fakturoid účtu")],
    fakturoid_token: Annotated[
        str | None,
        typer.Option("--fakturoid-token", help="PAT token. Bez zadání: FAKTUROID_TOKEN env, jinak interaktivní prompt."),
    ] = None,
    fakturoid_base_url: Annotated[
        str,
        typer.Option(
            "--fakturoid-base-url",
            hidden=True,
            help="Jen pro testy proti mock serveru — v produkci se nikdy nenastavuje.",
        ),
    ] = DEFAULT_BASE_URL,
    only: Annotated[
        str | None, typer.Option("--only", help="contacts (zatím jediná implementovaná entita)")
    ] = None,
    include_institutional_contacts: Annotated[
        bool,
        typer.Option(
            "--include-institutional-contacts",
            help="Zahrnout kontakty jako zdravotní pojišťovnu/OSSZ/finanční úřad (ve výchozím stavu se přeskakují, viz Open Question Q7).",
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="Skutečně zapsat do Fakturoidu. Bez tohoto je běh vždy jen dry-run.")
    ] = False,
) -> None:
    """Migruj data ze zálohy do Fakturoidu. Bez --yes vždy jen dry-run report."""
    if only is not None and only != "contacts":
        console.print(f"[red]--only {only} zatím není implementováno.[/red] Podporováno: contacts")
        raise typer.Exit(code=1)

    token = _resolve_token(fakturoid_token)
    dump = backup.load(backup_path)
    contacts = load_flex_contacts(dump)
    country_lookup = load_country_lookup(dump)

    asyncio.run(
        _migrate_contacts_async(
            contacts=contacts,
            country_lookup=country_lookup,
            slug=fakturoid_slug,
            token=token,
            base_url=fakturoid_base_url,
            include_institutional=include_institutional_contacts,
            apply=yes,
        )
    )


async def _migrate_contacts_async(
    contacts: list[FlexContact],
    country_lookup: dict[str, str],
    slug: str,
    token: str,
    base_url: str,
    include_institutional: bool,
    apply: bool,
) -> None:
    async with FakturoidClient(slug=slug, token=token, base_url=base_url) as client:
        plan = await build_contact_plan(client, contacts, country_lookup, include_institutional)
        print_contact_plan(plan)

        if not apply:
            console.print("\n[dim]Dry-run — nic nebylo zapsáno. Spusť s --yes pro reálný import.[/dim]")
            return

        run_log = RunLog.start(slug)
        created_count = await apply_contact_plan(client, plan, run_log)
        run_log_path = run_log.save()
        console.print(f"\n[green]Hotovo.[/green] Vytvořeno {created_count} kontaktů.")
        console.print(f"Run log: {run_log_path} (run-id: {run_log.run_id}, pro rollback)")


if __name__ == "__main__":
    app()
