"""End-to-end tests of issued/received invoice migration against the mock
Fakturoid server. See docs/spec.md#testing-strategy."""

from __future__ import annotations

from datetime import date

from f2f.fakturoid.client import FakturoidClient
from f2f.flexibee.models import FlexContact, FlexInvoice, FlexInvoiceLine
from f2f.migration.run_log import RunLog
from f2f.migration.runner import (
    apply_invoice_plan,
    build_idfirmy_to_subject_id,
    build_invoice_plan,
)
from tests.conftest import MOCK_SLUG, MOCK_TOKEN
from tests.mock_fakturoid.server import MockFakturoidServer


def _client(server: MockFakturoidServer) -> FakturoidClient:
    return FakturoidClient(slug=MOCK_SLUG, token=MOCK_TOKEN, base_url=server.base_url)


def _invoice(
    iddoklfak: int,
    kod: str,
    modul: str,
    datvyst: str,
    idfirmy: int = 1,
    storno: str = "f",
    stavuhrk: str | None = None,
) -> FlexInvoice:
    return FlexInvoice(
        iddoklfak=iddoklfak,
        kod=kod,
        modul=modul,
        datvyst=datvyst,
        idfirmy=idfirmy,
        sumcelkem="1000.00",
        storno=storno,
        stavuhrk=stavuhrk,
    )


async def _seed_subject(client: FakturoidClient, registration_no: str) -> dict:
    return await client.create_subject({"name": "Firma s.r.o.", "registration_no": registration_no})


async def test_issued_invoice_created_with_number_and_subject(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    line = FlexInvoiceLine(iddoklfak=100, nazev="Programování", mnozmj="10", cenamj="1500", szbdph="21")

    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])

        invoice = _invoice(100, "VF1-0009/2024", "FAV", "2024-09-30", idfirmy=1)
        plan = await build_invoice_plan(
            client, [invoice], {100: [line]}, idfirmy_map, {}, "FAV", since=None, until=None
        )
        assert len(plan.to_create) == 1

        run_log = RunLog.start(MOCK_SLUG)
        created = await apply_invoice_plan(client, plan, run_log, "FAV")

    assert created == 1
    assert len(mock_fakturoid.state.invoices) == 1
    stored = next(iter(mock_fakturoid.state.invoices.values()))
    assert stored["number"] == "VF1-0009/2024"
    assert stored["subject_id"] == subject["id"]
    assert stored["lines"][0]["name"] == "Programování"


async def test_since_until_filters_invoices_out_of_scope(mock_fakturoid: MockFakturoidServer) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoices = [
        _invoice(1, "F2023", "FAV", "2023-06-01"),
        _invoice(2, "F2024", "FAV", "2024-06-01"),
        _invoice(3, "F2025", "FAV", "2025-06-01"),
    ]
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])

        plan = await build_invoice_plan(
            client, invoices, {}, idfirmy_map, {}, "FAV",
            since=date(2024, 1, 1), until=date(2025, 1, 1),
        )

    assert [inv.kod for inv, _ in plan.to_create] == ["F2024"]


async def test_storno_invoice_is_skipped(mock_fakturoid: MockFakturoidServer) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F1", "FAV", "2024-01-01", storno="t")
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])
        plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAV", since=None, until=None
        )

    assert len(plan.to_create) == 0
    assert len(plan.to_skip_storno) == 1


async def test_invoice_missing_subject_is_skipped_with_warning(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    # No contact/subject seeded — idfirmy=1 has no mapping.
    invoice = _invoice(1, "F1", "FAV", "2024-01-01", idfirmy=1)
    async with _client(mock_fakturoid) as client:
        plan = await build_invoice_plan(
            client, [invoice], {}, {}, {}, "FAV", since=None, until=None
        )

    assert len(plan.to_create) == 0
    assert len(plan.to_skip_missing_subject) == 1


async def test_received_invoice_goes_to_expenses_endpoint(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F0083/23", "FAP", "2023-10-25", idfirmy=1)
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])
        plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAP", since=None, until=None
        )
        run_log = RunLog.start(MOCK_SLUG)
        created = await apply_invoice_plan(client, plan, run_log, "FAP")

    assert created == 1
    assert len(mock_fakturoid.state.expenses) == 1
    assert mock_fakturoid.state.invoices == {}


async def test_second_run_dedups_invoices_by_number(mock_fakturoid: MockFakturoidServer) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F1", "FAV", "2024-01-01", idfirmy=1)
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])

        first_plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAV", since=None, until=None
        )
        await apply_invoice_plan(client, first_plan, RunLog.start(MOCK_SLUG), "FAV")

        second_plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAV", since=None, until=None
        )

    assert len(second_plan.to_create) == 0
    assert len(second_plan.to_skip_existing) == 1


async def test_paid_issued_invoice_records_payment_via_separate_call(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F1", "FAV", "2024-01-01", idfirmy=1, stavuhrk="stavUhr.uhrazenoRucne")
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])
        plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAV", since=None, until=None
        )
        await apply_invoice_plan(client, plan, RunLog.start(MOCK_SLUG), "FAV")

    created_id = next(iter(mock_fakturoid.state.invoices))
    # Payment is a separate call, not a field on the creation payload — see
    # Invoice model docstring and docs/spec.md#fakturoid-import.
    assert mock_fakturoid.state.invoice_payments[created_id] == [{"paid_on": "2024-01-01"}]


async def test_unpaid_invoice_never_calls_payments_endpoint(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F1", "FAV", "2024-01-01", idfirmy=1, stavuhrk=None)
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])
        plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAV", since=None, until=None
        )
        await apply_invoice_plan(client, plan, RunLog.start(MOCK_SLUG), "FAV")

    assert mock_fakturoid.state.invoice_payments == {}


async def test_paid_received_expense_records_payment(mock_fakturoid: MockFakturoidServer) -> None:
    contact = FlexContact(idfirmy=1, kod="F1", nazev="Firma", ic="12345678")
    invoice = _invoice(1, "F1", "FAP", "2024-01-01", idfirmy=1, stavuhrk="stavUhr.uhrazenoRucne")
    async with _client(mock_fakturoid) as client:
        subject = await _seed_subject(client, "12345678")
        idfirmy_map = build_idfirmy_to_subject_id([contact], [subject])
        plan = await build_invoice_plan(
            client, [invoice], {}, idfirmy_map, {}, "FAP", since=None, until=None
        )
        await apply_invoice_plan(client, plan, RunLog.start(MOCK_SLUG), "FAP")

    created_id = next(iter(mock_fakturoid.state.expenses))
    assert mock_fakturoid.state.expense_payments[created_id] == [{"paid_on": "2024-01-01"}]
