"""Description normalisation for matching. Rules come from measured hospital habits (see DECISIONS ADR-016):
hospital prefixes seen in >2.5% of a hospital's descriptions (hc, pr, hb, hchg, chg) are dropped; a small hand-built
abbreviation map (from the most frequent short tokens) is expanded. Pure, idempotent, never raises."""
import re

PREFIX = {"hc", "pr", "hb", "hchg", "chg"}
ABBREV = {"inj": "injection", "injs": "injection", "cath": "catheter", "fem": "femoral",
          "tib": "tibial", "cann": "cannulated", "spn": "spine", "iol": "intraocular lens", "imp": "implant", "stnt": "stent",
          "strl": "sterile", "bln": "balloon", "cort": "cortical", "lok": "locking", "ins": "insert", "proc": "procedure",
          "ct": "computed tomography", "us": "ultrasound", "mri": "magnetic resonance imaging", "iv": "intravenous",
          "po": "oral", "im": "intramuscular", "sc": "subcutaneous", "rt": "right", "lt": "left", "bilat": "bilateral",
          "ea": "each", "addl": "additional", "add'l": "additional", "sngl": "single", "unlis": "unlisted"}
_SPLIT = re.compile(r"[^a-z0-9']+")
_WITHOUT, _WITH = re.compile(r"\bw/o\b"), re.compile(r"\bw/(?=\s|$|[a-z])")
_UNIT = re.compile(r"^(\d+)(mg|ml|mm|cm|gm|g|mcg|unit|units|iu)$")


def normalize(text: str | None) -> str:
    t0 = _WITH.sub(" with ", _WITHOUT.sub(" without ", (text or "").lower()))
    toks = [t for t in _SPLIT.split(t0) if t]
    while toks and toks[0] in PREFIX:
        toks = toks[1:]
    out: list[str] = []
    for t in toks:
        m = _UNIT.match(t)
        parts = [m.group(1), m.group(2)] if m else [t]
        for p in parts:
            out.extend(ABBREV.get(p, p).split())
    return " ".join(out)


def code_family(code: str) -> str:
    """Coarse family used to stratify evaluation."""
    c = (code or "").strip().upper()
    if len(c) == 5 and c.isdigit():
        return "cpt_numeric"
    if len(c) == 3 and c.isdigit():
        return "ms_drg"
    if c[:1] == "J":
        return "drug_J"
    if c[:1] in "CLVEGKPQRSTABDHM" and len(c) == 5:
        return "device_or_other_hcpcs"
    return "other"
