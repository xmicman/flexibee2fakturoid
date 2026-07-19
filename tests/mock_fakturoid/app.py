"""Stateful mock of the relevant subset of the Fakturoid REST API v3.

Used for end-to-end tests of the migrate/rollback flow so nothing ever
touches a real Fakturoid account. See docs/spec.md#testing-strategy.

Not a full reimplementation of Fakturoid's API — just enough surface
(auth, dedup-relevant listing, validation, rate limiting, delete) to
exercise the CLI's full HTTP path.
"""

from __future__ import annotations

import itertools
from typing import Any

from flask import Flask, jsonify, request

PER_PAGE = 40
REQUIRED_SUBJECT_FIELDS = ("name",)
REQUIRED_INVOICE_FIELDS = ("subject_id",)


class MockState:
    def __init__(self) -> None:
        self.subjects: dict[int, dict[str, Any]] = {}
        self.invoices: dict[int, dict[str, Any]] = {}
        self.inbox_invoices: dict[int, dict[str, Any]] = {}
        self.sent_emails: list[int] = []
        self.request_count = 0
        self.rate_limit_every: int | None = None
        self._ids = itertools.count(1)

    def next_id(self) -> int:
        return next(self._ids)


def _paginated(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page = int(request.args.get("page", 1))
    start = (page - 1) * PER_PAGE
    return items[start : start + PER_PAGE]


def create_app(token: str = "test-token", rate_limit_every: int | None = None) -> Flask:
    app = Flask(__name__)
    state = MockState()
    state.rate_limit_every = rate_limit_every
    app.state = state  # type: ignore[attr-defined]

    @app.before_request
    def _check_auth_and_rate_limit() -> tuple[Any, int] | None:
        if request.path == "/health":
            return None
        if request.headers.get("Authorization") != f"Bearer {token}":
            return jsonify({"error": "invalid or missing token"}), 401
        state.request_count += 1
        if state.rate_limit_every and state.request_count % state.rate_limit_every == 0:
            return jsonify({"error": "rate limit exceeded"}), 429
        return None

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True})

    @app.get("/accounts/<slug>/number_formats.json")
    def number_formats(slug: str) -> Any:
        return jsonify([{"id": 1, "name": "Výchozí", "format": "((year))((rownumber))"}])

    # --- Subjects ------------------------------------------------------

    @app.post("/accounts/<slug>/subjects.json")
    def create_subject(slug: str) -> Any:
        payload = request.get_json(force=True) or {}
        missing = [f for f in REQUIRED_SUBJECT_FIELDS if not payload.get(f)]
        if missing:
            return jsonify({"errors": {f: ["can't be blank"] for f in missing}}), 422
        subject_id = state.next_id()
        record = {"id": subject_id, **payload}
        state.subjects[subject_id] = record
        return jsonify(record), 201

    @app.get("/accounts/<slug>/subjects.json")
    def list_subjects(slug: str) -> Any:
        return jsonify(_paginated(list(state.subjects.values())))

    @app.delete("/accounts/<slug>/subjects/<int:subject_id>.json")
    def delete_subject(slug: str, subject_id: int) -> Any:
        state.subjects.pop(subject_id, None)
        return "", 204

    # --- Invoices (issued) ----------------------------------------------

    @app.post("/accounts/<slug>/invoices.json")
    def create_invoice(slug: str) -> Any:
        payload = request.get_json(force=True) or {}
        error = _validate_invoice(payload, state)
        if error:
            return error
        invoice_id = state.next_id()
        record = {"id": invoice_id, **payload}
        state.invoices[invoice_id] = record
        return jsonify(record), 201

    @app.get("/accounts/<slug>/invoices.json")
    def list_invoices(slug: str) -> Any:
        return jsonify(_paginated(list(state.invoices.values())))

    @app.delete("/accounts/<slug>/invoices/<int:invoice_id>.json")
    def delete_invoice(slug: str, invoice_id: int) -> Any:
        state.invoices.pop(invoice_id, None)
        return "", 204

    @app.post("/accounts/<slug>/invoices/<int:invoice_id>/send_by_email.json")
    def send_by_email(slug: str, invoice_id: int) -> Any:
        # Migration code must never call this — see CLAUDE.md. Recorded here
        # so a test can assert it was never hit.
        state.sent_emails.append(invoice_id)
        return jsonify({"status": "sent"}), 200

    # --- Invoices (received / inbox) -------------------------------------

    @app.post("/accounts/<slug>/inbox_invoices.json")
    def create_inbox_invoice(slug: str) -> Any:
        payload = request.get_json(force=True) or {}
        error = _validate_invoice(payload, state)
        if error:
            return error
        invoice_id = state.next_id()
        record = {"id": invoice_id, **payload}
        state.inbox_invoices[invoice_id] = record
        return jsonify(record), 201

    @app.get("/accounts/<slug>/inbox_invoices.json")
    def list_inbox_invoices(slug: str) -> Any:
        return jsonify(_paginated(list(state.inbox_invoices.values())))

    @app.delete("/accounts/<slug>/inbox_invoices/<int:invoice_id>.json")
    def delete_inbox_invoice(slug: str, invoice_id: int) -> Any:
        state.inbox_invoices.pop(invoice_id, None)
        return "", 204

    return app


def _validate_invoice(payload: dict[str, Any], state: MockState) -> tuple[Any, int] | None:
    missing = [f for f in REQUIRED_INVOICE_FIELDS if not payload.get(f)]
    if missing:
        return jsonify({"errors": {f: ["can't be blank"] for f in missing}}), 422
    if payload["subject_id"] not in state.subjects:
        return jsonify({"errors": {"subject_id": ["does not exist"]}}), 422
    return None
