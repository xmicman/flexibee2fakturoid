"""Fakturoid REST API v3 client.

Rate limiting here only protects against per-request 429s. The separate
monthly request quota (1500/month on the free tier) is a budgeting concern
for callers, not something this client tracks — see
docs/spec.md#api-limity-a-rozpočet-requestů.

`list_*` methods fetch every page in one call and are meant to be called
once per migration run to build a local dedup cache — never per record.
See docs/spec.md#idempotence for why.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://app.fakturoid.cz/api/v3"
REQUEST_INTERVAL_SECONDS = 0.35
MAX_RETRIES_ON_429 = 3
RETRY_BACKOFF_SECONDS = 5
TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60


class FakturoidError(RuntimeError):
    """Non-recoverable Fakturoid API error."""


class RateLimitExceededError(FakturoidError):
    """429 persisted after all retries — likely the monthly quota, not
    transient per-second throttling. See docs/spec.md#rate-limiting."""


class FakturoidClient:
    """Auth: either a static Personal Access Token (`token`), or OAuth2
    Client Credentials (`client_id` + `client_secret`) — Fakturoid's
    recommended flow for "scripts without a server component, single
    account", i.e. exactly this tool. Confirmed against
    https://www.fakturoid.cz/api/v3/authorization (2026-07-19):
    `POST {base_url}/oauth/token`, HTTP Basic auth with
    `client_id:client_secret`, body `{"grant_type": "client_credentials"}`,
    token expires after 2h with no refresh endpoint — this client
    re-fetches lazily before it expires, not on a timer.
    """

    def __init__(
        self,
        slug: str,
        token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = "flexibee2fakturoid (michal.manena@gmail.com)",
    ) -> None:
        if not token and not (client_id and client_secret):
            raise ValueError("FakturoidClient needs either token, or both client_id and client_secret")
        self._slug = slug
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = token
        self._token_expires_at = float("inf") if token else 0.0
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": user_agent, "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FakturoidClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _ensure_access_token(self) -> None:
        if self._token_expires_at > time.monotonic():
            return
        # Only reached for OAuth2 mode — static tokens set expires_at=inf.
        # Body matches the literal example at
        # https://www.fakturoid.cz/api/v3/authorization#client-credentials-flow
        # verbatim. KNOWN ISSUE (2026-07-19, see docs/spec.md Open Question
        # Q3 / CLAUDE.md): a live trial account gets 415 Unsupported Media
        # Type on this exact request. Also tried RFC 6749 §4.4's
        # application/x-www-form-urlencoded form — same 415. Both request
        # shapes verified byte-for-byte correct offline via
        # httpx.MockTransport, so this isn't a client-side encoding bug;
        # root cause is unconfirmed (account/app config? trial tier gating
        # OAuth specifically?). Needs Fakturoid support or a working
        # account to resolve — not blocking if a plain PAT is used instead.
        resp = await self._client.post(
            "/oauth/token",
            json={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        self._token_expires_at = time.monotonic() + expires_in - TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(MAX_RETRIES_ON_429 + 1):
            await self._ensure_access_token()
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
            headers = {"Authorization": f"Bearer {self._access_token}"}
            resp = await self._client.request(method, path, headers=headers, **kwargs)
            if resp.status_code != 429:
                return resp
            if attempt == MAX_RETRIES_ON_429:
                raise RateLimitExceededError(
                    f"{method} {path} still 429 after {MAX_RETRIES_ON_429} retries"
                )
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        raise AssertionError("unreachable")

    async def _list_all(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            resp = await self._request("GET", path, params={"page": page})
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            page += 1
        return items

    # --- Subjects --------------------------------------------------------

    async def list_subjects(self) -> list[dict[str, Any]]:
        return await self._list_all(f"/accounts/{self._slug}/subjects.json")

    async def create_subject(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", f"/accounts/{self._slug}/subjects.json", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def delete_subject(self, subject_id: int) -> None:
        resp = await self._request(
            "DELETE", f"/accounts/{self._slug}/subjects/{subject_id}.json"
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    # --- Issued invoices ---------------------------------------------------

    async def list_invoices(self) -> list[dict[str, Any]]:
        return await self._list_all(f"/accounts/{self._slug}/invoices.json")

    async def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", f"/accounts/{self._slug}/invoices.json", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def delete_invoice(self, invoice_id: int) -> None:
        resp = await self._request(
            "DELETE", f"/accounts/{self._slug}/invoices/{invoice_id}.json"
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    async def create_invoice_payment(self, invoice_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/accounts/{self._slug}/invoices/{invoice_id}/payments.json", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    # --- Received invoices ("expenses" in Fakturoid's API — see
    # docs/spec.md Open Question Q2. Earlier drafts guessed
    # "inbox_invoices", which does not exist; confirmed against
    # https://www.fakturoid.cz/api/v3/expenses.) ----------------------------

    async def list_expenses(self) -> list[dict[str, Any]]:
        return await self._list_all(f"/accounts/{self._slug}/expenses.json")

    async def create_expense(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/accounts/{self._slug}/expenses.json", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_expense(self, expense_id: int) -> None:
        resp = await self._request(
            "DELETE", f"/accounts/{self._slug}/expenses/{expense_id}.json"
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    async def create_expense_payment(self, expense_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/accounts/{self._slug}/expenses/{expense_id}/payments.json", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    # --- Number formats (Q3 — see docs/spec.md Open Questions) -------------

    async def list_number_formats(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/accounts/{self._slug}/number_formats.json")
        resp.raise_for_status()
        return resp.json()
