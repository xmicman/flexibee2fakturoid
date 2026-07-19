from __future__ import annotations

from pydantic import BaseModel


class Subject(BaseModel):
    """Payload shape for POST /accounts/{slug}/subjects.json."""

    name: str
    registration_no: str | None = None
    vat_no: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    zip: str | None = None
    country: str | None = None
