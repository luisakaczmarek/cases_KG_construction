# Methodology: KG Construction for Legal Hallucination Benchmarking

This document describes the end-to-end pipeline for constructing the Neo4j citation knowledge graph used to evaluate LLM hallucination rates on the [Dahl et al. (2024)](https://doi.org/10.1093/jla/laae003) legal QA benchmark.

---

## Overview

The pipeline turns a flat CSV of benchmark questions into a queryable Neo4j citation graph. Each step is independently resumable and produces a JSON artifact that feeds the next step.

```
dataset.csv
    │
    ▼
explore_dataset.py       # inspect structure, verify citation column
    │
    ▼
scrape_cases.py          # CourtListener API → scraped_cases.json
    │
    ▼
scrape_citation_edges.py # CourtListener API → citation_edges.json
    │
    ▼
normalize_citations.py   # eyecite → citation_lookup.json
    │
    ▼
enrich_citations.py      # merge edges into scraped_cases.json
    │
    ▼
load_neo4j.py            # → populated Neo4j graph (Case + Judge nodes)
    │
    ▼
query_kg.py              # → kg_results.csv (KG answers for all 6 tasks)
```

---

## Step 1 — Dataset Inspection (`explore_dataset.py`)

Reads `legal_hallucinations/dataset.csv` and prints:

- Column names and data types
- Task distribution across the 14 benchmark tasks
- Court level codes (`scotus`, `ca1`–`ca11`, `usdc`)
- Example citation strings
- Hallucination flag and correctness score distributions

**Relevant tasks filtered downstream:**

| Task name | Description |
|---|---|
| `case_existence` | Is this a real case? |
| `court_id` | What court decided this case? |
| `citation_retrieval` | What is the citation for this case? |
| `majority_author` | Who wrote the majority opinion? |
| `cited_precedent` | What case does this case cite? |
| `year_overruled` | What year was this case overruled? |

These six tasks are the only ones addressable by deterministic KG lookup (Part 1). High-complexity tasks (factual background, central holding) require KG-RAG and are out of scope for graph construction.

---

## Step 2 — Case Scraping (`scrape_cases.py`)

### API

All requests use **CourtListener REST API v4**. API v3 returns `403 Forbidden` for free-tier accounts.

Base URL: `https://www.courtlistener.com/api/rest/v4`

### Three-request chain per citation

For each unique citation string in the filtered dataset:

**Request 1 — Case search**
```
GET /search/?q="{citation}"&type=o
```
Returns: `caseName`, `cluster_id`, `court`, `dateFiled`. The `cluster_id` is the stable CourtListener identifier used as a foreign key throughout the pipeline.

**Request 2 — Opinion text and author**
```
GET /opinions/?cluster={cluster_id}&type=010combined
```
Returns: `author_id`, `plain_text`. The combined opinion type (`010combined`) is preferred; `plain_text` is used downstream for authority task scoring via eyecite. If `plain_text` is empty, falls back to `html`.

**Request 3 — Judge name**
```
GET /people/{author_id}/
```
Returns: `name_full` (or `name_first` + `name_last`). Results are cached in memory so each judge is fetched at most once per run.

### Rate limiting and resumption

- **Daily limit:** 4,800 requests (`DAILY_LIMIT`). The script counts all requests (search + opinions + people) and exits cleanly when the limit is reached, saving progress first.
- **Retry logic:** Re-run with `--retry-errors` to retry any citations that previously returned transient HTTP errors (e.g. `502 Bad Gateway`).
- **Resume:** `scraped_cases.json` is written after every citation. Restart the script at any time; already-processed citations are skipped.
- **Sleep:** 0.5 s between requests to avoid rate pressure.

### Output format: `scraped_cases.json`

```json
{
  "410 U.S. 113": {
    "status": "found",
    "cluster_id": 108713,
    "case_name": "Roe v. Wade",
    "court": "scotus",
    "date_filed": "1973-01-22",
    "plain_text": "...",
    "author_id": 1740,
    "judge_name": "Harry A. Blackmun"
  },
  "999 F.3d 999": {
    "status": "not_found"
  }
}
```

Possible `status` values: `found`, `not_found`, `error`.

### Scraping results

| Run | Processed | Cumulative found | Note |
|---|---|---|---|
| 1 | 2,389 | 2,382 (99.7%) | Hit daily limit |
| 2–6 | ~2,200/run | up to 13,441 | Hit daily limit each run |
| 7 | 211 | 13,652 (99.4%) | Base scrape complete |
| Retry | 79 errors | 13,731 (100.0%) | All 502s resolved |

Final: **13,731 found**, 5 genuinely absent from CourtListener, 0 errors.

---

## Step 3 — Citation Edge Scraping (`scrape_citation_edges.py`)

For each case in `scraped_cases.json` with a `cluster_id`, fetches the `opinions_cited` field from the opinions endpoint:

```
GET /opinions/?cluster={cluster_id}
```

`opinions_cited` is a pre-extracted list of opinion IDs provided by CourtListener — no eyecite parsing is needed here. This produces a directed graph edge list used for `CITES` relationships in Neo4j.

> **Important distinction:** `citation_edges.json` is built from CourtListener's `opinions_cited` field, not from running eyecite on `plain_text`. The two are kept separate: `citation_edges.json` powers Neo4j `CITES` edges; eyecite on `plain_text` powers authority task scoring (Step 2.2 of the evaluation pipeline).

**Output: `citation_edges.json`**

```json
{
  "108713": [102345, 99841, 114002],
  "204501": [108713]
}
```

Keys are `cluster_id` strings; values are lists of cited opinion IDs. Deduplicated by `cluster_id` — multiple citation strings that resolve to the same cluster are processed once.

Scope: **13,625 unique cluster IDs** across multiple daily sessions (~11,300 processed as of 2026-03-08, final run pending).

---

## Step 4 — Citation Normalization (`normalize_citations.py`)

Raw citation strings in the dataset contain formatting inconsistencies (year suffixes, trailing periods, spacing variations). This step builds a lookup table: `normalized_citation_string → cluster_id`.

### Normalization logic

1. Strip year suffix: `410 U.S. 113 (1973)` → `410 U.S. 113`
2. Strip trailing periods from reporter abbreviations
3. Parse with `eyecite.get_citations()`
4. Filter to `FullCaseCitation` instances only (excludes short-form, id., supra)
5. Canonicalize via `FullCaseCitation.corrected_citation()`
6. **Fallback:** if eyecite cannot parse, store by cleaned raw string

Per curiam opinions have no `author_id`; these are stored with `judge_name = "Per Curiam"`.

**Output: `citation_lookup.json`**

```json
{
  "410 U.S. 113": 108713,
  "347 U.S. 483": 102731
}
```

Results: **13,731 entries**, 0 parse failures requiring the raw-string fallback.

---

## Step 5 — Enrichment (`enrich_citations.py`)

Merges `citation_edges.json` into `scraped_cases.json`, adding a `cited_opinion_ids` field to each case record. This produces a single enriched JSON file ready for Neo4j loading.

---

## Step 6 — Neo4j Graph Loading (`load_neo4j.py`)

### Node types

| Label | Properties |
|---|---|
| `Case` | `citation`, `name`, `year`, `court_level`, `court_slug`, `cluster_id` |
| `Judge` | `name`, `courtlistener_id` |

### Edge types

| Relationship | From → To | Properties |
|---|---|---|
| `authored_by` | `Case` → `Judge` | — |
| `cites` | `Case` → `Case` | — *(pending: load_cites.py)* |
| `overruled_by` | `Case` → `Case` | `year_overruled` *(pending)* |

### Load results (2026-03-07)

| Metric | Count |
|---|---|
| Case nodes | 13,731 |
| Judge nodes | 1,279 |
| `authored_by` edges | 4,338 |
| Errors | 0 |

### Design decisions

- **No separate `Court` node.** Court is stored as `court_level` and `court_slug` properties directly on `Case`. No Part 1 task requires traversal to a court node, so the extra join would add complexity with no benefit.
- **`court_slug`** stores the raw CourtListener identifier (e.g. `scotus`, `ca9`, `dcd`) for precise filtering.
- **`cluster_id`** is stored on `Case` for debugging and CourtListener traceability.
- **MERGE on `citation`** prevents duplicates when multiple dataset rows reference the same case.

### Indexes

```cypher
CREATE INDEX case_citation IF NOT EXISTS FOR (c:Case) ON (c.citation)
CREATE INDEX case_name     IF NOT EXISTS FOR (c:Case) ON (c.name)
```

---

## Step 7 — Coverage Check (`coverage_check.py`)

Verifies that dataset citations are present as Case nodes in Neo4j.

### Results (2026-03-07)

| Court | Found | Total | Coverage |
|-------|-------|-------|----------|
| SCOTUS | 4,708 | 4,711 | 99.9% |
| COA | 4,528 | 4,528 | 100.0% |
| USDC | 4,495 | 4,497 | 100.0% |
| **Total** | **13,731** | **13,736** | **100.0%** |

5 missing cases are genuinely absent from CourtListener. Coverage is not a binding constraint — all court levels are included.

---

## Step 8 — KG Query Evaluation (`query_kg.py`)

For each row in the dataset, the KG is queried using the appropriate Cypher pattern:

| Task | Cypher |
|------|--------|
| `case_existence` | `MATCH (c:Case {citation: $c}) RETURN count(c) > 0` |
| `court_id` | `MATCH (c:Case {citation: $c}) RETURN c.court_level` |
| `citation_retrieval` | `MATCH (c:Case) WHERE toLower(c.name) CONTAINS toLower($name) RETURN c.citation LIMIT 1` |
| `majority_author` | `MATCH (c:Case {citation: $c})-[:authored_by]->(j) RETURN j.name` |
| `cited_precedent` | `MATCH (c:Case {citation: $c})-[:cites]->(p) RETURN p.citation` |
| `year_overruled` | `MATCH (c:Case {citation: $c})-[e:overruled_by]->() RETURN e.year_overruled` |

KG answers are compared against `example_correct_answer` and LLM outputs from the dataset to measure hallucination reduction. Output saved to `kg_results.csv`.

---

## Scope and Limitations

**KG scope:** The graph contains only the ~13,731 cases appearing in the Dahl et al. benchmark. Multi-hop traversal (e.g. "cases cited by cases that cite X") is not required by any Part 1 task and is not supported.

**Authority scoring vs. CITES edges:** `CITES` edges in Neo4j are built from CourtListener's pre-extracted `opinions_cited` field. Authority task scoring runs eyecite directly on `plain_text` to extract the citation set. These two approaches may diverge slightly; the divergence is noted as a limitation.

**Non-majority content:** `plain_text` from CourtListener may include dissents, concurrences, and syllabus text alongside the majority opinion. Dahl et al. scored against majority opinion text only. This may produce a marginally different valid citation set for the authority task.

**USDC coverage:** District court cases are substantially underrepresented in CourtListener relative to SCOTUS and COA. All results are stratified by court level; low USDC coverage is reported as a limitation rather than treated as a scoring failure.

**Partial overrulings:** Cases with ambiguous or partial overruling treatment are excluded from the `OVERRULED_BY` edge; only unambiguous full overrulings are modelled.

---

## References

- Dahl et al. (2024). Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models. *Journal of Legal Analysis*, 16(1). [doi:10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)
- Magesh et al. (2025). Hallucination-Free? *Journal of Empirical Legal Studies*.
- [CourtListener API documentation](https://www.courtlistener.com/help/api/)
- [eyecite — legal citation parser](https://github.com/freelawproject/eyecite)
- [reglab/legal_hallucinations dataset](https://huggingface.co/datasets/reglab/legal_hallucinations)
