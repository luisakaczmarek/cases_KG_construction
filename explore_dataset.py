"""
Step 1.2 — Dataset Exploration
Clean inspection of legal_hallucinations/dataset.csv
"""
import pandas as pd

DATASET_PATH = "legal_hallucinations/dataset.csv"

df = pd.read_csv(DATASET_PATH, low_memory=False)

print("=" * 60)
print("COLUMNS")
print("=" * 60)
print(df.columns.tolist())
print(f"\nShape: {df.shape[0]:,} rows x {df.shape[1]} columns")

print("\n" + "=" * 60)
print("TASK NAMES & COUNTS")
print("=" * 60)
print(df["task"].value_counts().to_string())

print("\n" + "=" * 60)
print("COURT LEVEL CODES")
print("=" * 60)
print(df["court_level"].value_counts().to_string())

print("\n" + "=" * 60)
print("COURT SLUGS (top 20)")
print("=" * 60)
print(df["court_slug"].value_counts().head(20).to_string())

print("\n" + "=" * 60)
print("CITATION FORMAT SAMPLES (task == citation_retrieval)")
print("=" * 60)
cit_rows = df[df["task"] == "citation_retrieval"][["citation", "query", "llm_output", "example_correct_answer"]].head(10)
print(cit_rows.to_string())

print("\n" + "=" * 60)
print("CITATION STRING FORMATS (unique sample)")
print("=" * 60)
sample_cits = df["citation"].dropna().loc[df["citation"] != "citation"].unique()[:20]
for c in sample_cits:
    print(" ", c)

print("\n" + "=" * 60)
print("LLM COLUMNS")
print("=" * 60)
print(df["llm"].value_counts().to_string())

print("\n" + "=" * 60)
print("HALLUCINATION FLAG")
print("=" * 60)
print(df["hallucination"].value_counts().to_string())
true_count = (df["hallucination"] == True) | (df["hallucination"].astype(str).str.lower() == "true")
print(f"\nHallucination rate: {true_count.sum() / len(df) * 100:.1f}%")

print("\n" + "=" * 60)
print("CORRECTNESS SCORE")
print("=" * 60)
print(df["correctness_score"].describe())

print("\n" + "=" * 60)
print("SAMPLE ROWS (task == citation_retrieval)")
print("=" * 60)
print(df[df["task"] == "citation_retrieval"].head(10).to_string())
