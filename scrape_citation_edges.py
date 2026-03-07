"""
Step 1.3 — Scrape citation edges
For each scraped case, extract the list of opinions it cites.
Output: citation_edges.json  { opinion_id -> [cited_opinion_id, ...] }
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
    print("ERROR: COURTLISTENER_TOKEN not set. Check your .env file.")
    sys.exit(1)

HEADERS = {"Authorization": f"Token {TOKEN}"}
BASE = "https://www.courtlistener.com/api/rest/v4"
SCRAPED_PATH = "scraped_cases.json"
EDGES_PATH = "citation_edges.json"
SLEEP = 0.5
DAILY_LIMIT = 4800


def save(edges):
    with open(EDGES_PATH, "w") as f:
        json.dump(edges, f, indent=2)


# Load scraped cases — only process found ones with a cluster_id
with open(SCRAPED_PATH) as f:
    scraped = json.load(f)

cases = {
    citation: v
    for citation, v in scraped.items()
    if v.get("status") == "found" and v.get("cluster_id")
}
print(f"Found cases with cluster_id: {len(cases)}")

# Resume support
if os.path.exists(EDGES_PATH):
    with open(EDGES_PATH) as f:
        edges = json.load(f)
    print(f"Resuming — {len(edges)} cases already processed.")
else:
    edges = {}

# Use cluster_id as key (string) for deduplication — multiple citations can share a cluster
processed_clusters = set(edges.keys())
# Build list of (cluster_id, citation) deduplicated by cluster_id
seen_clusters = set()
work_list = []
for citation, v in cases.items():
    cid = str(v["cluster_id"])
    if cid not in seen_clusters:
        seen_clusters.add(cid)
        if cid not in processed_clusters:
            work_list.append(cid)

print(f"Unique cluster_ids to process: {len(seen_clusters)}")
print(f"Remaining after resume: {len(work_list)}\n")

request_count = 0

for i, cluster_id in enumerate(work_list):
    try:
        request_count += 1
        if request_count % 100 == 0:
            print(f"  [requests made: {request_count}]", flush=True)
        if request_count >= DAILY_LIMIT:
            save(edges)
            print("Daily limit approaching — run again tomorrow to resume")
            sys.exit(0)

        resp = requests.get(
            f"{BASE}/opinions/",
            params={"cluster": cluster_id, "type": "010combined"},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(SLEEP)

        results = resp.json().get("results", [])
        if not results:
            edges[cluster_id] = []
        else:
            opinion = results[0]
            cited_urls = opinion.get("opinions_cited", [])
            # Extract opinion IDs from URLs like .../opinions/1234567/
            cited_ids = []
            for url in cited_urls:
                parts = url.rstrip("/").split("/")
                if parts[-1].isdigit():
                    cited_ids.append(int(parts[-1]))
            edges[cluster_id] = cited_ids

    except Exception as e:
        print(f"  ERROR on cluster {cluster_id}: {e}", flush=True)
        edges[cluster_id] = None  # None = failed, retry later

    save(edges)

    if (i + 1) % 50 == 0:
        non_empty = sum(1 for v in edges.values() if v)
        failed = sum(1 for v in edges.values() if v is None)
        print(
            f"  [{i+1}/{len(work_list)}] processed={len(edges)} "
            f"with_edges={non_empty} failed={failed}",
            flush=True,
        )

# Summary
total = len(edges)
with_edges = sum(1 for v in edges.values() if v)
no_edges = sum(1 for v in edges.values() if v == [])
failed = sum(1 for v in edges.values() if v is None)
total_edge_count = sum(len(v) for v in edges.values() if v)

print("\n=== Final Summary ===")
print(f"  Clusters processed       : {total}")
print(f"  With outgoing citations  : {with_edges}")
print(f"  No citations found       : {no_edges}")
print(f"  Failed (will retry)      : {failed}")
print(f"  Total citation edges     : {total_edge_count:,}")
