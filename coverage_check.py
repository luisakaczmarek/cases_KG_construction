"""
Coverage check — how many dataset citations exist as Case nodes in Neo4j?

Output:
  - console: overall % + breakdown by court_level
  - coverage_report.csv: citation, court, found
"""
import os

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

DATASET_PATH = "legal_hallucinations/dataset.csv"
OUTPUT_PATH  = "coverage_report.csv"
URI          = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
AUTH         = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

RELEVANT_TASKS = {
    "case_existence", "court_id", "citation_retrieval",
    "majority_author", "cited_precedent", "year_overruled",
}

# ── Load dataset ──────────────────────────────────────────────────────────────
df = pd.read_csv(DATASET_PATH, low_memory=False)
df = df[df["task"].isin(RELEVANT_TASKS)]

pairs = (
    df[["citation", "court_level"]]
    .dropna(subset=["citation"])
    .drop_duplicates(subset=["citation"])
    .copy()
)
pairs["citation"] = pairs["citation"].str.strip().str.rstrip(".")
pairs = pairs[pairs["citation"].str.lower() != "citation"]

print(f"Unique citations to check: {len(pairs):,}")

# ── Query Neo4j ───────────────────────────────────────────────────────────────
driver = GraphDatabase.driver(URI, auth=AUTH)

with driver.session() as session:
    results = {}
    for citation in pairs["citation"]:
        row = session.run(
            "MATCH (c:Case {citation: $citation}) RETURN count(c) > 0 AS found",
            citation=citation,
        ).single()
        results[citation] = row["found"]

driver.close()

pairs["found"] = pairs["citation"].map(results)
pairs = pairs.rename(columns={"court_level": "court"})

# ── Save report ───────────────────────────────────────────────────────────────
pairs[["citation", "court", "found"]].to_csv(OUTPUT_PATH, index=False)
print(f"Saved: {OUTPUT_PATH}")

# ── Print summary ─────────────────────────────────────────────────────────────
total   = len(pairs)
found_n = pairs["found"].sum()
print(f"\n=== Overall coverage ===")
print(f"  Found : {found_n:,} / {total:,}  ({found_n / total * 100:.1f}%)")

print(f"\n=== Breakdown by court level ===")
for court, group in pairs.groupby("court"):
    n       = len(group)
    n_found = group["found"].sum()
    print(f"  {court:<10} {n_found:>5,} / {n:>5,}  ({n_found / n * 100:.1f}%)")
