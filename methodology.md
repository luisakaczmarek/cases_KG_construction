# Methodology

## Overview

This project builds a Neo4j citation knowledge graph over US federal court cases and evaluates whether structured KG traversal reduces hallucination rates in legal QA tasks, benchmarked against Dahl et al. (2024).

---

## Part 1 — Data Collection & Graph Construction

### 1.1 Dataset

Source: [reglab/legal_hallucinations](https://huggingface.co/datasets/reglab/legal_hallucinations) — Dahl et al. (2024).

Filtered to 6 factual tasks:
- `case_existence` — does this case exist?
- `court_id` — which court decided it?
- `citation_retrieval` — what is the citation for a named case?
- `majority_author` — who wrote the majority opinion?
- `cited_precedent` — what cases does this case cite?
- `year_overruled` — in what year was this case overruled?

### 1.2 Scraping (CourtListener API)

Script: `scrape_cases.py`

For each unique citation in the filtered dataset, the CourtListener v4 REST API is queried to retrieve:
- `cluster_id` — unique opinion cluster identifier
- `case_name` — full case name
- `date_filed` — filing date (used to extract year)
- `court` — court identifier (e.g. `scotus`, `ca9`, `dcd`)
- `plain_text` — opinion text
- `author_id` / `judge_name` — majority author

Rate limit: 4,800 requests/day. Scripts resume automatically from where they left off.

Citation edges (which cases cite which) are scraped separately in `scrape_citation_edges.py`, producing `citation_edges.json`: `cluster_id → [cited_opinion_ids]`.

### 1.3 Citation Normalization

Script: `normalize_citations.py`

Uses [eyecite](https://github.com/freelawproject/eyecite) to canonicalize citation strings (e.g. strip year suffixes, trailing periods, correct reporter abbreviations). Produces `citation_lookup.json`: `normalized_citation → cluster_id`.

### 1.4 Neo4j Graph Schema

Scripts: `load_neo4j.py` (nodes), future scripts for edges.

**Nodes:**

| Label  | Properties |
|--------|-----------|
| `Case` | `citation` (string, unique), `name`, `year` (int), `court_level`, `court_slug`, `cluster_id` (int) |
| `Judge` | `name`, `courtlistener_id` (int) |

**Edges (current):**

| Relationship | From → To | Properties |
|---|---|---|
| `authored_by` | `Case → Judge` | — |

**Edges (planned):**

| Relationship | From → To | Properties |
|---|---|---|
| `cites` | `Case → Case` | — |
| `overruled_by` | `Case → Case` | `year_overruled` (int) |

**Indexes:** `Case.citation`, `Case.name`

### 1.5 Coverage

As of 2026-03-07:

| Court | Found | Total | Coverage |
|-------|-------|-------|----------|
| SCOTUS | 4,708 | 4,711 | 99.9% |
| COA | 4,528 | 4,528 | 100.0% |
| USDC | 4,495 | 4,497 | 100.0% |
| **Total** | **13,731** | **13,736** | **100.0%** |

5 missing cases are genuinely absent from CourtListener. Coverage is not a binding constraint — all court levels are included.

---

## Part 2 — KG Query Evaluation (planned)

Script: `query_kg.py`

For each row in the dataset, the KG is queried using the appropriate Cypher pattern:

| Task | Cypher |
|------|--------|
| `case_existence` | `MATCH (c:Case {citation: $c}) RETURN count(c) > 0` |
| `court_id` | `MATCH (c:Case {citation: $c}) RETURN c.court_level` |
| `citation_retrieval` | `MATCH (c:Case) WHERE toLower(c.name) CONTAINS toLower($name) RETURN c.citation LIMIT 1` |
| `majority_author` | `MATCH (c:Case {citation: $c})-[:authored_by]->(j) RETURN j.name` |
| `cited_precedent` | `MATCH (c:Case {citation: $c})-[:cites]->(p) RETURN p.citation` |
| `year_overruled` | `MATCH (c:Case {citation: $c})-[e:overruled_by]->() RETURN e.year_overruled` |

KG answers are compared against `example_correct_answer` and LLM outputs from the dataset to measure hallucination reduction.

---

## References

- Dahl et al. (2024). Large Legal Fictions. *Journal of Legal Analysis*, 16(1). [doi:10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)
- Magesh et al. (2025). Hallucination-Free? *Journal of Empirical Legal Studies*.
- [CourtListener API](https://www.courtlistener.com/help/api/)
- [eyecite](https://github.com/freelawproject/eyecite)
