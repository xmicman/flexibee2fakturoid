"""End-to-end tests of the migrate flow against the mock Fakturoid server.

These go through the real f2f.fakturoid.client.FakturoidClient over HTTP,
not Python-level mocks — see docs/spec.md#testing-strategy for why.
"""

from __future__ import annotations

from f2f.fakturoid.client import FakturoidClient
from f2f.flexibee.models import FlexContact
from f2f.migration.run_log import RunLog
from f2f.migration.runner import apply_contact_plan, build_contact_plan
from tests.conftest import MOCK_SLUG, MOCK_TOKEN
from tests.mock_fakturoid.server import MockFakturoidServer, running_mock_server


def _contact(idfirmy: int, kod: str, nazev: str, ic: str | None = None, typvztahuk: str | None = None) -> FlexContact:
    return FlexContact(idfirmy=idfirmy, kod=kod, nazev=nazev, ic=ic, typvztahuk=typvztahuk)


async def _client(server: MockFakturoidServer) -> FakturoidClient:
    return FakturoidClient(slug=MOCK_SLUG, token=MOCK_TOKEN, base_url=server.base_url)


async def test_apply_creates_subjects_and_records_run_log(mock_fakturoid: MockFakturoidServer) -> None:
    contacts = [
        _contact(1, "FIRMA001", "Firma s.r.o.", ic="12345678"),
        _contact(2, "FIRMA002", "Jiná firma a.s.", ic="87654321"),
    ]
    async with await _client(mock_fakturoid) as client:
        plan = await build_contact_plan(client, contacts, country_lookup={})
        assert len(plan.to_create) == 2

        run_log = RunLog.start(MOCK_SLUG)
        created_count = await apply_contact_plan(client, plan, run_log)

    assert created_count == 2
    assert len(mock_fakturoid.state.subjects) == 2
    assert len(run_log.created) == 2
    assert {r.flexibee_source_id for r in run_log.created} == {"1", "2"}


async def test_second_run_skips_duplicates_by_registration_no(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    contact = _contact(1, "FIRMA001", "Firma s.r.o.", ic="12345678")

    async with await _client(mock_fakturoid) as client:
        first_plan = await build_contact_plan(client, [contact], country_lookup={})
        await apply_contact_plan(client, first_plan, RunLog.start(MOCK_SLUG))

        second_plan = await build_contact_plan(client, [contact], country_lookup={})

    assert len(second_plan.to_create) == 0
    assert len(second_plan.to_skip_existing) == 1
    assert len(mock_fakturoid.state.subjects) == 1


async def test_institutional_contacts_skipped_by_default(mock_fakturoid: MockFakturoidServer) -> None:
    contacts = [_contact(1, "VZP", "Zdravotní pojišťovna", typvztahuk="typVztahu.zdravotka")]
    async with await _client(mock_fakturoid) as client:
        plan = await build_contact_plan(client, contacts, country_lookup={})

    assert len(plan.to_create) == 0
    assert len(plan.to_skip_institutional) == 1


async def test_dry_run_never_calls_create(mock_fakturoid: MockFakturoidServer) -> None:
    contacts = [_contact(1, "FIRMA001", "Firma s.r.o.", ic="12345678")]
    async with await _client(mock_fakturoid) as client:
        await build_contact_plan(client, contacts, country_lookup={})
        # Dry-run: never call apply_contact_plan.

    assert mock_fakturoid.state.subjects == {}


async def test_migration_never_calls_send_by_email(mock_fakturoid: MockFakturoidServer) -> None:
    contacts = [_contact(1, "FIRMA001", "Firma s.r.o.", ic="12345678")]
    async with await _client(mock_fakturoid) as client:
        plan = await build_contact_plan(client, contacts, country_lookup={})
        await apply_contact_plan(client, plan, RunLog.start(MOCK_SLUG))

    assert mock_fakturoid.state.sent_emails == []


async def test_retries_after_429_and_eventually_succeeds() -> None:
    with running_mock_server(token=MOCK_TOKEN, rate_limit_every=2) as server:
        contacts = [_contact(1, "FIRMA001", "Firma s.r.o.", ic="12345678")]
        async with FakturoidClient(slug=MOCK_SLUG, token=MOCK_TOKEN, base_url=server.base_url) as client:
            plan = await build_contact_plan(client, contacts, country_lookup={})
            run_log = RunLog.start(MOCK_SLUG)
            created_count = await apply_contact_plan(client, plan, run_log)

        assert created_count == 1
