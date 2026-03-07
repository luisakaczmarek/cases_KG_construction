import argparse
import json
import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("COURTLISTENER_TOKEN")
if not TOKEN:
    print("ERROR: COURTLISTENER_TOKEN not set or empty. Check your .env file.")
    sys.exit(1)

HEADERS = {"Authorization": f"Token {TOKEN}"}
BASE = "https://www.courtlistener.com/api/rest/v4"
DATASET_PATH = "legal_hallucinations/dataset.csv"
OUTPUT_PATH = "scraped_cases.json"
SLEEP = 0.5
DAILY_LIMIT = 4800
RELEVANT_TASKS = {"case_existence", "court_id", "citation_retrieval", "majority_author", "cited_precedent", "year_overruled"}

parser = argparse.ArgumentParser()
parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
parser.add_argument("--retry-errors", action="store_true", help="Retry previously errored citations")
args = parser.parse_args()

# ── 1. Load dataset and inspect citation column ───────────────────────────────
df = pd.read_csv(DATASET_PATH, low_memory=False)

print("=== Column names ===")
print(list(df.columns))
print()

citation_col = None
for candidate in df.columns:
    if "citation" in candidate.lower():
        citation_col = candidate
        break

if citation_col is None:
    print("ERROR: No column with 'citation' in its name found.")
    sys.exit(1)

print(f"=== Citation column: '{citation_col}' — 5 example values ===")
examples = (
    df[citation_col]
    .dropna()
    .loc[lambda s: s != "citation"]
    .unique()[:5]
)
for ex in examples:
    print(" ", ex)
print()

print("Please confirm the citation column looks correct before I continue.")
if args.yes:
    print("(--yes flag set, proceeding automatically)")
else:
    response = input("Type 'yes' to proceed, or anything else to abort: ").strip().lower()
    if response != "yes":
        print("Aborted.")
        sys.exit(0)

# ── 2. Filter to relevant tasks only ─────────────────────────────────────────
relevant_rows = df[df["task"].isin(RELEVANT_TASKS)]
raw_citations = (
    relevant_rows[citation_col]
    .dropna()
    .unique()
    .tolist()
)

# Clean: strip trailing periods, drop literal "citation" header strings
citations = []
seen = set()
for c in raw_citations:
    c = str(c).strip().rstrip(".")
    if c.lower() == "citation" or not c:
        continue
    if c not in seen:
        seen.add(c)
        citations.append(c)

print(f"\nUnique citations after task filter ({', '.join(sorted(RELEVANT_TASKS))}): {len(citations)}")

# ── 3. Resume support ─────────────────────────────────────────────────────────
if os.path.exists(OUTPUT_PATH):
    with open(OUTPUT_PATH) as f:
        results = json.load(f)
    if args.retry_errors:
        error_keys = [k for k, v in results.items() if v.get("status") == "error"]
        for k in error_keys:
            del results[k]
        print(f"Resuming — {len(results)} citations already scraped, retrying {len(error_keys)} errors.")
    else:
        print(f"Resuming — {len(results)} citations already scraped.")
else:
    results = {}

remaining = [c for c in citations if c not in results]
print(f"Citations remaining to scrape: {len(remaining)}\n")

judge_cache = {}
request_count = 0


def save():
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)


def api_get(url, params=None):
    global request_count
    request_count += 1
    if request_count % 100 == 0:
        print(f"  [requests made: {request_count}]", flush=True)
    if request_count >= DAILY_LIMIT:
        print("Daily limit approaching — run again tomorrow to resume")
        save()
        sys.exit(0)
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(SLEEP)
    return resp.json()


# ── 4. Scrape ─────────────────────────────────────────────────────────────────
for i, citation in enumerate(remaining):
    try:
        # Request 1: v4 search API lookup by citation string
        search_data = api_get(
            f"{BASE}/search/",
            params={"q": f'"{citation}"', "type": "o"},
        )

        if not search_data.get("results"):
            results[citation] = {"status": "not_found"}
            save()
            continue

        hit = search_data["results"][0]
        cluster_id = hit.get("cluster_id")
        record = {
            "status": "found",
            "cluster_id": cluster_id,
            "case_name": hit.get("caseName"),
            "court": hit.get("court"),
            "date_filed": hit.get("dateFiled"),
            "plain_text": None,
            "author_id": None,
            "judge_name": None,
        }

        # Request 2: opinion text
        op_data = api_get(
            f"{BASE}/opinions/",
            params={"cluster": cluster_id, "type": "010combined"},
        )
        if op_data.get("results"):
            opinion = op_data["results"][0]
            record["author_id"] = opinion.get("author_id") or opinion.get("author")
            text = opinion.get("plain_text", "").strip()
            if not text:
                text = opinion.get("html", "").strip()
            record["plain_text"] = text or None

        # Request 3: judge lookup (cached)
        author_id = record["author_id"]
        if author_id:
            if author_id in judge_cache:
                record["judge_name"] = judge_cache[author_id]
            else:
                try:
                    person = api_get(f"{BASE}/people/{author_id}/")
                    name = person.get("name_full") or (
                        f"{person.get('name_first', '')} {person.get('name_last', '')}".strip()
                    )
                    judge_cache[author_id] = name
                    record["judge_name"] = name
                except Exception as e:
                    print(f"    Judge lookup failed for author_id={author_id}: {e}", flush=True)

        results[citation] = record

    except Exception as e:
        print(f"  ERROR on '{citation}': {e}", flush=True)
        results[citation] = {"status": "error", "error": str(e)}

    save()

    if (i + 1) % 10 == 0:
        found = sum(1 for v in results.values() if v.get("status") == "found")
        not_found = sum(1 for v in results.values() if v.get("status") == "not_found")
        print(
            f"  [{i+1}/{len(remaining)}] found={found} not_found={not_found} "
            f"errors={len(results)-found-not_found}",
            flush=True,
        )

# ── 5. Summary ────────────────────────────────────────────────────────────────
total = len(results)
found = sum(1 for v in results.values() if v.get("status") == "found")
not_found = sum(1 for v in results.values() if v.get("status") == "not_found")
errors = sum(1 for v in results.values() if v.get("status") == "error")
coverage = (found / total * 100) if total else 0

print("\n=== Final Summary ===")
print(f"  Total citations processed : {total}")
print(f"  Found                     : {found}")
print(f"  Not found                 : {not_found}")
print(f"  Errors                    : {errors}")
print(f"  Coverage                  : {coverage:.1f}%")
