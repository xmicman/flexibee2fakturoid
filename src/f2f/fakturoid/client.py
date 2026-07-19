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
from types import TracebackType
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://app.fakturoid.cz/api/v3"
REQUEST_INTERVAL_SECONDS = 0.35
MAX_RETRIES_ON_429 = 3
RETRY_BACKOFF_SECONDS = 5


class FakturoidError(RuntimeError):
    """Non-recoverable Fakturoid API error."""


class RateLimitExceededError(FakturoidError):
    """429 persisted after all retries — likely the monthly quota, not
    transient per-second throttling. See docs/spec.md#rate-limiting."""


class FakturoidClient:
    def __init__(
        self,
        slug: str,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = "flexibee2fakturoid (michal.manena@gmail.com)",
    ) -> None:
        self._slug = slug
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": user_agent,
                "Content-Type": "application/json",
            },
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

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(MAX_RETRIES_ON_429 + 1):
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
            resp = await self._client.request(method, path, **kwargs)
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

    # --- Received invoices (inbox) -----------------------------------------

    async def list_inbox_invoices(self) -> list[dict[str, Any]]:
        return await self._list_all(f"/accounts/{self._slug}/inbox_invoices.json")

    async def create_inbox_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/accounts/{self._slug}/inbox_invoices.json", json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_inbox_invoice(self, invoice_id: int) -> None:
        resp = await self._request(
            "DELETE", f"/accounts/{self._slug}/inbox_invoices/{invoice_id}.json"
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    # --- Number formats (Q3 — see docs/spec.md Open Questions) -------------

    async def list_number_formats(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/accounts/{self._slug}/number_formats.json")
        resp.raise_for_status()
        return resp.json()
