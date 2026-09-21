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
