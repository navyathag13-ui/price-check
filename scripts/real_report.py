"""Record (or reproduce) the pinned price-spread report against the REAL history table."""
import json
import sys
from pathlib import Path

from pricecheck.history import delta_store as D
from pricecheck.reports import median_price as R

ROOT = Path(__file__).resolve().parents[1]
HIST, LEDG = ROOT / "data/delta/price_history", ROOT / "reports/ledger.jsonl"

if len(sys.argv) > 1 and sys.argv[1] == "reproduce":
    print(json.dumps(R.reproduce(sys.argv[2], LEDG), indent=2)); sys.exit(0)
con = D.duck()
codes = [r[0] for r in con.execute(f"""SELECT code FROM delta_scan('{HIST}') WHERE is_current AND price_type='negotiated' AND code_type='CPT'
    GROUP BY code HAVING count(DISTINCT hospital_slug) >= 15 ORDER BY count(*) DESC, code LIMIT 20""").fetchall()]
params = {"name": "price_spread_by_code", "version": 1, "price_types": ["negotiated", "cash"], "codes": codes,
          "selection_rule": "20 CPT codes with negotiated prices at >=15 of 21 hospitals, most rows first, as of the pinned Delta version"}
rec = R.record(HIST, params, LEDG)
print(json.dumps({k: rec[k] for k in ("run_id", "history_version", "rows", "output_sha256")}, indent=2))
