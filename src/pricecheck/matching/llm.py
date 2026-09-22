"""Method (c): LLM with structured JSON output (Azure OpenAI). Two modes: 'candidates' (choose among top-10 from the
embedding index, or NONE) and 'free' (no candidates; the model's own knowledge). Records real token usage and latency."""
from __future__ import annotations

import json
import time
from pathlib import Path

from dotenv import dotenv_values
from openai import APIConnectionError, APITimeoutError, AzureOpenAI, RateLimitError

ENV = Path("/Users/navyathag/claude timepass/fresh-repos/RAG_document_log_assistant/.env")
SCHEMA = {"name": "code_choice", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["code", "confidence", "reason"],
    "properties": {"code": {"type": ["string", "null"], "description": "the chosen CPT/HCPCS/MS-DRG code, or null if none fits"},
                   "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                   "reason": {"type": "string", "description": "one short sentence"}}}}
SYS = ("You map a hospital price-list line description to a standard procedure/supply/drug code (CPT, HCPCS Level II, or MS-DRG). "
       "Hospital descriptions are abbreviated and messy. Answer with JSON only. If nothing fits, return code null.")


class LLM:
    def __init__(self):
        e = dotenv_values(ENV)
        self.c = AzureOpenAI(azure_endpoint=e["AZURE_OPENAI_ENDPOINT"], api_key=e["AZURE_OPENAI_API_KEY"], api_version=e["AZURE_OPENAI_API_VERSION"])
        self.model = e["AZURE_OPENAI_DEPLOYMENT"]
        self.usage = {"prompt": 0, "completion": 0, "calls": 0}

    def choose(self, description: str, candidates: list[tuple[str, str]] | None):
        if candidates is not None:
            body = "Candidates (code: reference text):\n" + "\n".join(f"- {c}: {t}" for c, t in candidates) + \
                   f"\n\nDescription: {description}\nPick the best candidate code, or null if none fits."
        else:
            body = f"Description: {description}\nGive the single best standard code, or null if unsure."
        for attempt in range(12):
            try:
                t = time.monotonic()
                r = self.c.chat.completions.create(model=self.model, temperature=0, max_tokens=120,
                                                   response_format={"type": "json_schema", "json_schema": SCHEMA},
                                                   messages=[{"role": "system", "content": SYS}, {"role": "user", "content": body}])
                dt = time.monotonic() - t
                self.usage["prompt"] += r.usage.prompt_tokens; self.usage["completion"] += r.usage.completion_tokens; self.usage["calls"] += 1
                out = json.loads(r.choices[0].message.content)
                return out.get("code"), out.get("confidence", "low"), dt, r.usage.prompt_tokens, r.usage.completion_tokens
            except (RateLimitError, APIConnectionError, APITimeoutError):
                time.sleep(min(60, 4 * (attempt + 1)))
        return None, "low", 0.0, 0, 0
