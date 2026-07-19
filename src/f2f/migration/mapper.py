"""FlexiBee -> Fakturoid field mapping and migration planning (dedup).

See docs/spec.md — Field Mapping for the source of these mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from f2f.fakturoid.models import Subject
from f2f.flexibee.models import FlexContact

# typvztahuk values observed in real data for institutional contacts
# (health insurance, social security, tax office) rather than actual
# customers/suppliers. See docs/spec.md Open Questions Q7 — excluded by
# default, override with --include-institutional-contacts.
INSTITUTIONAL_RELATION_TYPES = {
    "typVztahu.zdravotka",
    "typVztahu.socialka",
    "typVztahu.financniUrad",
}


def is_institutional_contact(contact: FlexContact) -> bool:
    return contact.typvztahuk in INSTITUTIONAL_RELATION_TYPES


def _clean_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip()
    # Legacy records observed with a stray "EMAIL" prefix, e.g.
    # " EMAILinfo@vzp.cz" — see docs/spec.md Field Mapping notes.
    if cleaned.upper().startswith("EMAIL"):
        cleaned = cleaned[len("EMAIL") :]
    return cleaned.strip() or None


def map_contact(contact: FlexContact, country_lookup: dict[str, str]) -> Subject:
    country = country_lookup.get(str(contact.idfastatu)) if contact.idfastatu is not None else None
    return Subject(
        name=contact.nazev.strip(),
        registration_no=contact.ic.strip() if contact.ic else None,
        vat_no=contact.dic.strip() if contact.dic else None,
        email=_clean_email(contact.email),
        phone=contact.tel.strip() if contact.tel else None,
        street=contact.ulice.strip() if contact.ulice else None,
        city=contact.mesto.strip() if contact.mesto else None,
        zip=contact.psc.strip() if contact.psc else None,
        country=country,
    )


@dataclass
class ContactMigrationPlan:
    to_create: list[tuple[FlexContact, Subject]] = field(default_factory=list)
    to_skip_existing: list[FlexContact] = field(default_factory=list)
    to_skip_institutional: list[FlexContact] = field(default_factory=list)
    no_dedup_key_warning: list[FlexContact] = field(default_factory=list)


def plan_contacts_migration(
    contacts: list[FlexContact],
    country_lookup: dict[str, str],
    existing_registration_nos: set[str],
    include_institutional: bool = False,
) -> ContactMigrationPlan:
    """Decide what to create/skip. Does not talk to the network — the
    caller fetches `existing_registration_nos` once via
    `FakturoidClient.list_subjects()`, not per contact.
    """
    plan = ContactMigrationPlan()
    seen_in_this_run: set[str] = set()
    for contact in contacts:
        if not include_institutional and is_institutional_contact(contact):
            plan.to_skip_institutional.append(contact)
            continue

        dedup_key = contact.ic.strip() if contact.ic else None
        if not dedup_key:
            plan.no_dedup_key_warning.append(contact)
        elif dedup_key in existing_registration_nos or dedup_key in seen_in_this_run:
            plan.to_skip_existing.append(contact)
            continue
        else:
            seen_in_this_run.add(dedup_key)

        plan.to_create.append((contact, map_contact(contact, country_lookup)))
    return plan
