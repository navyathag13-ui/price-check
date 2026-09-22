"""config/hospitals.yaml -> data/dbt_sources/hospitals.csv, so dbt (which reads CSV via DuckDB) has a source for it."""
import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    h = yaml.safe_load((ROOT / "config/hospitals.yaml").read_text())["hospitals"]
    out = ROOT / "data/dbt_sources/hospitals.csv"; out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["slug", "name", "state", "group", "index_url", "mrf_url"]); w.writeheader()
        for r in h:
            w.writerow(r)
    print(len(h), "hospitals exported to", out)
