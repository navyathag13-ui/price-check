"""Build small, real (not mocked) Delta/parquet fixtures with the pipeline's actual schemas, for CI's dbt job.

CI has no access to the real 41M-row history table (multi-GB, gitignored, local-only). Rather than mock dbt's
inputs with hand-typed rows in a different shape, this imports the real schemas from history/delta_store.py and
writes genuinely valid Delta tables through the real write path (write_deltalake), just with 3 hospitals and a
few hundred rows instead of 21 hospitals and 41.1M. Every dbt model and test runs against real, if small, data.
"""
import csv
import random
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
from deltalake import write_deltalake

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/ci_fixtures"
random.seed(20260922)


def main() -> None:
    from pricecheck.history.delta_store import HISTORY_SCHEMA

    OUT.mkdir(parents=True, exist_ok=True)
    hospitals = ["ci-hosp-a", "ci-hosp-b", "ci-hosp-c"]
    payers = ["Aetna", "Cigna", None]
    codes = [("99213", "CPT"), ("71046", "CPT"), ("J1885", "HCPCS"), ("470", "MS-DRG")]
    now = datetime.now(timezone.utc)
    rows = []
    for h in hospitals:
        for i, (code, ctype) in enumerate(codes):
            for j, payer in enumerate(payers):
                amt = Decimal(str(round(random.uniform(10, 5000), 2)))
                pt = "negotiated" if payer else random.choice(["gross", "cash", "min", "max"])
                rid = f"{h}-{code}-{j}"
                rows.append({
                    "row_id": rid, "key_hash": rid, "hospital_slug": h, "description": f"CI fixture item {code}",
                    "code": code, "code_type": ctype, "alt_codes": "", "setting": "outpatient", "billing_class": "facility",
                    "payer": payer, "plan": "PPO" if payer else None, "price_type": pt, "dup_seq": 0, "amount": amt,
                    "methodology": "fee schedule" if payer else None, "modifiers": None, "row_hash": f"{rid}-hash",
                    "first_source_sha256": "ci-fixture-sha", "effective_from": now, "effective_to": None,
                    "is_current": True, "closed_by_source_sha256": None, "change_reason": None,
                })
    write_deltalake(str(OUT / "price_history"), pa.Table.from_pylist(rows, schema=HISTORY_SCHEMA), mode="overwrite")

    q_rows = []
    for h in hospitals:
        q_rows.append({"hospital_slug": h, "source_sha256": "ci-fixture-sha", "as_of": now.date(), "items": 4,
                       "price_rows": len([r for r in rows if r["hospital_slug"] == h]), "completeness": 0.9,
                       "validity": 0.95, "consistency": 0.98, "freshness": 0.8, "quality_score": round((0.9+0.95+0.98+0.8)/4*100, 1),
                       "m_reject_rate": 0.01, "m_sentinel_rate": 0.0, "m_standard_code_share": 1.0,
                       "m_days_since_update": 30, "m_template_current": 1.0})
    write_deltalake(str(OUT / "quality_scores"), pa.Table.from_pylist(q_rows), mode="overwrite")

    flag_rows = [{"row_id": r["row_id"], "hospital_slug": r["hospital_slug"], "code": r["code"], "price_type": r["price_type"],
                 "R1_robust_z": False, "R2_neg_gt_gross": False, "R3_out_of_range": False, "R4_cash_gt_gross": False,
                 "R5_placeholder": False, "if_score": 0.1, "IF_flag": False, "any_rule": False, "any_flag": False}
                for r in rows if r["price_type"] in ("negotiated", "cash", "gross")]
    pa.parquet.write_table(pa.Table.from_pylist(flag_rows), OUT / "flags.parquet")

    with (OUT / "hospitals.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["slug", "name", "state", "group", "index_url", "mrf_url"]); w.writeheader()
        for h in hospitals:
            w.writerow({"slug": h, "name": f"CI Fixture Hospital {h}", "state": "IA", "group": "ci",
                       "index_url": f"https://{h}.example/cms-hpt.txt", "mrf_url": f"https://{h}.example/mrf.csv"})

    print(f"wrote {len(rows)} price_history rows, {len(q_rows)} quality rows, {len(flag_rows)} flag rows, {len(hospitals)} hospitals")


if __name__ == "__main__":
    main()
