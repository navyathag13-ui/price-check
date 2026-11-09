"""How much does the same procedure cost at different hospitals?

Reads the gold DuckDB warehouse and prints, per procedure, each hospital's median
cash (self-pay) price and the spread between the cheapest and the dearest hospital.
Prices flagged by the anomaly detector are left out.

    python scripts/price_spread.py               # all 21 hospitals
    python scripts/price_spread.py --state IA    # one state only
"""
from __future__ import annotations

import argparse

import duckdb

PROCEDURES = {
    "70551": "MRI brain, no contrast",
    "73721": "MRI knee or other leg joint, no contrast",
    "74177": "CT abdomen and pelvis, with contrast",
    "71046": "Chest X-ray, 2 views",
}

QUERY = """
WITH per_hospital AS (
    SELECT f.code, f.hospital_slug, median(f.amount) AS price
    FROM fact_price f JOIN dim_hospital h USING (hospital_slug)
    WHERE f.price_type = 'cash' AND f.amount > 0 AND NOT coalesce(f.is_flagged, false)
      AND f.code IN ({codes}) {state_filter}
    GROUP BY 1, 2
)
SELECT code, count(*) AS hospitals, min(price) AS lowest, median(price) AS median, max(price) AS highest,
       arg_min(hospital_slug, price) AS cheapest, arg_max(hospital_slug, price) AS dearest
FROM per_hospital GROUP BY 1 ORDER BY 1
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/gold/pricecheck.duckdb")
    p.add_argument("--state", help="two-letter state code, e.g. IA")
    args = p.parse_args()
    con = duckdb.connect(args.db, read_only=True)
    codes = ", ".join(f"'{c}'" for c in PROCEDURES)
    state_filter = "AND h.state = ?" if args.state else ""
    rows = con.execute(QUERY.format(codes=codes, state_filter=state_filter),
                       [args.state] if args.state else []).fetchall()
    print("| Procedure | Hospitals | Lowest | Median | Highest | Highest / lowest | Cheapest | Dearest |")
    print("|---|---|---|---|---|---|---|---|")
    for code, n, lo, med, hi, cheap, dear in rows:
        print(f"| {PROCEDURES[code]} ({code}) | {n} | ${lo:,.0f} | ${med:,.0f} | ${hi:,.0f} | {hi / lo:.1f}x | {cheap} | {dear} |")


if __name__ == "__main__":
    main()
