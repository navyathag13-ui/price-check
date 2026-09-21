"""Stage one (hospital, source-version) from silver into a deduplicated, keyed Parquet file.

Identity of a price fact (business key): hospital, description, code, code_type, setting, billing_class,
payer, plan, price_type. Two rows can share that key with different amounts (e.g. the file lists a line twice at
different prices); rather than pick one and lose data, they get a deterministic `dup_seq` (ordered by amount) that
is part of the key. Exact duplicate rows collapse. Everything else (amount, methodology, modifiers, alt_codes)
is an *attribute*; `row_hash` changes when any attribute changes -> new SCD version.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

SEP = "chr(31)"
KEY_COLS = ["hospital_slug", "description", "code", "code_type", "setting", "billing_class", "payer", "plan", "price_type"]


def _c(col: str) -> str:
    return f"coalesce(cast({col} as varchar), '')"


def stage(silver_glob: str, out_path: Path, tmp_dir: Path, memory_limit: str = "10GB") -> dict:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'; SET temp_directory='{tmp_dir}'; SET preserve_insertion_order=false")
    key_expr = f"concat_ws({SEP}, " + ", ".join(_c(c) for c in KEY_COLS) + ")"
    part = ", ".join(KEY_COLS)
    con.execute(f"""
        COPY (
          WITH src AS (
            SELECT DISTINCT hospital_slug, description, code, code_type, alt_codes, setting, billing_class, payer, plan,
                            price_type, amount, methodology, modifiers
            FROM read_parquet('{silver_glob}')
          ), keyed AS (
            SELECT *, {key_expr} AS base_key,
                   row_number() OVER (PARTITION BY {part}
                        ORDER BY amount, {_c('methodology')}, {_c('modifiers')}, {_c('alt_codes')}) - 1 AS dup_seq
            FROM src
          )
          SELECT md5(base_key || ':' || cast(dup_seq as varchar)) AS key_hash,
                 hospital_slug, description, code, code_type, alt_codes, setting, billing_class, payer, plan,
                 price_type, cast(dup_seq as integer) AS dup_seq, amount, methodology, modifiers,
                 md5(concat_ws({SEP}, cast(amount as varchar), {_c('methodology')}, {_c('modifiers')}, {_c('alt_codes')})) AS row_hash
          FROM keyed
        ) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)
    """)
    n_in = con.execute(f"SELECT count(*) FROM read_parquet('{silver_glob}')").fetchone()[0]
    n_out, n_conflict_keys = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE dup_seq > 0) FROM read_parquet('{out_path}')").fetchone()
    con.close()
    return {"silver_rows": n_in, "staged_rows": n_out, "collapsed_exact_duplicates_and_generic_repeats": n_in - n_out,
            "rows_with_key_conflict_dup_seq_gt0": n_conflict_keys}
