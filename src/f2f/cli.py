from __future__ import annotations

import asyncio
import os
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from pgdumplib.dump import Dump
from rich.console import Console
from rich.table import Table

from f2f.fakturoid.client import DEFAULT_BASE_URL, FakturoidClient
from f2f.flexibee import backup
from f2f.flexibee.models import FlexContact, FlexInvoice
from f2f.migration.run_log import RunLog
from f2f.migration.runner import (
    apply_contact_plan,
    apply_invoice_plan,
    apply_rollback,
    build_contact_plan,
    build_idfirmy_to_subject_id,
    build_invoice_plan,
    load_country_lookup,
    load_currency_lookup,
    load_invoice_lines,
    load_invoices,
    print_contact_plan,
    print_invoice_plan,
    print_run_log_summary,
)
from f2f.migration.runner import load_contacts as load_flex_contacts

ONLY_CHOICES = ("contacts", "issued-invoices", "received-invoices")

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


def _resolve_fakturoid_auth(
    token: str | None, client_id: str | None, client_secret: str | None
) -> dict[str, str]:
    """Priority: explicit CLI flags > env vars > interactive PAT prompt.
    Returns kwargs for FakturoidClient(**kwargs). OAuth2 Client Credentials
    (client_id/client_secret) is Fakturoid's recommended auth for a script
    like this one — see FakturoidClient docstring."""
    if token:
        return {"token": token}
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}

    env_token = os.environ.get("FAKTUROID_TOKEN")
    if env_token:
        return {"token": env_token}

    env_client_id = os.environ.get("FAKTUROID_CLIENT_ID")
    env_client_secret = os.environ.get("FAKTUROID_SECRET")
    if env_client_id and env_client_secret:
        return {"client_id": env_client_id, "client_secret": env_client_secret}

    return {"token": typer.prompt("Fakturoid token", hide_input=True)}


def _parse_date(value: str | None, option_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        console.print(f"[red]{option_name}[/red] musí být ve formátu YYYY-MM-DD, dostal jsem {value!r}")
        raise typer.Exit(code=1) from exc


@app.command()
def migrate(
    backup_path: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Cesta k .winstrom-backup souboru")
    ],
    fakturoid_slug: Annotated[str, typer.Option("--fakturoid-slug", help="Slug Fakturoid účtu")],
    fakturoid_token: Annotated[
        str | None,
        typer.Option("--fakturoid-token", help="PAT token. Alternativa k --fakturoid-client-id/--fakturoid-client-secret."),
    ] = None,
    fakturoid_client_id: Annotated[
        str | None,
        typer.Option("--fakturoid-client-id", help="OAuth2 Client Credentials — spolu s --fakturoid-client-secret."),
    ] = None,
    fakturoid_client_secret: Annotated[
        str | None, typer.Option("--fakturoid-client-secret", help="Viz --fakturoid-client-id.")
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
        str | None,
        typer.Option("--only", help="contacts | issued-invoices | received-invoices. Bez zadání: všechno."),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Faktury s datvyst >= tomuto datu (YYYY-MM-DD). Netýká se kontaktů."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Faktury s datvyst < tomuto datu (YYYY-MM-DD). Netýká se kontaktů."),
    ] = None,
    number_format_id: Annotated[
        int | None,
        typer.Option(
            "--number-format-id",
            help="ID číselné řady vydaných faktur ve Fakturoidu — nutné, pokud má účet víc než jednu (viz Invoice model docstring, jak ID zjistit).",
        ),
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
    if only is not None and only not in ONLY_CHOICES:
        console.print(f"[red]--only {only} není platná hodnota.[/red] Podporováno: {', '.join(ONLY_CHOICES)}")
        raise typer.Exit(code=1)

    since_date = _parse_date(since, "--since")
    until_date = _parse_date(until, "--until")
    auth = _resolve_fakturoid_auth(fakturoid_token, fakturoid_client_id, fakturoid_client_secret)
    dump = backup.load(backup_path)

    asyncio.run(
        _migrate_async(
            dump=dump,
            slug=fakturoid_slug,
            auth=auth,
            base_url=fakturoid_base_url,
            only=only,
            since=since_date,
            until=until_date,
            include_institutional=include_institutional_contacts,
            number_format_id=number_format_id,
            apply=yes,
        )
    )


async def _migrate_async(
    dump: Dump,
    slug: str,
    auth: dict[str, str],
    base_url: str,
    only: str | None,
    since: date | None,
    until: date | None,
    include_institutional: bool,
    number_format_id: int | None,
    apply: bool,
) -> None:
    do_contacts = only in (None, "contacts")
    do_issued = only in (None, "issued-invoices")
    do_received = only in (None, "received-invoices")

    run_log = RunLog.start(slug) if apply else None
    total_created = 0

    async with FakturoidClient(slug=slug, base_url=base_url, **auth) as client:
        contacts = load_flex_contacts(dump)
        country_lookup = load_country_lookup(dump)

        if do_contacts:
            contact_plan = await build_contact_plan(
                client, contacts, country_lookup, include_institutional
            )
            print_contact_plan(contact_plan)
            if apply:
                total_created += await apply_contact_plan(client, contact_plan, run_log)  # type: ignore[arg-type]

        if do_issued or do_received:
            existing_subjects = await client.list_subjects()
            idfirmy_to_subject_id = build_idfirmy_to_subject_id(contacts, existing_subjects)
            currency_lookup = load_currency_lookup(dump)
            lines_by_invoice = load_invoice_lines(dump)

        if do_issued:
            issued = load_invoices(dump, "FAV")
            issued_plan = await build_invoice_plan(
                client, issued, lines_by_invoice, idfirmy_to_subject_id, currency_lookup,
                "FAV", since, until, number_format_id,
            )
            print_invoice_plan(issued_plan, "Vydané faktury")
            if apply:
                total_created += await apply_invoice_plan(client, issued_plan, run_log, "FAV")  # type: ignore[arg-type]

        if do_received:
            received = load_invoices(dump, "FAP")
            received_plan = await build_invoice_plan(
                client, received, lines_by_invoice, idfirmy_to_subject_id, currency_lookup,
                "FAP", since, until,
            )
            print_invoice_plan(received_plan, "Přijaté faktury")
            if apply:
                total_created += await apply_invoice_plan(client, received_plan, run_log, "FAP")  # type: ignore[arg-type]

    if not apply:
        console.print("\n[dim]Dry-run — nic nebylo zapsáno. Spusť s --yes pro reálný import.[/dim]")
        return

    run_log_path = run_log.save()  # type: ignore[union-attr]
    console.print(f"\n[green]Hotovo.[/green] Vytvořeno {total_created} záznamů.")
    console.print(f"Run log: {run_log_path} (run-id: {run_log.run_id}, pro rollback)")  # type: ignore[union-attr]


@app.command()
def rollback(
    run_id: Annotated[str, typer.Argument(help="Run ID z výstupu předchozí migrace")],
    fakturoid_slug: Annotated[str, typer.Option("--fakturoid-slug", help="Slug Fakturoid účtu")],
    fakturoid_token: Annotated[
        str | None,
        typer.Option("--fakturoid-token", help="PAT token. Alternativa k --fakturoid-client-id/--fakturoid-client-secret."),
    ] = None,
    fakturoid_client_id: Annotated[
        str | None, typer.Option("--fakturoid-client-id", help="OAuth2 Client Credentials.")
    ] = None,
    fakturoid_client_secret: Annotated[
        str | None, typer.Option("--fakturoid-client-secret", help="Viz --fakturoid-client-id.")
    ] = None,
    fakturoid_base_url: Annotated[
        str,
        typer.Option("--fakturoid-base-url", hidden=True, help="Jen pro testy proti mock serveru."),
    ] = DEFAULT_BASE_URL,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Skutečně smazat. Bez tohoto jen ukáže, co by se smazalo."),
    ] = False,
) -> None:
    """Smaž přesně to, co vytvořil daný migrační běh (run-id). Nikdy nesahá na nic jiného.

    Viz docs/spec.md#rollback--failure-recovery."""
    try:
        run_log = RunLog.load(run_id)
    except FileNotFoundError:
        console.print(f"[red]Run log pro run-id {run_id!r} nenalezen.[/red]")
        raise typer.Exit(code=1) from None

    if run_log.slug != fakturoid_slug:
        console.print(
            f"[red]Run {run_id} patří účtu '{run_log.slug}', ne '{fakturoid_slug}'.[/red] "
            "Zastavuji, ať se nesmaže něco na jiném účtu."
        )
        raise typer.Exit(code=1)

    print_run_log_summary(run_log, f"Rollback {run_id} ({run_log.slug})")

    if not yes:
        console.print("\n[dim]Dry-run — nic nebylo smazáno. Spusť s --yes pro skutečné smazání.[/dim]")
        return

    auth = _resolve_fakturoid_auth(fakturoid_token, fakturoid_client_id, fakturoid_client_secret)
    asyncio.run(_rollback_async(run_log, fakturoid_slug, auth, fakturoid_base_url))


async def _rollback_async(run_log: RunLog, slug: str, auth: dict[str, str], base_url: str) -> None:
    async with FakturoidClient(slug=slug, base_url=base_url, **auth) as client:
        deleted, failures = await apply_rollback(client, run_log)

    console.print(f"\n[green]Smazáno {deleted} z {len(run_log.created)} záznamů.[/green]")
    if failures:
        console.print(f"[red]Nepovedlo se smazat {len(failures)}:[/red]")
        for failure in failures:
            console.print(f"  - {failure}")


if __name__ == "__main__":
    app()
