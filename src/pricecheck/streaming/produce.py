"""Emit a "file changed" event when bronze download detects real new content (outcome == "stored", not a
duplicate). Two backends, resolved the same way llm_service.py / serving/db.py resolve theirs in this project:

  Event Hubs (Kafka-compatible endpoint) -- used when EVENTHUB_* env vars are all set.
  Local file  -- always works, no cloud dependency: one JSON file per event, written to a directory. Spark
                 Structured Streaming's file source watches for new files appearing there, which is why this
                 writes one file per event rather than appending to a shared log (append would not trigger a
                 new streaming micro-batch the same way).

This is NOT a general event bus -- one narrow purpose (bronze content changed -> downstream should reprocess),
matching the stretch goal's actual scope.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOCAL_EVENTS_DIR = ROOT / "data/streaming/events"
KAFKA_TOPIC = "pricecheck-file-changed"


@dataclass
class FileChangedEvent:
    event_id: str
    slug: str
    sha256: str
    size_bytes: int
    outcome: str
    detected_at: str


def make_event(slug: str, sha256: str, size_bytes: int, outcome: str) -> FileChangedEvent:
    return FileChangedEvent(event_id=uuid.uuid4().hex, slug=slug, sha256=sha256, size_bytes=size_bytes,
                            outcome=outcome, detected_at=datetime.now(timezone.utc).isoformat())


def _eventhub_configured() -> bool:
    return bool(os.environ.get("EVENTHUB_NAMESPACE") and os.environ.get("EVENTHUB_NAME") and os.environ.get("EVENTHUB_CONNECTION_STRING"))


def emit(event: FileChangedEvent) -> dict:
    """Returns {"backend": ..., "detail": ...}. Never raises -- a failed emission is logged, not fatal to the
    caller (the same "never let a secondary concern break the primary pipeline" pattern used throughout this
    project, e.g. qa_service's experiment tracking in the RAG project)."""
    payload = json.dumps(asdict(event))
    if _eventhub_configured():
        try:
            from kafka import KafkaProducer
            ns = os.environ["EVENTHUB_NAMESPACE"]
            producer = KafkaProducer(
                bootstrap_servers=f"{ns}.servicebus.windows.net:9093",
                security_protocol="SASL_SSL", sasl_mechanism="PLAIN",
                sasl_plain_username="$ConnectionString", sasl_plain_password=os.environ["EVENTHUB_CONNECTION_STRING"],
                value_serializer=lambda v: v.encode("utf-8"), request_timeout_ms=15000,
            )
            producer.send(os.environ["EVENTHUB_NAME"], payload).get(timeout=15)
            producer.close()
            return {"backend": "eventhub", "detail": "sent"}
        except Exception as exc:  # noqa: BLE001 - report, don't crash the download pipeline over telemetry
            return {"backend": "eventhub", "detail": f"failed: {exc}"}
    LOCAL_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    out = LOCAL_EVENTS_DIR / f"{event.detected_at.replace(':', '')}_{event.event_id}.json"
    out.write_text(payload)
    return {"backend": "local_file", "detail": str(out)}
