[README (4).md](https://github.com/user-attachments/files/25740928/README.4.md)
# Legal Hallucinations — KG Grounding

Bachelor thesis project. Builds a Neo4j citation graph over US federal cases to reduce LLM hallucination rates on factual legal QA tasks, benchmarked against Dahl et al. (2024).

## Research question

Can structured knowledge graph traversal reduce hallucination rates in legal QA compared to LLM-only baselines, across factual lookup tasks?

## Dataset

[reglab/legal_hallucinations](https://huggingface.co/datasets/reglab/legal_hallucinations) — Dahl et al., *Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models*, Journal of Legal Analysis (2024).

Place the dataset at `legal_hallucinations/dataset.csv` before running.

## Project structure

```
Graph_database/
├── scrape_cases.py        # scrapes CourtListener API for dataset cases
├── scraped_cases.json     # scraping progress cache (gitignored)
├── legal_hallucinations/  # dataset folder (gitignored)
├── requirements.txt
├── .env                   # API token (gitignored)
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

## Usage

```bash
# Run scraper (resumes automatically if interrupted)
python scrape_cases.py --yes

# Check progress
python -c "import json; d=json.load(open('scraped_cases.json')); print(f'Scraped: {len(d)}')"
```

## References

- Dahl et al. (2024). Large Legal Fictions. *Journal of Legal Analysis*, 16(1). [doi:10.1093/jla/laae003](https://doi.org/10.1093/jla/laae003)
- Magesh et al. (2025). Hallucination-Free? *Journal of Empirical Legal Studies*.
- [CourtListener API](https://www.courtlistener.com/help/api/)
