"""
Build opinion_cluster_map.json: opinion_id -> cluster_id

Needed to resolve cited opinion IDs in citation_edges.json back to
cluster_ids so we can create :cites edges in Neo4j.

Fetches GET /opinions/?cluster={cluster_id}&type=010combined for each
cluster in scraped_cases.json and extracts the opinion's own ID.

Output: opinion_cluster_map.json  { opinion_id (int) -> cluster_id (int) }
"""
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("COURTLISTENER_TOKEN")
if not TOKEN:
    print("ERROR: COURTLISTENER_TOKEN not set.")
    sys.exit(1)

HEADERS       = {"Authorization": f"Token {TOKEN}"}
BASE          = "https://www.courtlistener.com/api/rest/v4"
SCRAPED_PATH  = "scraped_cases.json"
OUTPUT_PATH   = "opinion_cluster_map.json"
SLEEP         = 0.5
DAILY_LIMIT   = 4800

# ── Load scraped cases ────────────────────────────────────────────────────────
with open(SCRAPED_PATH) as f:
    scraped = json.load(f)

cluster_ids = list({
    int(v["cluster_id"])
    for v in scraped.values()
    if v.get("status") == "found" and v.get("cluster_id")
})
print(f"Unique cluster IDs to map: {len(cluster_ids):,}")

# ── Resume ────────────────────────────────────────────────────────────────────
if os.path.exists(OUTPUT_PATH):
    with open(OUTPUT_PATH) as f:
        opinion_map = {int(k): int(v) for k, v in json.load(f).items()}
    print(f"Resuming — {len(opinion_map):,} opinions already mapped.")
else:
    opinion_map = {}

mapped_clusters = set(opinion_map.values())
remaining = [cid for cid in cluster_ids if cid not in mapped_clusters]
print(f"Remaining: {len(remaining):,}\n")


def save():
    with open(OUTPUT_PATH, "w") as f:
        json.dump(opinion_map, f)


request_count = 0

for i, cluster_id in enumerate(remaining):
    if request_count >= DAILY_LIMIT:
        save()
        print(f"Daily limit reached — run again tomorrow to resume.")
        sys.exit(0)

    try:
        request_count += 1
        resp = requests.get(
            f"{BASE}/opinions/",
            params={"cluster": cluster_id, "type": "010combined"},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(SLEEP)

        results = resp.json().get("results", [])
        if results:
            opinion_id = results[0].get("id")
            if opinion_id:
                opinion_map[int(opinion_id)] = int(cluster_id)

    except Exception as e:
        print(f"  ERROR on cluster {cluster_id}: {e}", flush=True)

    if (i + 1) % 500 == 0:
        save()
        print(f"  [{i+1}/{len(remaining)}] mapped so far: {len(opinion_map):,}", flush=True)

save()
print(f"\nDone. opinion_cluster_map.json: {len(opinion_map):,} entries")
