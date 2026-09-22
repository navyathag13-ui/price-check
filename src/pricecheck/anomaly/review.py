"""Precision estimate from the AI-labeled review sample. Labels: E likely error, R plausible real, U cannot tell.

Labeled by Claude under docs/phase4_review_protocol.md (written before sampling). NOT a human/domain-expert review.
Labels below are in sample order (rn 1..20 within each stratum). Short reasons live in review_labels.csv.
"""
import json
import math
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[3] / "data/anomaly"
# per-row labels (rn -> label), in the order of review_sample.csv
L = {
 "R5": dict(zip(range(1, 4), "RRR")),
 "R4": {1:"R",2:"R",3:"R",4:"R",5:"R",6:"U",7:"U",8:"U",9:"R",10:"R",11:"R",12:"R",13:"R",14:"R",15:"R",16:"R",17:"R",18:"R",19:"R",20:"R"},
 "R3": {1:"R",2:"R",3:"R",4:"R",5:"R",6:"E",7:"R",8:"U",9:"R",10:"R",11:"R",12:"R",13:"R",14:"R",15:"R",16:"R",17:"R",18:"R",19:"R",20:"E"},
 "R2": {1:"R",2:"E",3:"E",4:"E",5:"E",6:"R",7:"R",8:"R",9:"R",10:"R",11:"E",12:"E",13:"E",14:"E",15:"E",16:"R",17:"R",18:"E",19:"R",20:"E"},
 "R1": {1:"R",2:"R",3:"R",4:"R",5:"R",6:"E",7:"R",8:"R",9:"R",10:"R",11:"R",12:"R",13:"E",14:"E",15:"E",16:"R",17:"R",18:"R",19:"R",20:"E"},
 "IF_only": {1:"E",2:"E",3:"E",4:"E",5:"E",6:"E",7:"E",8:"U",9:"E",10:"E",11:"E",12:"E",13:"E",14:"E",15:"E",16:"E",17:"E",18:"R",19:"E",20:"E"},
}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def main() -> dict:
    sizes = json.loads((OUT / "flag_strata_sizes.json").read_text())
    s = pd.read_csv(OUT / "review_sample.csv")
    s["label"] = [L[r.stratum][r.rn] for r in s.itertuples()]
    s.to_csv(OUT / "review_sample_labeled.csv", index=False)
    total = sum(sizes.values()); res = {"strata": {}, "n_reviewed": len(s)}
    lo = hi = 0.0
    for st, n_pop in sizes.items():
        d = s[s.stratum == st]; n = len(d); e = int((d.label == "E").sum()); u = int((d.label == "U").sum()); r = n - e - u
        res["strata"][st] = {"population": n_pop, "reviewed": n, "E": e, "U": u, "R": r,
                             "precision_low": round(e / n, 3), "precision_high": round((e + u) / n, 3), "wilson95_low_bound": wilson(e, n),
                             "hospitals_among_E": sorted(d[d.label == "E"].hospital_slug.unique().tolist())}
        lo += n_pop * e / n; hi += n_pop * (e + u) / n
    res["overall_precision_estimate"] = {"lower": round(lo / total, 3), "upper": round(hi / total, 3), "flagged_population": total}
    (OUT / "review_results.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
