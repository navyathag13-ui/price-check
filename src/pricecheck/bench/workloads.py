"""The three core transformations, as dialect-neutral SQL. Both engines run the SAME text (only MEDIAN differs)."""
BASE_FILTER = "code_type IN ('CPT','HCPCS','MS-DRG') AND price_type IN ('negotiated','cash','gross','min','max')"

def sql(median):
    m = median
    return {
        # W1: staging - distinct + dup_seq window + key hashing (what history/stage.py does)
        "W1_dedupe_keys": f"""
            WITH d AS (SELECT DISTINCT hospital_slug, description, code, code_type, setting, billing_class, payer, plan, price_type, amount
                       FROM t WHERE {BASE_FILTER}),
            k AS (SELECT *, row_number() OVER (PARTITION BY hospital_slug, description, code, code_type, setting, billing_class, payer, plan, price_type
                                               ORDER BY amount) - 1 AS dup_seq FROM d)
            SELECT count(*) AS n, sum(CASE WHEN dup_seq > 0 THEN 1 ELSE 0 END) AS n_dup,
                   count(DISTINCT md5(concat(hospital_slug, '|', description, '|', code, '|', price_type, '|', cast(dup_seq AS string)))) AS n_keys FROM k""",
        # W2: peer statistics - group median and MAD, then robust-z flag count (what anomaly/features.py does)
        "W2_peer_stats": f"""
            WITH b AS (SELECT code, price_type, coalesce(setting,'na') AS s, coalesce(billing_class,'na') AS c, hospital_slug, ln(cast(amount AS double)) AS la
                       FROM t WHERE price_type IN ('negotiated','cash','gross') AND code_type IN ('CPT','HCPCS','MS-DRG') AND amount > 0),
            g AS (SELECT code, price_type, s, c, count(*) AS n, count(DISTINCT hospital_slug) AS nh, {m('la')} AS med FROM b GROUP BY code, price_type, s, c),
            g2 AS (SELECT g.code, g.price_type, g.s, g.c, g.n, g.nh, g.med, {m('abs(b.la - g.med)')} AS mad
                   FROM b JOIN g ON b.code = g.code AND b.price_type = g.price_type AND b.s = g.s AND b.c = g.c
                   GROUP BY g.code, g.price_type, g.s, g.c, g.n, g.nh, g.med),
            z AS (SELECT b.la, (b.la - g2.med) / greatest(1.4826 * g2.mad, 0.1) AS rz FROM b JOIN g2
                  ON b.code = g2.code AND b.price_type = g2.price_type AND b.s = g2.s AND b.c = g2.c WHERE g2.nh >= 5 AND g2.n >= 30)
            SELECT count(*) AS scored, sum(CASE WHEN abs(rz) >= 5 THEN 1 ELSE 0 END) AS flagged FROM z""",
        # W3: item context join - per-item gross/min/max medians joined back to negotiated rows (internal-consistency rules)
        "W3_item_context": f"""
            WITH i AS (SELECT hospital_slug, code, description, coalesce(setting,'na') AS s, coalesce(billing_class,'na') AS c,
                              {m("CASE WHEN price_type='gross' THEN cast(amount AS double) END")} AS gross,
                              {m("CASE WHEN price_type='min' THEN cast(amount AS double) END")} AS mn,
                              {m("CASE WHEN price_type='max' THEN cast(amount AS double) END")} AS mx
                       FROM t WHERE code_type IN ('CPT','HCPCS','MS-DRG') GROUP BY hospital_slug, code, description, coalesce(setting,'na'), coalesce(billing_class,'na'))
            SELECT count(*) AS n, sum(CASE WHEN r.amount > 1.1 * i.gross THEN 1 ELSE 0 END) AS neg_gt_gross,
                   sum(CASE WHEN r.amount < 0.9 * i.mn OR r.amount > 1.1 * i.mx THEN 1 ELSE 0 END) AS out_of_range
            FROM t r JOIN i ON r.hospital_slug = i.hospital_slug AND r.code = i.code AND r.description = i.description
                 AND coalesce(r.setting,'na') = i.s AND coalesce(r.billing_class,'na') = i.c
            WHERE r.price_type = 'negotiated' AND r.code_type IN ('CPT','HCPCS','MS-DRG')""",
    }

DUCK = lambda x: f"median({x})"      # noqa: E731
SPARK = lambda x: f"percentile({x}, 0.5)"   # noqa: E731  (exact percentile, like DuckDB median)
