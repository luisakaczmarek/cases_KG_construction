"""
Step 3 — Query the KG for all 6 tasks and evaluate against dataset.

Strategy: batch by unique inputs per task (UNWIND), then join back to all rows.
This reduces ~543k individual queries to ~14k batched lookups.

Tasks:
  case_existence    : MATCH (c:Case {citation: $c}) RETURN count(c) > 0
  court_id          : MATCH (c:Case {citation: $c}) RETURN c.court_level
  citation_retrieval: MATCH (c:Case) WHERE toLower(c.name) CONTAINS toLower($name) RETURN c.citation LIMIT 1
  majority_author   : MATCH (c:Case {citation: $c})-[:authored_by]->(j) RETURN j.name
  cited_precedent   : MATCH (c:Case {citation: $c})-[:cites]->(p) RETURN p.citation  (list)
  year_overruled    : MATCH (c:Case {citation: $c})-[e:overruled_by]->() RETURN e.year_overruled

Output: kg_results.csv
"""
import os
import re

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

load_dotenv()

DATASET_PATH = "legal_hallucinations/dataset.csv"
OUTPUT_PATH  = "kg_results.csv"
URI          = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687").replace("neo4j://", "bolt://")
AUTH         = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

RELEVANT_TASKS = {
    "case_existence", "court_id", "citation_retrieval",
    "majority_author", "cited_precedent", "year_overruled",
}

BATCH_SIZE = 500

# ── Extract case name from citation_retrieval query string ────────────────────
_NAME_RE = re.compile(r"for (?:the [\w ]+ case )?(.+?)\?", re.IGNORECASE)

def extract_case_name(query: str) -> str | None:
    m = _NAME_RE.search(str(query))
    return m.group(1).strip() if m else None


# ── Batch Cypher queries (UNWIND) ─────────────────────────────────────────────
def batch_case_existence(session, citations):
    result = session.run(
        "UNWIND $cits AS c "
        "MATCH (n:Case {citation: c}) "
        "RETURN c AS citation, count(n) > 0 AS found",
        cits=citations,
    )
    return {r["citation"]: bool(r["found"]) for r in result}


def batch_court_id(session, citations):
    result = session.run(
        "UNWIND $cits AS c "
        "OPTIONAL MATCH (n:Case {citation: c}) "
        "RETURN c AS citation, n.court_level AS court",
        cits=citations,
    )
    return {r["citation"]: r["court"] for r in result}


def batch_majority_author(session, citations):
    result = session.run(
        "UNWIND $cits AS c "
        "OPTIONAL MATCH (n:Case {citation: c})-[:authored_by]->(j) "
        "RETURN c AS citation, j.name AS name",
        cits=citations,
    )
    return {r["citation"]: r["name"] for r in result}


def batch_cited_precedent(session, citations):
    result = session.run(
        "UNWIND $cits AS c "
        "MATCH (n:Case {citation: c})-[:cites]->(p) "
        "RETURN c AS citation, collect(p.citation) AS cited",
        cits=citations,
    )
    lookup = {r["citation"]: r["cited"] for r in result}
    # Ensure missing citations return empty list
    return {c: lookup.get(c, []) for c in citations}


def batch_year_overruled(session, citations):
    result = session.run(
        "UNWIND $cits AS c "
        "OPTIONAL MATCH (n:Case {citation: c})-[e:overruled_by]->() "
        "RETURN c AS citation, e.year_overruled AS yr",
        cits=citations,
    )
    return {r["citation"]: r["yr"] for r in result}


def batch_citation_retrieval(session, names):
    # No clean UNWIND for CONTAINS — query individually but deduplicated
    lookup = {}
    for name in names:
        if not name:
            continue
        row = session.run(
            "MATCH (c:Case) WHERE toLower(c.name) CONTAINS toLower($name) "
            "RETURN c.citation AS citation LIMIT 1",
            name=name,
        ).single()
        lookup[name] = row["citation"] if row else None
    return lookup


BATCH_FN = {
    "case_existence"    : batch_case_existence,
    "court_id"          : batch_court_id,
    "majority_author"   : batch_majority_author,
    "cited_precedent"   : batch_cited_precedent,
    "year_overruled"    : batch_year_overruled,
}

# ── Load dataset ──────────────────────────────────────────────────────────────
print("Loading dataset…")
df = pd.read_csv(DATASET_PATH, low_memory=False)
df = df[df["task"].isin(RELEVANT_TASKS)].copy()
print(f"Rows to process: {len(df):,}")

# ── Run batched queries ───────────────────────────────────────────────────────
driver = GraphDatabase.driver(URI, auth=AUTH)
kg_lookup = {}   # (task, input_key) -> answer

with driver.session() as session:

    for task in tqdm(RELEVANT_TASKS, desc="Tasks"):

        if task == "citation_retrieval":
            # Input is case name extracted from query column
            unique_names = list({
                extract_case_name(q)
                for q in df.loc[df["task"] == task, "query"]
                if extract_case_name(q)
            })
            tqdm.write(f"  {task}: {len(unique_names):,} unique names")
            result = batch_citation_retrieval(session, unique_names)
            for name, answer in result.items():
                kg_lookup[(task, name)] = answer

        else:
            unique_cits = list(
                df.loc[df["task"] == task, "citation"]
                .dropna()
                .str.strip()
                .unique()
            )
            tqdm.write(f"  {task}: {len(unique_cits):,} unique citations")
            # Process in batches
            combined = {}
            for i in range(0, len(unique_cits), BATCH_SIZE):
                batch = unique_cits[i : i + BATCH_SIZE]
                try:
                    result = BATCH_FN[task](session, batch)
                    combined.update(result)
                except Exception as e:
                    tqdm.write(f"    ERROR batch {i//BATCH_SIZE}: {e}")
            for cit, answer in combined.items():
                kg_lookup[(task, cit)] = answer

driver.close()

# ── Map answers back to all rows ──────────────────────────────────────────────
def get_answer(row):
    task = row["task"]
    if task == "citation_retrieval":
        name = extract_case_name(row.get("query", ""))
        return kg_lookup.get((task, name))
    else:
        cit = str(row.get("citation", "") or "").strip()
        return kg_lookup.get((task, cit))

print("Mapping answers to rows…")
df["kg_answer"] = df.apply(get_answer, axis=1)

# ── Save ──────────────────────────────────────────────────────────────────────
df.to_csv(OUTPUT_PATH, index=False)
print(f"Saved: {OUTPUT_PATH}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n=== KG answer rate by task ===")
for task, group in df.groupby("task"):
    n        = len(group)
    answered = group["kg_answer"].apply(
        lambda x: x is not None and x != [] and x is not False
    ).sum()
    print(f"  {task:<22} {answered:>6,} / {n:>6,}  ({answered / n * 100:.1f}% answered)")
