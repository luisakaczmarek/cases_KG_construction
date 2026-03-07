import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("COURTLISTENER_TOKEN")
if not TOKEN:
    print("ERROR: COURTLISTENER_TOKEN not set or empty.")
    sys.exit(1)

HEADERS = {"Authorization": f"Token {TOKEN}"}
BASE = "https://www.courtlistener.com/api/rest/v4"
INPUT_PATH = "scraped_cases.json"
SLEEP = 0.5
DAILY_LIMIT = 4800

request_count = 0


def api_get(url, params=None):
    global request_count
    request_count += 1
    if request_count % 100 == 0:
        print(f"  [requests made: {request_count}]", flush=True)
    if request_count >= DAILY_LIMIT:
        print("Daily limit approaching — save and rerun tomorrow.")
        save(data)
        sys.exit(0)
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(SLEEP)
    return resp.json()


def save(data):
    with open(INPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Load ──────────────────────────────────────────────────────────────────────
with open(INPUT_PATH) as f:
    data = json.load(f)

to_enrich = [
    citation for citation, record in data.items()
    if record.get("status") == "found"
    and "cited_opinions" not in record
]

print(f"Records to enrich: {len(to_enrich)}")

# ── First record: inspect opinion keys ───────────────────────────────────────
_inspected = False

for i, citation in enumerate(to_enrich):
    record = data[citation]
    cluster_id = record.get("cluster_id")
    if not cluster_id:
        record["cited_opinions"] = []
        save(data)
        continue

    try:
        op_data = api_get(
            f"{BASE}/opinions/",
            params={"cluster": cluster_id, "type": "010combined"},
        )

        if not op_data.get("results"):
            record["cited_opinions"] = []
            save(data)
            continue

        opinion = op_data["results"][0]

        # Inspect keys on first result to confirm citation field name
        if not _inspected:
            print("\n=== Opinion keys (first result) ===")
            print(list(opinion.keys()))
            print()
            _inspected = True

        # Extract cited opinions — adjust field name if keys printout shows otherwise
        cited_raw = opinion.get("opinions_cited") or opinion.get("citations") or []
        cited_ids = []
        for entry in cited_raw:
            if isinstance(entry, dict):
                cited_ids.append(entry.get("id") or entry.get("resource_uri"))
            else:
                cited_ids.append(entry)

        record["cited_opinions"] = [c for c in cited_ids if c]

    except Exception as e:
        print(f"  ERROR on '{citation}': {e}", flush=True)
        record["cited_opinions"] = None  # None = failed, distinct from [] = genuinely no citations

    save(data)

    if (i + 1) % 50 == 0:
        enriched = sum(1 for r in data.values() if "cited_opinions" in r)
        print(f"  [{i+1}/{len(to_enrich)}] enriched so far: {enriched}", flush=True)

# ── Summary ───────────────────────────────────────────────────────────────────
enriched = sum(1 for r in data.values() if r.get("cited_opinions") is not None and "cited_opinions" in r)
failed = sum(1 for r in data.values() if r.get("cited_opinions") is None)
empty = sum(1 for r in data.values() if r.get("cited_opinions") == [])

print("\n=== Enrichment Summary ===")
print(f"  Enriched (with citations) : {enriched - empty}")
print(f"  Enriched (no citations)   : {empty}")
print(f"  Failed                    : {failed}")
