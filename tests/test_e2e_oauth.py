"""End-to-end tests for OAuth2 Client Credentials auth against the mock
Fakturoid server. See FakturoidClient docstring and
docs/spec.md#fakturoid-import for why this is the primary auth mode."""

from __future__ import annotations

import pytest

from f2f.fakturoid.client import FakturoidClient, FakturoidError
from tests.conftest import MOCK_SLUG
from tests.mock_fakturoid.server import running_mock_server


async def test_client_credentials_flow_obtains_and_uses_token() -> None:
    with running_mock_server(
        oauth_client_id="my-client-id", oauth_client_secret="my-client-secret"
    ) as server:
        async with FakturoidClient(
            slug=MOCK_SLUG,
            client_id="my-client-id",
            client_secret="my-client-secret",
            base_url=server.base_url,
        ) as client:
            subjects = await client.list_subjects()

        assert subjects == []


async def test_wrong_client_secret_is_rejected() -> None:
    with running_mock_server(
        oauth_client_id="my-client-id", oauth_client_secret="my-client-secret"
    ) as server:
        async with FakturoidClient(
            slug=MOCK_SLUG,
            client_id="my-client-id",
            client_secret="wrong-secret",
            base_url=server.base_url,
        ) as client:
            with pytest.raises(FakturoidError):
                await client.list_subjects()


async def test_client_requires_token_or_client_credentials() -> None:
    with pytest.raises(ValueError, match="token, or both client_id and client_secret"):
        FakturoidClient(slug=MOCK_SLUG)


async def test_oauth_token_reused_across_requests_not_refetched_every_call() -> None:
    with running_mock_server(
        oauth_client_id="my-client-id", oauth_client_secret="my-client-secret"
    ) as server:
        token_requests_before = server.state.request_count
        async with FakturoidClient(
            slug=MOCK_SLUG,
            client_id="my-client-id",
            client_secret="my-client-secret",
            base_url=server.base_url,
        ) as client:
            await client.list_subjects()
            await client.list_subjects()
            await client.list_subjects()

        # /oauth/token itself is excluded from request_count (see app.py
        # before_request) — three list_subjects calls should show as
        # exactly 3 counted requests, not 6, proving the token was cached
        # rather than re-fetched before every call.
        assert server.state.request_count - token_requests_before == 3
