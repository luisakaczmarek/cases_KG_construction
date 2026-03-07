"""
Step 1.4 — Citation normalization with eyecite
Builds citation_lookup.json: normalized_citation_string -> cluster_id
Handles: year suffixes, trailing periods, per curiam, parallel citations
"""
import json
import re

from eyecite import get_citations
from eyecite.models import FullCaseCitation

SCRAPED_PATH = "scraped_cases.json"
OUTPUT_PATH = "citation_lookup.json"


def normalize(raw: str) -> str | None:
    """Return a canonical citation string, or None if unparseable."""
    # Strip year suffix like '410 U.S. 113 (1973)'
    cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", raw.strip())
    # Strip trailing periods from reporter abbreviations
    cleaned = cleaned.rstrip(".")

    try:
        cites = get_citations(cleaned)
        full = [c for c in cites if isinstance(c, FullCaseCitation)]
        if not full:
            return None
        c = full[0]
        # Use corrected canonical form from eyecite
        return c.corrected_citation()
    except Exception:
        return None


with open(SCRAPED_PATH) as f:
    scraped = json.load(f)

lookup = {}   # normalized_string -> cluster_id
failed = []   # citations eyecite couldn't parse

for raw_citation, v in scraped.items():
    if v.get("status") != "found" or not v.get("cluster_id"):
        continue

    cluster_id = v["cluster_id"]
    normed = normalize(raw_citation)

    if normed:
        # If two citations normalize to same string, prefer the one we have
        if normed not in lookup:
            lookup[normed] = cluster_id
    else:
        # Fall back: store cleaned raw string
        cleaned = raw_citation.strip().rstrip(".")
        cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned)
        if cleaned and cleaned.lower() != "citation":
            lookup[cleaned] = cluster_id
            failed.append(raw_citation)

with open(OUTPUT_PATH, "w") as f:
    json.dump(lookup, f, indent=2)

print(f"Total cases processed  : {sum(1 for v in scraped.values() if v.get('status')=='found')}")
print(f"Lookup entries written  : {len(lookup)}")
print(f"eyecite parse failures  : {len(failed)} (stored by cleaned raw string)")
print(f"Output: {OUTPUT_PATH}")
if failed:
    print("\nSample unparseable citations:")
    for c in failed[:10]:
        print(f"  {c!r}")
