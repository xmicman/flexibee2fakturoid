from __future__ import annotations

from f2f.flexibee.models import FlexInvoice
from f2f.migration.mapper import map_issued_invoice, map_received_expense, plan_invoices_migration


def _invoice(iddoklfak: int, kod: str, idfirmy: int = 1, modul: str = "FAV") -> FlexInvoice:
    return FlexInvoice(
        iddoklfak=iddoklfak,
        kod=kod,
        modul=modul,
        datvyst="2026-01-01",
        idfirmy=idfirmy,
        sumcelkem="100.00",
    )


def test_map_issued_invoice_normalizes_slash_to_hyphen() -> None:
    invoice = _invoice(1, "VF1-0009/2024")
    mapped = map_issued_invoice(invoice, [], subject_id=42, currency_lookup={})
    # Fakturoid number formats reject "/" — confirmed live 2026-07-19,
    # see _normalize_invoice_number docstring.
    assert mapped.number == "VF1-0009-2024"


def test_dedup_compares_normalized_number_against_existing() -> None:
    """existing_numbers comes from Fakturoid, which stores "-" not "/" —
    dedup must normalize before comparing or it silently never matches."""
    invoice = _invoice(1, "VF1-0009/2024")
    plan = plan_invoices_migration(
        invoices=[invoice],
        lines_by_invoice={},
        idfirmy_to_subject_id={1: 42},
        currency_lookup={},
        existing_dedup_keys={"VF1-0009-2024"},
        modul="FAV",
    )
    assert len(plan.to_create) == 0
    assert len(plan.to_skip_existing) == 1


def test_two_invoices_differing_only_by_separator_dedup_within_same_run() -> None:
    same_after_normalization = [_invoice(1, "F1/24"), _invoice(2, "F1-24")]
    plan = plan_invoices_migration(
        invoices=same_after_normalization,
        lines_by_invoice={},
        idfirmy_to_subject_id={1: 42},
        currency_lookup={},
        existing_dedup_keys=set(),
        modul="FAV",
    )
    assert len(plan.to_create) == 1
    assert len(plan.to_skip_existing) == 1


def test_map_received_expense_has_no_number_but_has_custom_id() -> None:
    # Expenses have no configurable number_format (confirmed live
    # 2026-07-19, no such option in Fakturoid's "Náklady" UI) — original
    # number goes in custom_id instead, unnormalized. See Expense model
    # docstring.
    invoice = _invoice(1, "F0001/26", modul="FAP")
    mapped = map_received_expense(invoice, [], subject_id=42, currency_lookup={})
    assert mapped.custom_id == "F0001/26"
    assert "number" not in mapped.model_dump(exclude_none=True)


def test_expense_dedup_uses_custom_id_not_number() -> None:
    invoice = _invoice(1, "F0001/26", modul="FAP")
    plan = plan_invoices_migration(
        invoices=[invoice],
        lines_by_invoice={},
        idfirmy_to_subject_id={1: 42},
        currency_lookup={},
        existing_dedup_keys={"F0001/26"},  # raw, unnormalized — matches custom_id
        modul="FAP",
    )
    assert len(plan.to_create) == 0
    assert len(plan.to_skip_existing) == 1
