# Architecture Decision Records

Short ADRs. Each states the decision, the alternatives rejected, and the evidence. Anything
marked **UNVERIFIED** has not been measured or confirmed and must not be quoted as fact.
Status: Phase 1 in progress; ADRs 001-005 are decided, later ones are added as their phase lands.

---

## ADR-001: Local bronze first, no cloud resources until Phase 7/8
**Decision.** Phases 1-6 run on local disk (bronze = immutable raw files under `data/bronze/`).
Azure resources are created only when serving/orchestration need them, after cost approval.
**Alternatives rejected.** Creating ADLS Gen2 now: adds spend and burns free-credit time
(new-account credit is time-limited) for no Phase 1-6 benefit. The bronze layout is
path-compatible with ADLS (`<slug>/<sha256>/<file>`), so the later upload is a copy.
**Evidence.** ~6.4 GB of files (sizes below); local disk had 361 GB free.

## ADR-002: Content-addressed, append-only bronze
**Decision.** Raw bytes are stored untouched at `bronze/<hospital>/<sha256>/<original filename>`,
read-only (0444), and every fetch attempt (including failures and duplicates) is appended to
`bronze/manifest.jsonl` with URL, final URL, HTTP headers, size, SHA-256, duration, robots.txt result.
**Alternatives rejected.** Overwrite-in-place by hospital (loses history, breaks "re-run a past
report exactly"); ETag/Last-Modified as change detector (several hosts send neither; hash is the
only universal signal).
**Consequence.** A changed file becomes a new directory; nothing is ever edited or deleted.

## ADR-003: Polite ingestion: one connection per host, sequential per host, identifying UA
**Decision.** Downloader uses a fixed 2 s delay per request, one in-flight request per host,
an identifying User-Agent, and records each host's robots.txt. Parallelism is allowed only
*across* hosts. Hosts that returned 403 to automated requests (Mayo Clinic, Johns Hopkins,
UW Medicine, Mount Sinai) were excluded, not worked around.
**Alternatives rejected.** Spoofing a browser UA or rotating IPs to get past 403s (violates
"respect terms"); single global sequential queue (measured ~1 MB/s, ~1.8 h estimate; sharding by
host is compliant and faster).
**Note.** Several hospitals share one host (e.g. UnityPoint and Atrium both use
`sthpiprd.blob.core.windows.net`), so those are kept in one sequential shard.
**Terms of use: UNVERIFIED.** No hospital ToU page has been read yet; only robots.txt is recorded.
The files are published under the CMS price-transparency mandate; no redistribution of raw files
is done by this repo (bronze is gitignored).

## ADR-004: CPT handled as an identifier, never as licensed text
**Decision.** CPT codes are stored as opaque codes. This project ships no AMA CPT descriptions.
Descriptions come from (a) the hospital's own file, (b) CMS HCPCS Level II, (c) CMS MS-DRG Table 5.
**Evidence (measured).** The CMS October 2026 alpha-numeric HCPCS file (`HCPC2026_OCT_ANWEB_v2.txt`,
16,900 lines) has 16,320 lines beginning with a Level II code (letter + 4 digits), which are **8,770 distinct codes with a long
description** (the remaining lines are continuation/other record types; corrected in Phase 5, this ADR first said
"16,320 codes"), and **0 five-digit numeric CPT-style codes**. So the free CMS reference cannot describe most procedure codes hospitals publish
(CPT). Consequence for Phase 5: ground truth and semantic matching must lean on hospital
descriptions and MS-DRG titles, and the labeled set cannot use AMA text as the label source.
**CMS licensing text: UNVERIFIED.** The CMS quarterly-update page has no license statement; I did
not find or read the CMS/AMA license terms beyond that.
**Alternatives rejected.** Scraping CPT descriptions from third-party sites (license risk);
buying an AMA license (out of scope).

## ADR-005: Reference data is pinned by hash
**Decision.** `bronze`-style manifest for reference data (`data/reference/manifest.jsonl`):
HCPCS October 2026 release (published 2026-09-10) and FY2026 IPPS Final Rule Table 5 (MS-DRG).
**Caveat.** Table 5 is dated 2025-07-31 (FY2026 rule). CMS also lists a v43.1 effective
2026-04-01 and an FY2027 v44 definitions manual; I have **not** checked whether Table 5 for those
supersedes it. Matching in Phase 5 must record which release it used.

---

## ADR-006: Layout is per-file, not per-hospital; parsers must be layout-agnostic and BOM-safe
**Decision.** Phase 2 gets one parser per layout (tall CSV, wide CSV, JSON) plus a per-source contract,
selected from the profile, not assumed from the hospital.
**Evidence (measured, see `docs/phase1_report.md`).** Of 20 profiled files: 12 tall CSV, 2 wide CSV
(NYU Tisch, MD Anderson), 6 JSON (incl. MSK, Providence, Stanford, UCSF, UChicago, Cedars-Sinai). Declared
template version is 3.0.0 everywhere except **Cedars-Sinai, still on 2.0.0** despite the 2026 v3 deadline.
Three JSON files (Stanford, UCSF, UChicago) begin with a UTF-8 byte-order mark that the streaming JSON
parser rejects; found because the profiler failed on them, fixed and covered by a regression test.
**Caveat.** "rows / items" counts CSV data rows for CSV files but `standard_charge_information` items for JSON;
the units differ and must not be compared across layouts.
**Ops finding.** Atrium's 2.88 GB download failed once with a broken pipe mid-transfer (retry in progress);
robots.txt returned 400/403/404 on several hosts (no policy to honour or a block page), recorded in the manifest.

---

## ADR-007: Contracts are per-source, versioned YAML; file-level violations quarantine, row-level ones are logged
**Decision.** `contracts/<slug>.v1.yaml` (pydantic-validated) states layout, accepted/deprecated template
versions, required columns, expected fixed columns, allowed enums, amount cap, max reject rate. On arrival:
(1) wrong layout / unaccepted version / missing required column => **quarantine record + error alert, nothing promoted**;
(2) new or vanished non-payer columns or a deprecated version => **warning alert, still processed**;
(3) row/price-cell problems => **rejects table with reason**, and if the reject rate exceeds the contract's
limit (or zero rows are produced) the whole file is quarantined and its partial output deleted.
Promotion is atomic (write to `.tmp`, rename, `_SUCCESS` marker) so a crash never leaves a half-promoted file.
**Alternatives rejected.** One global schema (hospitals differ: 3 files omit the CMS-required `billing_class`);
silently coercing/dropping bad rows (violates "never silently drop"); failing the whole run on any bad row
(one bad row would block a 7.5M-row file).
**Evidence.** `tests/test_quarantine_e2e.py` exercises quarantine, high-reject-rate quarantine and idempotent
promotion. Contracts were *derived from the real headers*, which surfaced the `billing_class` omissions
(NYU Tisch, OHSU, Rush) as `known_deviations`.
**Limits.** "Alert" is currently an append-only `alerts.jsonl`; real delivery (email/Action Group) is Phase 8.

## ADR-008: Canonical model is long-form, one row per price fact
**Decision.** One row per (hospital, source row, setting, billing class, payer, plan, price type) with
`price_type` in gross|cash|negotiated|min|max, `amount` decimal(14,4), primary code chosen by priority
(CPT > HCPCS > MS-DRG > APR-DRG > ICD-10-PCS > NDC > CDM > RC > LOCAL > OTHER) with the rest kept in `alt_codes`.
Tall CSV repeats gross/cash/min/max on every payer row, so generic prices are emitted once per *consecutive* item.
**Alternatives rejected.** Keeping wide (NYU has 3,733 columns; not queryable across hospitals); one row per
item with a payer array (harder to MERGE and to compare). Amounts as float (money); decimal is used.
**Correction (found in Phase 3).** This ADR originally emitted generic prices once per *consecutive item* and claimed
any error would only be harmless duplicates. That was wrong: in UnityPoint Iowa Methodist one HCPCS drug code (J1885)
appears in 117 adjacent rows (one per NDC) with *different* gross prices ($0.90, $2.20, $65.34, $88.94...), and the
parser dropped every one after the first. Fixed: generic prices are emitted on every row and exact duplicates are
collapsed in the history staging step (ADR-010). Regression test: `test_tall_generic_prices_are_never_dropped...`.
**Not loaded (counted, not hidden).** Percentage/algorithm-only negotiated charges, estimated amounts and
percentiles are outside the five required price types; counts are in `run_log.jsonl`.

## ADR-009: Bugs the tests found (recorded because they are the evidence the tests earn their place)
1. Hypothesis: a positive amount such as `4.9e-43` rounded to `0.0000` and would have been accepted as a $0 price. Fixed -> rejected as `non_positive_amount`.
2. JSON parser assumed a `peek`-able stream; caught by a `BytesIO` unit test.
3. Reading real files: NYU/OHSU/MD Anderson contain non-UTF-8 bytes (cp1252). Decoded per-byte with a counting fallback (NYU 45, OHSU 293, MD Anderson 25 bytes) instead of `errors="replace"`, which had silently hidden them in Phase 1.
4. `rejects.parquet` beside data parts broke a plain glob over the table; moved to a `rejects/` subfolder.

---

## ADR-010: History = SCD Type 2 rows in a Delta table, loaded by MERGE; snapshots, not deltas
**Decision.** `price_history` (Delta, partitioned by `hospital_slug`) keeps one row per *version* of each price fact
with `effective_from`, `effective_to`, `is_current`, `closed_by_source_sha256`, `change_reason` (changed|removed).
A hospital file is a full snapshot, so loading a new hash computes the diff against that hospital's current rows and
runs one MERGE on the surrogate `row_id`: close changed/removed rows, insert new versions and new keys; unchanged rows
are never rewritten. First sight of a hospital is a plain append. A `(slug, sha)` already in `ingestion_ledger` is skipped
(idempotent); an identical snapshot under a new hash is a recorded no-op with no new table version.
**Identity of a price fact** = hospital, description, code, code_type, setting, billing_class, payer, plan, price_type
(+`dup_seq`). Same key with different amounts (a hospital listing a line twice at two prices) keeps *both*, ordered by
amount, instead of picking one. Description is part of identity: a hospital retyping a description shows as remove+add
(accepted; alternative of excluding it would merge unrelated lines that share a CDM code).
**Alternatives rejected.** Overwriting current state (loses history); append-only snapshots with no keys (cannot answer
"what changed" without a full diff every query, and 5x the storage); Spark for this step (delta-rs + DuckDB did the whole
real load in minutes on a laptop; Spark comparison is Phase 6, not assumed).
**Why two time-travel mechanisms.** Delta versions give exact table state; SCD columns give business-time queries.
The reproducibility script checks that they agree.

## ADR-011: Reads go through DuckDB's native Delta reader, not a delta-rs pyarrow dataset
**Evidence (a failure, not a preference).** After the first MERGE, delta-rs writes string columns as Arrow `string_view`;
registering `DeltaTable.to_pyarrow_dataset()` in DuckDB then failed with `Function 'greater_equal' has no kernel matching
input types (string, string_view)`. DuckDB's `delta_scan(path, version=N)` reads the same table correctly, including
time travel (version 0 returned the original 685,917 rows after a merge), so all reads use it. Regression test:
`test_two_consecutive_merges_then_time_travel`.

## ADR-012: Reproducibility is proven with a script whose failure is possible
`scripts/prove_reproducibility.py` loads a real hospital as version 1, records a report (Delta version + SHA-256 of the
output bytes), ingests a version 2, then requires: the latest-state report **differs** (so the test is not vacuous), the
recorded report re-runs **byte-identical** via time travel, and an independent SCD-column point-in-time query gives the
same bytes. **Limit, stated plainly:** version 2 is *synthetic* (2% of prices +10%, 1% removed, 1% new lines derived from
the real file, flagged `synthetic=true` in the ledger) because we hold only one real version per hospital so far. It proves
the mechanism, not how hospitals actually change files. Real second versions will flow through the same code.
**Not covered:** `VACUUM` deletes old files and would break time travel beyond the retention window; retention is not yet
configured (Phase 6/8).

## ADR-013: Observations from the first real report that later phases must handle
From the recorded real report (`reports/outputs/91f166ac89a2.csv`, Delta version 20):
- Hospitals label the *same* numeric procedure code with different `code_type` (CPT at 15 hospitals, HCPCS at 7 for code 11043). Code type is not a reliable identity; the gold layer must key on the code string and treat CPT/HCPCS Level I as one namespace.
- Spreads are wide and include implausible lows: CPT 11043 negotiated ranges $0.25 to $40,293 (median $81.36). Not judged here; it is the input to Phase 4's anomaly work.
- Storage: the history Delta table is 4.1 GB versus 1.0 GB for the zstd silver Parquet it came from (Delta written with default compression, unoptimised). Not yet compacted or re-compressed; that is Phase 6 and will be measured, not assumed.

---

## ADR-014: Quality score = four transparent ratios, equal weights, not validated against ground truth
Completeness, validity, consistency, freshness (definitions in `quality/scores.py`), each 0..1, averaged x100, with the
raw metrics stored beside the score (`docs/quality_scores.csv`, Delta `quality_scores`). Equal weights and a 365-day
freshness window (CMS requires at least annual updates) are **judgment calls**. Sensitivity: hospital ordering stays close
under alternative weights (Spearman 0.95-0.97) but drops to 0.86 if freshness is removed, so freshness genuinely drives
ranks. There is no ground truth for "quality"; the score ranks files relative to each other, it does not certify them.
**Alternative rejected:** a single ML-derived score (nothing to train it against).

## ADR-015: Anomaly detection = fixed statistical rules + Isolation Forest; results reported as measured, including unflattering ones
Thresholds were fixed before looking at flags and not tuned on the injection test. **Measured, see docs/phase4_report.md:**
1. Pooled recall on 9 injected corruption types is 81.5% (rules 81.3%); the headline hides a split: crude x10/x100 scaling of *one* price is caught 83-99% of the time because the item's own gross/min/max contradicts it, but a **consistent unit error** (whole item scaled together) is caught only 19.8% (x10) and 42.8% (x100).
2. The peer comparison alone is a weak separator: real cross-hospital dispersion is huge (median log-scale ~1.1). At |z|>=5 it flags 2.8% of clean rows and catches 16% of x10 unit errors; lowering to 3 doubles the noise for 36% recall.
3. The Isolation Forest adds ~0.3 points of recall over the rules on injections (95.6% -> 95.9% on the first 7 types). Its one clear win: it surfaced Sanford's negotiated price of exactly $1.00 on items with $9k-$34k gross (109,312 such prices at Sanford, 102,613 on items with gross >= $100), which no rule targeted. Verdict: keep it, but do not claim it is what makes detection work.
4. Estimated precision of the flags is ~30-32% by an AI-labeled review of 103 rows against a protocol committed before sampling. Broad internal-consistency rules are the main noise source (R3 out-of-min/max ~10%, R4 cash>gross ~0% likely-error). This is not a human/domain-expert review and the sample is clustered by hospital; treat as order-of-magnitude.
5. Known false positive, pinned in a test: rule R5 flags $99,999.94, a legitimate price for a pneumatic VAD driver (peer median $113k). All 3 R5 hits were false.
**What it misses (stated, not hidden):** errors that are consistent across an item's own prices; errors in codes with too few peers (only 43% of negotiated rows are peer-scorable); wrong-but-plausible prices; systematic hospital-wide bias; anything I did not think to inject. **Circularity:** recall on corruptions I invented tests only what I imagined.
**v2 rule candidates (not applied, so the reported numbers stay pre-registered):** negotiated == $1.00 where item gross >= $100; UIHC-style $1.00 gross charges; peer groups that ignore catch-all codes like A9270/J3490 that mix unrelated products.

---

## ADR-016: Procedure matching vocabulary is hospital-submitted text + CMS references, matched leave-one-hospital-out
**Decision.** A 103,941-entry vocabulary: 94,399 normalised (description, code) pairs pooled from all 21 hospitals'
own submitted descriptions (capped at 6 per code, ranked by how many hospitals agree), plus 8,770 CMS HCPCS Level II
long descriptions and 772 CMS MS-DRG titles. When matching an item from hospital H, vocabulary entries contributed
*only* by H are masked out (a 64-bit hospital bitmask per entry), so a hospital can never match trivially against its
own text -- this is the honest analogue of a train/test split for a lookup table instead of a trained model.
Normalisation (`matching/normalize.py`) strips hospital-specific prefixes (`hc`, `pr`, `hb`, `hchg`, `chg` -- found by
frequency analysis of real descriptions, not guessed) and expands abbreviations found the same way (`w/o`->without,
`cath`->catheter, `iol`->intraocular lens, etc). Since CPT text can't be shipped (ADR-004), CPT coverage in the
vocabulary depends entirely on *other hospitals* having described the same CPT code -- there is no official CPT text
anywhere in this system.
**Alternatives rejected.** A single shared abbreviation dictionary sourced from a style guide (untested against this
project's actual data); embedding the description text itself as the key rather than normalising first (measured
worse recall in early testing, not kept).

## ADR-017: Three matching methods measured on a 200-item stratified test set; tiered design calibrated on a separate 3,000-item dev set
**Decision & measured results (`docs/phase5_report.md`, full numbers there):**
1. **(a) rules + fuzzy (rapidfuzz WRatio):** 47.5% top-1 accuracy overall, 90.3% on the subset an exact normalised-text
   match resolves (89 of 200 items), $0 marginal cost, 189ms median (dominated by scanning 103,941 candidate strings).
2. **(b) embedding search (all-MiniLM-L6-v2 via sentence-transformers, FAISS flat index, Apple MPS):** 57.0% top-1
   accuracy, $0 marginal cost, 10ms median (index build was a one-time 59s cost). Recall@10 (true code in the top 10)
   is 78.5% -- this ceiling matters because the LLM tier consumes exactly those top-10 candidates.
3. **(c) LLM (Azure OpenAI `gpt-4.1-mini`, structured JSON output):** **candidates mode** (choose among the
   embedding's top-10, or null) scored 51.5%, ~6s median latency, ~$0.18/1,000 items (estimate, see cost caveat
   below). **Free mode** (no candidates, recall from the model's own knowledge) scored **12.0%** -- the model cannot
   reliably recall exact 5-digit procedure codes from memory; giving it a short list to choose from is what makes it
   usable at all. This is a real, measured result, not assumed.
4. **On the genuinely hard tail** (1,176 dev items where *both* fuzzy<0.9 and embedding<0.9): LLM-candidates accuracy
   was only 23.0% (26.0% restricted to the model's own "high confidence" answers) -- worse than on the full test set,
   because this subset is disproportionately catch-all/device HCPCS codes (C17xx, J3490, J8499...) that generically
   describe hundreds of different physical parts, which no method here resolves well.
**Tiered design, calibrated on dev only (never on the numbers reported above), applied once to test:** target >=95%
dev precision per tier at >=30 supporting examples. Only the exact/fuzzy tier reached that bar on its own (at
threshold 0.92); the embedding tier alone never reached 95% precision on the residual pool at any tested threshold --
**its real contribution is as the LLM's candidate generator, not as an independent confident tier.** Result on the
held-out 200-item test set: 103/200 resolved by exact/fuzzy tier (90.3% precision), 67/200 resolved by the LLM tier
gated on its own "high confidence" label (**29.9% precision** -- the model's self-reported confidence does not track
actual correctness well here), 30/200 sent to human review. Overall: 85% coverage, 66.5% precision on answered items,
56.5% recall.
**Honest conclusion, stated plainly:** the tiering strategy correctly routes the easy 50% of items to a free, fast
method. It does **not** solve the hard tail -- LLM-with-candidates on catch-all/device codes is weak, and trusting the
model's own confidence label as a quality gate would be a mistake without independent calibration (which this ADR's
measurement now provides: don't trust it above ~30% precision here).
**Cost caveat.** Azure's Retail Prices API returned no base (non-fine-tuned) `gpt-4.1-mini` meter for this region;
$/1,000-item figures use the published fine-tuned-global rate as a directional stand-in, not a confirmed bill. Real
spend is in Azure Cost Management.
**Alternatives rejected:** training a supervised classifier (no labeled set large enough, and CPT-license constraints
limit what could even be trained on); ANN index (HNSW) instead of a flat FAISS index (103,941 vectors is small enough
that a flat index's exact search was already sub-millisecond; approximate search would trade correctness for no
measured speed benefit at this scale).

## ADR-018: Spark vs. single-node (DuckDB) -- measured up to 165M rows; Spark did not become worth it in this session
**Decision & measured results (`docs/phase6_report.md`, full tables there).** The same three real transformations
(staging dedupe/key-hash, cross-hospital peer statistics, item-context join) were implemented once as dialect-neutral
SQL and run unchanged on DuckDB and local PySpark 4.2 + Delta, at 986K / 5.0M / 20.2M / 41.1M / 82.3M / 164.5M rows,
single MacBook Air (10 threads, 18GB RAM). Result digests were compared and are byte-identical across engines at
every size, so the comparison is of equivalent work, not divergent logic.
**Spark was slower at every single size tested** -- from 17-50x slower at <1M rows down to 3.5-11x slower at 164.5M
rows (4.8GB). The gap narrows as data grows because DuckDB's process RSS climbs toward the configured 11GB cap
(10.0GB at 41M rows, ~9.2GB at 82-164M, evidence of memory pressure/spilling) while Spark's stays roughly flat
(6.5-9.0GB) -- so the *trend* is real and the two curves are converging. They had **not crossed** at the largest size
tested here. Spark's own fixed ~4-6s JVM startup cost never amortized below DuckDB's total time on these workloads
either.
**What this does NOT establish:** whether Spark would win on a real multi-node cluster (this was `local[10]` on one
laptop, the opposite of what Spark is built for); whether Spark wins past 165M rows (only two points beyond the real
41.1M were tested, at reduced statistical rigor -- see caveat in the report); whether it wins on workloads with more
shuffle-heavy joins than these three. **Do not assume Spark is justified by data volume alone; on this project's real
data, at the scale actually measured, it was not.** If/when the gold layer's dbt models (Phase 7) need to run at a
size where this trend suggests Spark would win, re-measure rather than assume.
**Alternatives considered, not run:** Polars (installed, not benchmarked this session -- DuckDB's SQL-first design
matched the "same query text on both engines" comparison goal more directly; a Polars comparison is a reasonable
follow-up, not done here).

## ADR-019: Delta compaction alone does not speed up selective queries; Z-order does
**Decision & measured results (`docs/phase6_report.md`).** On the real 41.1M-row table: OPTIMIZE (file compaction,
420 fragmented files -> 16) barely changed the fraction of files a single-code query must open (419/420 -> 16/16,
i.e. ~100% either way) because compaction does not sort data -- **it fixes small-file/listing overhead, not
selectivity.** Z-ORDER BY (code) on top of that dropped file-pruning to 1/8 files and made the single-code query
faster than the original real table (0.015s vs 0.037s), because the real table is partitioned by hospital, so a
single-code query there still opens every hospital's partition; Z-order by code prunes across hospitals instead.
**Consequence for the gold layer (Phase 7):** partition by the column most incremental loads filter on for
maintenance (hospital), but Z-order (or Databricks liquid clustering, not testable in this environment -- ADR needed
if/when real Databricks compute is used) by the column point-lookup queries actually filter on (code). These are
different columns and both matter; one does not substitute for the other.
**Cost of maintenance, measured, not assumed:** OPTIMIZE took 6.4s, Z-ORDER took 62.2s on 41.1M rows -- Z-order
rewrites and re-sorts every row, so it belongs on a schedule (e.g. after each incremental load, or nightly), not
something to run per-query.

---

## ADR-020: Azure SQL serves precomputed gold marts, not the 41.1M-row fact grain
**Decision.** Only `dim_hospital` (21 rows), `dim_procedure_code` (79,213), `mart_price_comparison` (128,372),
`mart_hospital_quality` (21) are loaded into Azure SQL, via `sql/azure_sql/001_schema.sql` + `002_views.sql` +
`pricecheck.serving.load_azure_sql`. The 41.1M-row `fact_price` grain stays in Delta/DuckDB only.
**Alternatives rejected.** Loading the full fact table into Azure SQL: at ~41M rows it would consume a large share of
the free offer's 32GB storage and, more importantly, the free offer's 100,000 vCore-seconds/month is meant for a
small serving workload, not repeated full-table scans -- the marts already have everything the "pick a procedure, see
the spread" use case needs, precomputed once by dbt rather than aggregated per request.
**Consequence, stated honestly.** Azure SQL cannot answer an arbitrary ad-hoc query over individual price rows (e.g.
"show me every negotiated rate MSK has with Aetna") -- that still requires the Delta table via DuckDB/Spark. The
served API is scoped to what the marts support: search, spread-by-code, hospital quality. This is a real, documented
scope boundary, not an oversight.

## ADR-021: One query layer, two backends, resolved by environment (same pattern as the RAG project's llm_service.py)
**Decision.** `serving/db.py` resolves to Azure SQL only when all four `AZURE_SQL_*` env vars are set, else DuckDB
(the local dbt-built gold database) -- verified: 3 of 4 vars set still falls back to DuckDB, not a broken half-state.
FastAPI (`serving/api.py`) and Strawberry GraphQL (`serving/graphql_app.py`) both call the same `db.py` functions, so
REST and GraphQL can never silently disagree (checked directly: `test_graphql_matches_rest`). The Streamlit dashboard
imports the same module rather than calling either API, so there is exactly one data-access path with three
presentations, not three independent ones that could drift.
**Alternatives rejected.** A shared ORM (SQLAlchemy) across DuckDB and Azure SQL: the two engines' SQL dialects
already diverge enough (T-SQL `TOP` vs. DuckDB `LIMIT`, parameter styles) that hand-written per-backend SQL in one
place was more honest than an abstraction that would paper over real differences; separate REST/GraphQL data-access
code (rejected for the drift risk above).
**Driver note.** `pymssql` (bundled FreeTDS) was used instead of `pyodbc` + Microsoft's ODBC Driver 18 -- the latter
needs a system-level installer this environment can't run (no Homebrew, as established in ADR-000-equivalent
constraints noted throughout this project); `pip install pymssql` needed nothing beyond the venv. **Not yet verified
against a real Azure SQL Database** -- no such database has been created this session (see `sql/azure_sql/README.md`
for why: Conditional Access blocks the Azure CLI here, same constraint as the RAG project). The DuckDB path is fully
verified (96 tests, including live REST/GraphQL/dashboard checks against the real 41.1M-row-derived gold layer); the
Azure SQL path is code-complete and reviewed, not live-tested. State this distinction plainly in the README, the same
pattern used throughout this project.

---

## ADR-022: CI runs against real (if small) data, not hand-typed mocks; verified locally before trusting GitHub Actions
**Decision.** `.github/workflows/ci.yml` has three jobs: (1) lint (ruff) + the full pytest suite, which skips every
data-dependent test cleanly on a fresh checkout (verified by actually cloning this repo fresh and running the suite:
67 passed, 29 skipped, 0 failed -- this caught a real bug, see below); (2) `dbt build` against `scripts/ci_fixtures.py`
-- 3 synthetic hospitals written through the *real* `write_deltalake` path using the pipeline's actual `HISTORY_SCHEMA`
(imported from `history/delta_store.py`, not redefined), so CI exercises the real dbt models and all 27 tests, not a
mock; (3) `terraform fmt -check` + `init -backend=false` + `validate`. All three were run locally before being
trusted in CI (Terraform 1.9.8 installed standalone, same constraint as every other tool in this project -- no
Homebrew) and pass: `terraform validate` succeeds, `dbt build` against the CI fixtures is 42/42, the fresh-clone
pytest run is clean.
**Real bug found by testing against a fresh clone, not assumed away:** `manifest.jsonl`/`profile.jsonl` are
committed (small, kept as run-evidence) but the multi-GB raw bronze files they reference are correctly gitignored.
The old skip guard on `test_contract_accepts_current_real_file` checked only whether the *index* file existed, so in
a fresh clone it ran the test body and failed on a missing multi-GB file instead of skipping. Fixed to check each
referenced raw file individually (`tests/test_contracts.py::_real_file_for`).
**Also found and fixed this phase, by actually running the full lint/test suite rather than writing CI blind:** 23
genuinely unused imports (ruff F401, auto-fixed), one dead-code assignment in `matching/tiered.py` (`ans`/`ok`
computed and never used), one in `ingest/profile.py` (`depth_key`), and a `pyarrow.lib.ArrowTypeError` in
`ci_fixtures.py` itself (the Delta schema wants `decimal128` for `amount`; a plain Python `float` doesn't satisfy it).
**`terraform apply` was never run.** Same Conditional Access constraint hit throughout this project and the RAG
project before it: this tenant blocks non-interactive Azure CLI/SDK auth outside the portal/Cloud Shell, which
Terraform's azurerm provider needs. `terraform/README.md` gives the exact commands to run in Cloud Shell. The CI
`terraform` job is scoped to `validate` only, not `plan`/`apply`, for the same reason -- stated in the workflow file
itself, not hidden.
**Repo hygiene note, corrected this phase:** the Phase 4 commit accidentally committed 1.1GB of regeneratable
anomaly-detection parquet/joblib artifacts (`features.parquet` 644MB, `flags.parquet` 497MB, plus smaller ones).
Caught before the first push (verified via `git ls-remote` that nothing had landed on GitHub yet), so history was
rewritten with `git filter-repo` rather than just gitignoring going forward -- `.git` dropped from 1.0GB to 324KB.
Small JSON/CSV evidence files derived from those artifacts (`review_results.json`, `injection_eval.json`, etc.)
stayed tracked; only the large regeneratable binaries were removed.

## ADR-023: Observability -- run_metrics consolidates existing per-stage logs; alerting on shrink/shape-change/freshness
**Decision.** `observability/run_metrics.py` builds ONE Delta table (`run_metrics`) by reading each phase's own
already-existing evidence (bronze `manifest.jsonl`, silver `run_log.jsonl`, history `ingestion_ledger`, dbt's
`run_results.json`) rather than inventing a parallel logging system -- 107 real rows from this project's actual
run history on first build. `observability/alerts.py` checks three real conditions against that same evidence:
size shrink (>50% drop vs. the previous successful fetch), 3+ consecutive fetch failures, layout/template-version
change between consecutive profiles, and staleness (>45 days since `last_updated_on`, tighter than CMS's own
annual-update requirement). Real run against this project's actual bronze history: every one of the 20 hospitals
fetched only once so far shows a `stale` warning (87-300 days) -- correct behavior given a single-snapshot dataset,
not a bug; it will report cleanly once a second real fetch cycle runs.
**Bugs found while testing this module properly, not glossed over:** (1) the failure-streak check was nested inside
an `if len(ok) < 2: continue` meant only for the shrink comparison, so a hospital with fewer than 2 *successful*
fetches never got checked for a failure streak either -- fixed by separating the two checks. (2) My own first test
fixture reused the same `fetched_at` value for two different records, which silently produced a different (but
still technically "sorted") ordering than intended and made the test fail for a reason unrelated to the alerting
logic -- fixed the fixture to use distinct, real-looking timestamps, and added a companion test
(`test_two_failures_then_a_success_does_not_alert`) to lock in the correct behavior in both directions.
