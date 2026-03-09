"""
Step 4 — Evaluate KG answers against ground truth and LLM baseline.

Input : kg_results.csv  (output of query_kg.py)
Output: results/evaluation_results.csv
        console: accuracy table per task

Comparison logic per task
─────────────────────────
case_existence    : KG True  == correct (all dataset cases exist)
court_id          : normalised court slug matches expected answer
citation_retrieval: normalised citation string match
majority_author   : last-name overlap (case-insensitive)
cited_precedent   : example citation contained in KG list
year_overruled    : integer year match

LLM baseline      : hallucination == False  (dataset column)
"""
import ast
import os
import re

import pandas as pd

KG_RESULTS_PATH = "kg_results.csv"
OUTPUT_PATH     = "results/evaluation_results.csv"

os.makedirs("results", exist_ok=True)

# ── Court name → expected answer mapping ──────────────────────────────────────
# Neo4j stores full court names from CourtListener (e.g. "Court of Appeals for
# the Ninth Circuit"). The dataset expected answers are:
#   SCOTUS → "Supreme Court"
#   COA    → circuit number string "1"–"13"  (DC=12, Federal=13)
#   USDC   → full district court name string

# COA: ordinal word → circuit number
_COA_ORDINAL = {
    "first": "1", "second": "2", "third": "3", "fourth": "4",
    "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8",
    "ninth": "9", "tenth": "10", "eleventh": "11",
    "d.c.": "12", "federal": "13",
}

# USDC: district prefix abbreviation → full word
_DISTRICT_PREFIX = {
    "n.d.": "northern", "nd": "northern",
    "s.d.": "southern", "sd": "southern",
    "e.d.": "eastern",  "ed": "eastern",
    "w.d.": "western",  "wd": "western",
    "m.d.": "middle",   "md": "middle",
    "c.d.": "central",  "cd": "central",
    "d.":   "",         "d":  "",
}


def norm(s) -> str:
    """Lowercase, strip whitespace."""
    return str(s).strip().lower() if s is not None else ""


def norm_citation(s) -> str:
    """Normalise citation: lowercase, strip year suffix and trailing periods."""
    s = norm(s)
    s = re.sub(r"\s*\(\d{4}\)\s*$", "", s)
    return s.rstrip(".")


def match_court_id(kg_answer, correct_answer) -> bool:
    if kg_answer is None:
        return False
    kg  = norm(kg_answer)
    ans = norm(correct_answer)

    # SCOTUS: "supreme court of the united states" → "supreme court"
    if "supreme court" in kg:
        return "supreme court" in ans or "scotus" in ans

    # COA: "court of appeals for the X circuit" → circuit number
    if "court of appeals" in kg:
        for word, num in _COA_ORDINAL.items():
            if word in kg:
                return ans == num
        return False

    # USDC: "District Court, [prefix]. [State]" → full district court name
    # Extract district prefix and state/location from KG answer
    if "district court" in kg:
        # Special case: "district of columbia"
        if "district of columbia" in kg or ", ddc" in kg:
            return "district of columbia" in ans

        # Parse "District Court, N.D. California" or "District Court, S.D.N.Y."
        parts = kg.split(",", 1)
        if len(parts) > 1:
            loc = parts[1].strip()  # e.g. "n.d. california" or "s.d.n.y."
            # Remove district prefix tokens to get state name
            state = loc
            for abbr in sorted(_DISTRICT_PREFIX, key=len, reverse=True):
                if state.startswith(abbr):
                    state = state[len(abbr):].strip()
                    break
            # state might be "new york" or "n.y." — check if it appears in ans
            state = state.rstrip(".")
            if state and len(state) > 2 and state in ans:
                return True
        # Fallback: any substantial token in kg appears in answer
        return any(t in ans for t in kg.split() if len(t) > 3)

    # Unknown court type — fuzzy fallback
    return any(t in ans for t in kg.split() if len(t) > 3)


def match_author(kg_answer, correct_answer) -> bool:
    if not kg_answer:
        return False
    kg   = norm(kg_answer)
    ans  = norm(correct_answer)
    if "per curiam" in ans or "per curiam" in kg:
        return "per curiam" in ans and "per curiam" in kg
    # Compare last names
    kg_last  = kg.split()[-1]  if kg  else ""
    ans_last = ans.split()[-1] if ans else ""
    if kg_last and len(kg_last) > 2 and kg_last in ans:
        return True
    if ans_last and len(ans_last) > 2 and ans_last in kg:
        return True
    return False


def match_cited_precedent(kg_answer, correct_answer) -> bool:
    """Check if correct_answer citation appears in the KG list."""
    if not kg_answer or kg_answer == [] or kg_answer == "[]":
        return False
    if isinstance(kg_answer, str):
        try:
            kg_answer = ast.literal_eval(kg_answer)
        except Exception:
            return False
    if not isinstance(kg_answer, list):
        return False
    ans_norm = norm_citation(correct_answer)
    return any(norm_citation(c) == ans_norm for c in kg_answer)


# ── Per-task comparison dispatch ──────────────────────────────────────────────
def kg_correct(task, kg_answer, correct_answer) -> bool:
    if task == "case_existence":
        return str(kg_answer).strip().lower() in ("true", "1", "yes")

    if task == "court_id":
        return match_court_id(kg_answer, correct_answer)

    if task == "citation_retrieval":
        return norm_citation(kg_answer) == norm_citation(correct_answer)

    if task == "majority_author":
        return match_author(kg_answer, correct_answer)

    if task == "cited_precedent":
        return match_cited_precedent(kg_answer, correct_answer)

    if task == "year_overruled":
        try:
            return int(str(kg_answer).strip()) == int(str(correct_answer).strip())
        except Exception:
            return False

    return False


# ── Load data ─────────────────────────────────────────────────────────────────
if not os.path.exists(KG_RESULTS_PATH):
    print(f"ERROR: {KG_RESULTS_PATH} not found — run query_kg.py first.")
    raise SystemExit(1)

df = pd.read_csv(KG_RESULTS_PATH, low_memory=False)
print(f"Loaded {len(df):,} rows from {KG_RESULTS_PATH}")

# LLM correct = hallucination == False
df["llm_correct"] = df["hallucination"].astype(str).str.lower().isin(("false", "0"))

# KG correct
df["kg_correct"] = df.apply(
    lambda r: kg_correct(r["task"], r.get("kg_answer"), r.get("example_correct_answer")),
    axis=1,
)

# ── Results per task ──────────────────────────────────────────────────────────
rows = []
TASKS = ["case_existence", "court_id", "citation_retrieval",
         "majority_author", "cited_precedent", "year_overruled"]

print(f"\n{'Task':<22} {'N':>6}  {'LLM acc':>8}  {'KG acc':>8}  {'Delta':>8}")
print("─" * 60)

for task in TASKS:
    g = df[df["task"] == task]
    if g.empty:
        continue
    n          = len(g)
    llm_acc    = g["llm_correct"].mean() * 100
    kg_acc     = g["kg_correct"].mean()  * 100
    delta      = kg_acc - llm_acc
    delta_str  = f"{delta:+.1f}%"
    print(f"{task:<22} {n:>6,}  {llm_acc:>7.1f}%  {kg_acc:>7.1f}%  {delta_str:>8}")
    rows.append({
        "task": task, "n": n,
        "llm_accuracy_pct": round(llm_acc, 2),
        "kg_accuracy_pct":  round(kg_acc,  2),
        "delta_pct":        round(delta,    2),
    })

print("─" * 60)
total_n       = len(df)
llm_total_acc = df["llm_correct"].mean() * 100
kg_total_acc  = df["kg_correct"].mean()  * 100
delta_total   = kg_total_acc - llm_total_acc
print(f"{'TOTAL':<22} {total_n:>6,}  {llm_total_acc:>7.1f}%  {kg_total_acc:>7.1f}%  {delta_total:+.1f}%")

# ── Save ──────────────────────────────────────────────────────────────────────
results_df = pd.DataFrame(rows)
results_df.to_csv(OUTPUT_PATH, index=False)
print(f"\nSaved: {OUTPUT_PATH}")

# Save full row-level results
df[["id", "task", "court_level", "llm", "citation",
    "example_correct_answer", "llm_output", "hallucination",
    "kg_answer", "llm_correct", "kg_correct"]].to_csv(
    "results/evaluation_detail.csv", index=False
)
print(f"Saved: results/evaluation_detail.csv")
