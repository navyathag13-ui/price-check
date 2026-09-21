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
16,900 lines) contains **16,320 Level II codes (letter + 4 digits) and 0 five-digit numeric
CPT-style codes**. So the free CMS reference cannot describe most procedure codes hospitals publish
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
