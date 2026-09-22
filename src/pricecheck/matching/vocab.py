"""Reference vocabulary + labeled sets for procedure matching.

Vocabulary entries: (code, normalised text, hospital bitmask, source). Sources: official CMS HCPCS Level II long
descriptions, official MS-DRG titles, and *crowd* descriptions hospitals attached to a code (this is how CPT is covered:
CPT has no free official text, ADR-004). Leave-one-hospital-out: when matching an item from hospital H, entries whose
contributing hospitals are only {H} are excluded, so a hospital's own description of its own code can never leak.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from pricecheck.history import delta_store as D
from pricecheck.matching.normalize import code_family, normalize

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/matching"
CMS_BIT = 1 << 40
PER_CODE_CAP = 6


def hcpcs_reference() -> pd.DataFrame:
    z = zipfile.ZipFile(ROOT / "data/reference/hcpcs_2026-10.zip")
    desc: dict[str, str] = {}
    for line in z.read("HCPC2026_OCT_ANWEB_v2.txt").decode("latin-1").splitlines():
        if len(line) < 12:
            continue
        code, rec, text = line[0:5].strip(), line[10:11], line[11:91].strip()
        if rec in ("3", "4") and re.fullmatch(r"[A-Z][0-9]{4}", code):
            desc[code] = (desc.get(code, "") + " " + text).strip()
    return pd.DataFrame({"code": list(desc), "raw": list(desc.values())})


def msdrg_reference() -> pd.DataFrame:
    z = zipfile.ZipFile(ROOT / "data/reference/msdrg_fy2026_table5.zip")
    rows = []
    for line in z.read("CMS-1833-F Table 5.txt").decode("latin-1").splitlines():
        parts = [p.strip().strip('"') for p in line.split("\t")]
        if len(parts) > 5 and re.fullmatch(r"\d{3}", parts[0]):
            rows.append((parts[0], parts[5]))
    return pd.DataFrame(rows, columns=["code", "raw"])


def hospital_items() -> pd.DataFrame:
    con = D.duck()
    df = con.execute(f"""SELECT DISTINCT hospital_slug, code, code_type, description FROM delta_scan('{ROOT}/data/delta/price_history')
                         WHERE is_current AND code_type IN ('CPT','HCPCS','MS-DRG') AND code IS NOT NULL AND description IS NOT NULL""").df()
    df["text"] = df.description.map(normalize)
    df = df[df.text.str.len() >= 3]
    df["family"] = df.code.map(code_family)
    return df


def build_vocab(items: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    slugs = sorted(items.hospital_slug.unique())
    bit = {s: 1 << i for i, s in enumerate(slugs)}
    items = items.assign(bit=items.hospital_slug.map(bit))
    g = items.groupby(["code", "text"], as_index=False).agg(mask=("bit", lambda x: int(sum(set(x)))), n_hosp=("hospital_slug", "nunique"))
    g["len"] = g.text.str.len()
    g = g.sort_values(["code", "n_hosp", "len"], ascending=[True, False, True]).groupby("code").head(PER_CODE_CAP)
    g["source"] = "hospital"
    frames = [g[["code", "text", "mask", "n_hosp", "source"]]]
    for name, ref in (("cms_hcpcs", hcpcs_reference()), ("cms_msdrg", msdrg_reference())):
        ref["text"] = ref.raw.map(normalize)
        ref = ref[ref.text.str.len() >= 3]
        frames.append(pd.DataFrame({"code": ref.code, "text": ref.text, "mask": CMS_BIT, "n_hosp": 0, "source": name}))
    v = pd.concat(frames, ignore_index=True).drop_duplicates(["code", "text", "source"]).reset_index(drop=True)
    return v, bit


if __name__ == "__main__":
    import json
    items = hospital_items(); v, bit = build_vocab(items)
    v.to_parquet(OUT / "vocab.parquet"); items.to_parquet(OUT / "items.parquet"); json.dump(bit, open(OUT / "hospital_bits.json", "w"))
    print("distinct hospital items:", len(items), "| vocab entries:", len(v), v.source.value_counts().to_dict(), "| codes:", v.code.nunique())
