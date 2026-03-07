"""
Step 2.1 — Load Case and Judge nodes into Neo4j.
Does NOT load cites or overruled_by edges (separate script).

Schema:
  (Case)-[:authored_by]->(Judge)

Case properties : citation, name, year, court_level, court_slug, cluster_id
Judge properties: name, courtlistener_id
"""
import json
import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

load_dotenv()

SCRAPED_PATH = "scraped_cases.json"
URI  = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

# ── Load data ─────────────────────────────────────────────────────────────────
print(f"Loading {SCRAPED_PATH} …")
with open(SCRAPED_PATH) as f:
    scraped = json.load(f)

found = {k: v for k, v in scraped.items() if v.get("status") == "found"}
print(f"Records with status=found: {len(found):,}")

# ── Helpers ───────────────────────────────────────────────────────────────────
def extract_year(date_filed):
    if date_filed and len(str(date_filed)) >= 4:
        try:
            return int(str(date_filed)[:4])
        except ValueError:
            return None
    return None


# ── Connect ───────────────────────────────────────────────────────────────────
driver = GraphDatabase.driver(URI, auth=AUTH)

# ── Indexes ───────────────────────────────────────────────────────────────────
with driver.session() as session:
    session.run("CREATE INDEX case_citation IF NOT EXISTS FOR (c:Case) ON (c.citation)")
    session.run("CREATE INDEX case_name     IF NOT EXISTS FOR (c:Case) ON (c.name)")
print("Indexes ensured: Case.citation, Case.name")

# ── Load ──────────────────────────────────────────────────────────────────────
case_count  = 0
edge_count  = 0
skipped     = 0
errors      = 0

with driver.session() as session:
    for citation, record in tqdm(found.items(), desc="Merging nodes", unit="rec"):
        # citation is required
        if not citation or citation.strip().lower() == "citation":
            skipped += 1
            continue

        try:
            cluster_id = record.get("cluster_id")
            court      = record.get("court")

            session.run(
                """
                MERGE (c:Case {citation: $citation})
                SET c.name        = $name,
                    c.year        = $year,
                    c.court_level = $court_level,
                    c.court_slug  = $court_slug,
                    c.cluster_id  = $cluster_id
                """,
                citation   = citation,
                name       = record.get("case_name") or None,
                year       = extract_year(record.get("date_filed")),
                court_level= court or None,
                court_slug = court or None,
                cluster_id = int(cluster_id) if cluster_id is not None else None,
            )
            case_count += 1

            judge_name = record.get("judge_name")
            author_id  = record.get("author_id")
            if judge_name:
                session.run(
                    """
                    MERGE (j:Judge {courtlistener_id: $courtlistener_id})
                    SET j.name = $name
                    WITH j
                    MATCH (c:Case {citation: $citation})
                    MERGE (c)-[:authored_by]->(j)
                    """,
                    courtlistener_id = int(author_id) if author_id is not None else None,
                    name             = judge_name,
                    citation         = citation,
                )
                edge_count += 1

        except Exception as e:
            tqdm.write(f"  ERROR on '{citation}': {e}")
            errors += 1

    # Final counts from DB
    db_cases  = session.run("MATCH (c:Case)  RETURN count(c) AS n").single()["n"]
    db_judges = session.run("MATCH (j:Judge) RETURN count(j) AS n").single()["n"]
    db_edges  = session.run("MATCH ()-[r:authored_by]->() RETURN count(r) AS n").single()["n"]

driver.close()

print("\n=== Load complete ===")
print(f"  Case nodes        : {db_cases:,}")
print(f"  Judge nodes       : {db_judges:,}")
print(f"  authored_by edges : {db_edges:,}")
print(f"  Skipped (no cite) : {skipped}")
print(f"  Errors            : {errors}")
