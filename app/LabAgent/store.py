"""The only writer. for_storage runs inside write(), so nothing bypasses it."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from controls import for_storage

LOG_PATH = Path(
    os.environ.get("LAB_LOG_PATH", Path(__file__).parent / "logs" / "agent_turns.jsonl")
)


def write(record: dict, *, path: Path | None = None, guardrail_client=None) -> dict:
    """Append for_storage(record) as one JSON line; return what was written."""
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    safe = for_storage(record, guardrail_client=guardrail_client)

    path = Path(path or LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe) + "\n")
    return safe
