"""Persists what a real (--yes) migration run created, so it can be undone
precisely via `f2f rollback <run-id>` without touching anything the user
created themselves in Fakturoid. See docs/spec.md#rollback--failure-recovery.

Stored outside the repo (~/.f2f/runs/) — never committed, never contains
secrets, just FlexiBee/Fakturoid id pairs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RUN_LOG_DIR = Path.home() / ".f2f" / "runs"


@dataclass
class CreatedRecord:
    entity_type: str  # "subject" | "invoice" | "expense"
    fakturoid_id: int
    flexibee_source_id: str


@dataclass
class RunLog:
    run_id: str
    slug: str
    started_at: str
    created: list[CreatedRecord] = field(default_factory=list)

    @classmethod
    def start(cls, slug: str) -> RunLog:
        return cls(
            run_id=uuid.uuid4().hex[:12],
            slug=slug,
            started_at=datetime.now(UTC).isoformat(),
        )

    def record(self, entity_type: str, fakturoid_id: int, flexibee_source_id: str) -> None:
        self.created.append(CreatedRecord(entity_type, fakturoid_id, str(flexibee_source_id)))

    def path(self) -> Path:
        return RUN_LOG_DIR / f"{self.run_id}.json"

    def save(self) -> Path:
        RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = self.path()
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, run_id: str) -> RunLog:
        path = RUN_LOG_DIR / f"{run_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        created = [CreatedRecord(**c) for c in data["created"]]
        return cls(
            run_id=data["run_id"], slug=data["slug"], started_at=data["started_at"], created=created
        )
