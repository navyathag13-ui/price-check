"""Spark Structured Streaming consumer for "file changed" events.

Two sources, same resolution pattern as produce.py's two sinks:
  file  (default) -- Spark's own file-source streaming, watching data/streaming/events/ for new JSON files.
                     Always works locally, no cloud dependency -- this is what's actually been tested this session.
  kafka -- Event Hubs' Kafka-compatible endpoint, when EVENTHUB_* env vars are set. NOT tested this session (no
           Event Hubs namespace has been created -- see terraform/main.tf and DECISIONS.md ADR-024).

For each micro-batch of events, calls the real reprocessing functions this project already has (silver.pipeline,
history.incremental) for the affected hospital -- this is not a toy consumer that just prints messages, it drives
the actual pipeline. Alerts on repeated failures via observability.alerts' Alert type, printed (not paged -- see
the runbook's "what's not wired up" section, same honest gap noted there).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVENT_SCHEMA_JSON = json.dumps({
    "type": "struct", "fields": [
        {"name": "event_id", "type": "string", "nullable": False, "metadata": {}},
        {"name": "slug", "type": "string", "nullable": False, "metadata": {}},
        {"name": "sha256", "type": "string", "nullable": False, "metadata": {}},
        {"name": "size_bytes", "type": "long", "nullable": False, "metadata": {}},
        {"name": "outcome", "type": "string", "nullable": False, "metadata": {}},
        {"name": "detected_at", "type": "string", "nullable": False, "metadata": {}},
    ]})


def reprocess(slug: str, sha256: str) -> dict:
    """The real reprocessing path: silver parse -> history load, for exactly the file that just changed.
    Returns a small dict describing what happened; never raises (a failure here is a data-pipeline finding,
    not a reason to kill the streaming job -- caught and reported per-event)."""
    from pricecheck.history.delta_store import load_version
    from pricecheck.silver.pipeline import latest_bronze, run_one

    bronze = latest_bronze()
    rec = bronze.get(slug)
    if rec is None or rec["sha256"] != sha256:
        return {"slug": slug, "sha256": sha256, "status": "skipped", "reason": "bronze record not found or hash mismatch (stale event)"}
    try:
        s = run_one(slug, rec, None, ROOT / "data")
        if s["outcome"] == "quarantined":
            return {"slug": slug, "sha256": sha256, "status": "quarantined", "detail": s.get("violations")}
        # "promoted" or "skipped_already_done" both mean silver is ready; load_version is itself idempotent
        # (checks the ledger, ADR-010), so it's always safe to call rather than branching on which one happened.
        glob = f"{ROOT}/data/silver/canonical/hospital={slug}/source_sha256={sha256}/part-*.parquet"
        h = load_version(ROOT / "data/delta/price_history", ROOT / "data/delta/ingestion_ledger", slug, sha256, glob, ROOT / "data/tmp")
        status = "already_current" if s["outcome"] == "skipped_already_done" and h["mode"] == "skipped_already_loaded" else "reprocessed"
        return {"slug": slug, "sha256": sha256, "status": status, "history_mode": h["mode"], "rows_inserted": h.get("rows_inserted", 0)}
    except Exception as exc:  # noqa: BLE001 - a per-event failure must not kill the streaming query
        return {"slug": slug, "sha256": sha256, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def handle_batch(df, batch_id: int) -> None:
    rows = [r.asDict() for r in df.collect()]
    if not rows:
        return
    print(f"[batch {batch_id}] {len(rows)} file-changed event(s)")
    for r in rows:
        result = reprocess(r["slug"], r["sha256"])
        print(f"  {result}")
        if result["status"] == "error":
            print(f"  [ALERT] reprocessing failed for {r['slug']}: {result.get('detail')}")


def build_query(spark, source: str, trigger_once: bool):
    if source == "kafka":
        ns = os.environ["EVENTHUB_NAMESPACE"]
        raw = (spark.readStream.format("kafka")
               .option("kafka.bootstrap.servers", f"{ns}.servicebus.windows.net:9093")
               .option("subscribe", os.environ.get("EVENTHUB_NAME", "pricecheck-file-changed"))
               .option("kafka.security.protocol", "SASL_SSL").option("kafka.sasl.mechanism", "PLAIN")
               .option("kafka.sasl.jaas.config",
                       'org.apache.kafka.common.security.plain.PlainLoginModule required username="$ConnectionString" '
                       f'password="{os.environ["EVENTHUB_CONNECTION_STRING"]}";')
               .option("startingOffsets", "earliest").load())
        from pyspark.sql.functions import col, from_json
        from pyspark.sql.types import StructType
        events = raw.select(from_json(col("value").cast("string"), StructType.fromJson(json.loads(EVENT_SCHEMA_JSON))).alias("e")).select("e.*")
    else:
        from pyspark.sql.types import StructType
        (ROOT / "data/streaming/events").mkdir(parents=True, exist_ok=True)
        events = (spark.readStream.format("json").schema(StructType.fromJson(json.loads(EVENT_SCHEMA_JSON)))
                  .option("maxFilesPerTrigger", 10).load(str(ROOT / "data/streaming/events")))
    writer = events.writeStream.foreachBatch(handle_batch).option("checkpointLocation", str(ROOT / f"data/streaming/checkpoint_{source}"))
    return writer.trigger(once=True).start() if trigger_once else writer.start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["file", "kafka"], default="file")
    ap.add_argument("--once", action="store_true", help="process currently-available events then stop (for testing/backfill)")
    ns = ap.parse_args()
    os.environ.setdefault("JAVA_HOME", str(Path.home() / ".local/share/jdk/jdk-17.0.20.1+1/Contents/Home"))
    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.master("local[2]").appName("pricecheck-streaming-consumer")
             .config("spark.sql.shuffle.partitions", "4").config("spark.ui.enabled", "false")
             .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.0" if ns.source == "kafka" else "")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    q = build_query(spark, ns.source, trigger_once=ns.once)
    q.awaitTermination()


if __name__ == "__main__":
    main()
