"""
Step 3 — Query the KG for all 6 tasks and evaluate against dataset.

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
URI          = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
AUTH         = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))

RELEVANT_TASKS = {
    "case_existence", "court_id", "citation_retrieval",
    "majority_author", "cited_precedent", "year_overruled",
}

# ── Extract case name from citation_retrieval query string ────────────────────
# Query format: "What is the citation for the [level] case <Name>? Provide ..."
_NAME_RE = re.compile(r"for (?:the [\w ]+ case )?(.+?)\?", re.IGNORECASE)

def extract_case_name(query: str) -> str | None:
    m = _NAME_RE.search(str(query))
    return m.group(1).strip() if m else None


# ── Cypher query functions ────────────────────────────────────────────────────
def q_case_existence(session, citation: str):
    row = session.run(
        "MATCH (c:Case {citation: $c}) RETURN count(c) > 0 AS found",
        c=citation,
    ).single()
    return bool(row["found"]) if row else False


def q_court_id(session, citation: str):
    row = session.run(
        "MATCH (c:Case {citation: $c}) RETURN c.court_level AS court",
        c=citation,
    ).single()
    return row["court"] if row else None


def q_citation_retrieval(session, name: str):
    row = session.run(
        "MATCH (c:Case) WHERE toLower(c.name) CONTAINS toLower($name) "
        "RETURN c.citation AS citation LIMIT 1",
        name=name,
    ).single()
    return row["citation"] if row else None


def q_majority_author(session, citation: str):
    row = session.run(
        "MATCH (c:Case {citation: $c})-[:authored_by]->(j) RETURN j.name AS name",
        c=citation,
    ).single()
    return row["name"] if row else None


def q_cited_precedent(session, citation: str):
    rows = session.run(
        "MATCH (c:Case {citation: $c})-[:cites]->(p) RETURN p.citation AS citation",
        c=citation,
    )
    return [r["citation"] for r in rows]


def q_year_overruled(session, citation: str):
    row = session.run(
        "MATCH (c:Case {citation: $c})-[e:overruled_by]->() RETURN e.year_overruled AS yr",
        c=citation,
    ).single()
    return row["yr"] if row else None


QUERY_FN = {
    "case_existence"    : q_case_existence,
    "court_id"          : q_court_id,
    "citation_retrieval": q_citation_retrieval,
    "majority_author"   : q_majority_author,
    "cited_precedent"   : q_cited_precedent,
    "year_overruled"    : q_year_overruled,
}

# ── Load dataset ──────────────────────────────────────────────────────────────
df = pd.read_csv(DATASET_PATH, low_memory=False)
df = df[df["task"].isin(RELEVANT_TASKS)].copy()
print(f"Rows to process: {len(df):,}")

# ── Run queries ───────────────────────────────────────────────────────────────
driver = GraphDatabase.driver(URI, auth=AUTH)
kg_answers = []

with driver.session() as session:
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Querying KG", unit="row"):
        task     = row["task"]
        citation = str(row.get("citation", "") or "").strip()
        fn       = QUERY_FN[task]

        try:
            if task == "citation_retrieval":
                name = extract_case_name(row.get("query", ""))
                answer = fn(session, name) if name else None
            else:
                answer = fn(session, citation)
        except Exception as e:
            answer = f"ERROR: {e}"

        kg_answers.append(answer)

driver.close()

df["kg_answer"] = kg_answers

# ── Save ──────────────────────────────────────────────────────────────────────
df.to_csv(OUTPUT_PATH, index=False)
print(f"Saved: {OUTPUT_PATH}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n=== KG answer rate by task ===")
for task, group in df.groupby("task"):
    n       = len(group)
    answered = group["kg_answer"].apply(
        lambda x: x is not None and x != [] and x is not False
    ).sum()
    print(f"  {task:<22} {answered:>5,} / {n:>5,}  ({answered / n * 100:.1f}% answered)")
