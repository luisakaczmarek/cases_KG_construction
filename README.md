# Legal Hallucinations — KG Grounding

Bachelor thesis project. Builds a Neo4j citation graph over US federal cases to reduce LLM hallucination rates on factual legal QA tasks, benchmarked against Dahl et al. (2024).

## Research question

Can structured knowledge graph traversal reduce hallucination rates in legal QA compared to LLM-only baselines, across factual lookup tasks?

## Dataset

[reglab/legal_hallucinations](https://huggingface.co/datasets/reglab/legal_hallucinations) — Dahl et al., *Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models*, Journal of Legal Analysis (2024).

Place the dataset at `legal_hallucinations/dataset.csv` before running. The folder is gitignored due to file size.

## Project structure

```
Graph_database/
├── explore_dataset.py         # Step 1.2 — inspect dataset columns, tasks, hallucination rates
├── scrape_cases.py            # Step 1.1 — scrape CourtListener API for dataset cases
├── scrape_citation_edges.py   # Step 1.3 — scrape outgoing citation edges per case
├── normalize_citations.py     # Step 1.4 — normalize citation strings with eyecite
├── enrich_citations.py        # enrich scraped cases with cited opinion IDs
├── load_neo4j.py              # Step 2.1 — load Case + Judge nodes into Neo4j
├── coverage_check.py          # Step 2.2 — verify citation coverage against Neo4j
├── query_kg.py                # Step 3   — run KG queries for all 6 tasks
├── results/
│   └── coverage_summary.md   # coverage results as of 2026-03-07
├── scraped_cases.json         # scraping progress cache (gitignored)
├── citation_edges.json        # cluster_id -> [cited_opinion_ids] (gitignored)
├── citation_lookup.json       # normalized_citation -> cluster_id (gitignored)
├── legal_hallucinations/      # dataset folder (gitignored)
├── methodology.md             # full methodology notes
├── requirements.txt
├── .env                       # API keys (gitignored)
└── .gitignore
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:
```
COURTLISTENER_TOKEN=your_token_here
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
```

Get a CourtListener token at [courtlistener.com](https://www.courtlistener.com/sign-in/).

## Pipeline

```bash
# 1. Explore the dataset
python3 explore_dataset.py

# 2. Scrape case metadata from CourtListener (resumes if interrupted)
python3 scrape_cases.py --yes

# 3. Scrape citation edges per case
python3 scrape_citation_edges.py

# 4. Normalize citation strings with eyecite
python3 normalize_citations.py

# 5. Load Case + Judge nodes into Neo4j
python3 load_neo4j.py

# 6. Check citation coverage
python3 coverage_check.py

# 7. Run KG queries for all 6 tasks
python3 query_kg.py
```

All scraping scripts respect a daily API limit of 4,800 requests and resume from where they left off.

## Coverage (as of 2026-03-07)

| Court | Found | Total | Coverage |
|-------|-------|-------|----------|
| SCOTUS | 4,708 | 4,711 | 99.9% |
| COA | 4,528 | 4,528 | 100.0% |
| USDC | 4,495 | 4,497 | 100.0% |
| **Total** | **13,731** | **13,736** | **100.0%** |

See `methodology.md` for full methodology and graph schema.

## References

- Dahl et al. (2024). Large Legal Fictions. *Journal of Legal Analysis*, 16(1). [doi:10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)
- Magesh et al. (2025). Hallucination-Free? *Journal of Empirical Legal Studies*.
- [CourtListener API](https://www.courtlistener.com/help/api/)
- [eyecite](https://github.com/freelawproject/eyecite) — legal citation parser
