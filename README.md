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
├── scraped_cases.json         # scraping progress cache (gitignored)
├── citation_edges.json        # cluster_id -> [cited_opinion_ids] (gitignored)
├── citation_lookup.json       # normalized_citation -> cluster_id (gitignored)
├── legal_hallucinations/      # dataset folder (gitignored)
├── requirements.txt
├── .env                       # API token (gitignored)
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
```
Get a token at [courtlistener.com](https://www.courtlistener.com/sign-in/).

## Pipeline

Run scripts in order:

```bash
# 1. Explore the dataset
python explore_dataset.py

# 2. Scrape case metadata from CourtListener (resumes automatically if interrupted)
python scrape_cases.py --yes

# 3. Scrape citation edges for each case
python scrape_citation_edges.py

# 4. Normalize citation strings with eyecite
python normalize_citations.py

# 5. Enrich scraped cases with cited opinion IDs
python enrich_citations.py
```

All scraping scripts respect a daily API limit of 4800 requests and resume from where they left off.

## Relevant tasks from dataset

The scraper filters to these task types: `case_existence`, `citation_retrieval`, `cited_precedent`, `court_id`, `majority_author`, `year_overruled`.

## References

- Dahl et al. (2024). Large Legal Fictions. *Journal of Legal Analysis*, 16(1). [doi:10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)
- Magesh et al. (2025). Hallucination-Free? *Journal of Empirical Legal Studies*.
- [CourtListener API](https://www.courtlistener.com/help/api/)
- [eyecite](https://github.com/freelawproject/eyecite) — legal citation parser
