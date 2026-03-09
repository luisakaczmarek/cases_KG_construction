"""
Step 2.2 — Load :cites edges into Neo4j.

Uses:
  citation_edges.json     — cluster_id -> [cited_opinion_ids]
  opinion_cluster_map.json — opinion_id -> cluster_id
  scraped_cases.json      — cluster_id -> citation string (for node lookup)

Creates: (Case)-[:cites]->(Case)
Only creates edges where both endpoints exist as Case nodes in Neo4j.
"""
import json
import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

load_dotenv()

EDGES_PATH      = "citation_edges.json"
OPINION_MAP_PATH= "opinion_cluster_map.json"
SCRAPED_PATH    = "scraped_cases.json"
URI             = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
AUTH            = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading data files…")
with open(EDGES_PATH) as f:
    edges = json.load(f)  # str(cluster_id) -> [opinion_id, ...]

with open(OPINION_MAP_PATH) as f:
    opinion_cluster = {int(k): int(v) for k, v in json.load(f).items()}
    # opinion_id -> cluster_id

with open(SCRAPED_PATH) as f:
    scraped = json.load(f)

# Build cluster_id -> citation map
cluster_to_citation = {
    int(v["cluster_id"]): citation
    for citation, v in scraped.items()
    if v.get("status") == "found" and v.get("cluster_id")
}
print(f"  citation_edges entries : {len(edges):,}")
print(f"  opinion_cluster_map    : {len(opinion_cluster):,}")
print(f"  cluster_to_citation    : {len(cluster_to_citation):,}")

# ── Build edge list ───────────────────────────────────────────────────────────
edge_pairs = []   # (source_citation, target_citation)
skipped_no_source = 0
skipped_no_target = 0

for src_cluster_str, cited_opinion_ids in edges.items():
    if not cited_opinion_ids:
        continue
    src_cluster = int(src_cluster_str)
    src_citation = cluster_to_citation.get(src_cluster)
    if not src_citation:
        skipped_no_source += 1
        continue

    for opinion_id in cited_opinion_ids:
        tgt_cluster = opinion_cluster.get(int(opinion_id))
        if not tgt_cluster:
            skipped_no_target += 1
            continue
        tgt_citation = cluster_to_citation.get(tgt_cluster)
        if not tgt_citation:
            skipped_no_target += 1
            continue
        edge_pairs.append((src_citation, tgt_citation))

print(f"\nEdge pairs resolved     : {len(edge_pairs):,}")
print(f"Skipped (no source)     : {skipped_no_source:,}")
print(f"Skipped (no target)     : {skipped_no_target:,}")

if not edge_pairs:
    print("No edges to load — make sure build_opinion_map.py has run.")
    sys.exit(0)

# ── Load into Neo4j in batches ────────────────────────────────────────────────
BATCH_SIZE = 500
driver = GraphDatabase.driver(URI, auth=AUTH)
loaded = 0
errors = 0

with driver.session() as session:
    for i in tqdm(range(0, len(edge_pairs), BATCH_SIZE), desc="Loading :cites", unit="batch"):
        batch = edge_pairs[i : i + BATCH_SIZE]
        try:
            session.run(
                """
                UNWIND $pairs AS pair
                MATCH (src:Case {citation: pair[0]})
                MATCH (tgt:Case {citation: pair[1]})
                MERGE (src)-[:cites]->(tgt)
                """,
                pairs=[[src, tgt] for src, tgt in batch],
            )
            loaded += len(batch)
        except Exception as e:
            tqdm.write(f"  ERROR on batch {i//BATCH_SIZE}: {e}")
            errors += len(batch)

    db_edges = session.run("MATCH ()-[r:cites]->() RETURN count(r) AS n").single()["n"]

driver.close()

print(f"\n=== Load complete ===")
print(f"  :cites edges in Neo4j : {db_edges:,}")
print(f"  Errors                : {errors:,}")
