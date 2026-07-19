from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.mock_fakturoid.server import MockFakturoidServer, running_mock_server

MOCK_TOKEN = "test-token"
MOCK_SLUG = "test-account"


@pytest.fixture
def mock_fakturoid() -> Iterator[MockFakturoidServer]:
    with running_mock_server(token=MOCK_TOKEN) as server:
        yield server
