"""Runs the mock Fakturoid app on a real local socket so tests exercise the
full HTTP stack (httpx client, retries, JSON serialization) rather than
mocking at the Python function level.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from werkzeug.serving import make_server

from .app import MockState, create_app


class MockFakturoidServer:
    def __init__(
        self,
        token: str = "test-token",
        rate_limit_every: int | None = None,
        oauth_client_id: str = "test-client-id",
        oauth_client_secret: str = "test-client-secret",
    ) -> None:
        self.token = token
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self.app = create_app(
            token=token,
            rate_limit_every=rate_limit_every,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
        )
        self._server = make_server("127.0.0.1", 0, self.app)
        self.port = self._server.server_port
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)

    @property
    def state(self) -> MockState:
        return self.app.state  # type: ignore[attr-defined]


@contextmanager
def running_mock_server(
    token: str = "test-token",
    rate_limit_every: int | None = None,
    oauth_client_id: str = "test-client-id",
    oauth_client_secret: str = "test-client-secret",
) -> Iterator[MockFakturoidServer]:
    server = MockFakturoidServer(
        token=token,
        rate_limit_every=rate_limit_every,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
    )
    server.start()
    try:
        yield server
    finally:
        server.stop()
