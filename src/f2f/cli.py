from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from f2f.flexibee import backup
from f2f.flexibee.models import FlexContact, FlexInvoice

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


if __name__ == "__main__":
    app()
