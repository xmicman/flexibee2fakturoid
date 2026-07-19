"""Sanity tests for the mock server itself, independent of our CLI."""

from __future__ import annotations

import httpx

from tests.conftest import MOCK_SLUG, MOCK_TOKEN
from tests.mock_fakturoid.server import MockFakturoidServer, running_mock_server


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {MOCK_TOKEN}"}


def test_health_does_not_require_auth(mock_fakturoid: MockFakturoidServer) -> None:
    resp = httpx.get(f"{mock_fakturoid.base_url}/health")
    assert resp.status_code == 200


def test_missing_token_is_rejected(mock_fakturoid: MockFakturoidServer) -> None:
    resp = httpx.get(f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects.json")
    assert resp.status_code == 401


def test_create_and_list_subject(mock_fakturoid: MockFakturoidServer) -> None:
    resp = httpx.post(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects.json",
        json={"name": "Firma s.r.o.", "registration_no": "12345678"},
        headers=_headers(),
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] == 1

    listed = httpx.get(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects.json", headers=_headers()
    )
    assert listed.json() == [created]


def test_create_subject_missing_name_is_422(mock_fakturoid: MockFakturoidServer) -> None:
    resp = httpx.post(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects.json",
        json={"registration_no": "12345678"},
        headers=_headers(),
    )
    assert resp.status_code == 422


def test_invoice_requires_existing_subject(mock_fakturoid: MockFakturoidServer) -> None:
    resp = httpx.post(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/invoices.json",
        json={"subject_id": 999, "number": "F1"},
        headers=_headers(),
    )
    assert resp.status_code == 422


def test_delete_subject(mock_fakturoid: MockFakturoidServer) -> None:
    created = httpx.post(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects.json",
        json={"name": "Dočasná firma"},
        headers=_headers(),
    ).json()

    resp = httpx.delete(
        f"{mock_fakturoid.base_url}/accounts/{MOCK_SLUG}/subjects/{created['id']}.json",
        headers=_headers(),
    )
    assert resp.status_code == 204
    assert mock_fakturoid.state.subjects == {}


def test_rate_limit_simulation() -> None:
    with running_mock_server(token=MOCK_TOKEN, rate_limit_every=3) as server:
        statuses = [
            httpx.get(
                f"{server.base_url}/accounts/{MOCK_SLUG}/subjects.json", headers=_headers()
            ).status_code
            for _ in range(3)
        ]
        assert statuses == [200, 200, 429]


def test_send_by_email_is_never_called_by_this_test_suite_by_default(
    mock_fakturoid: MockFakturoidServer,
) -> None:
    # Not a migration test — just documents that the mock tracks calls to
    # send_by_email so real e2e tests can assert it stays empty.
    assert mock_fakturoid.state.sent_emails == []
