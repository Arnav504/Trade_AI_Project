"""
ASAN Macro – Evaluation script for the project report.
Runs at least 10 real test cases through the application and records metrics.
Usage: from project root, run:  python evaluation/run_evaluation.py
       or:  python evaluation/run_evaluation.py --dry-run   (no LLM calls, just structure)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_path), override=True)
    except Exception:
        pass

from config import DB_PATH
from database import ensure_db


# At least 10 diverse test queries (in-domain and edge cases)
TEST_QUERIES = [
    None,  # full analysis
    "BRICS",
    "US-China electronics",
    "Vietnam and Mexico manufacturing",
    "minerals and energy",
    "South-South trade",
    "decoupling",
    "India Russia",
    "textiles",
    "Electronics",
    "regional trade blocs",
    "supply chain diversification",
]


def has_section(text: str, name: str) -> bool:
    """Check if report contains a section (case-insensitive, flexible)."""
    t = text.lower()
    if "summary" in name.lower():
        return "summary" in t or (t.startswith("the ") and len(t) > 100)
    if "key region" in name.lower() or "key sector" in name.lower():
        return "key region" in t or "key sector" in t or "regions/sectors" in t or "key regions" in t
    if "so what" in name.lower():
        return "so what" in t or "implication" in t
    if "what's next" in name.lower() or "whats next" in name.lower():
        return "what's next" in t or "whats next" in t or "what next" in t
    return False


def extract_metrics(report: str, runtime_sec: float, query) -> dict:
    """Compute metrics for one run."""
    report = (report or "").strip()
    return {
        "query": str(query) if query else "(full analysis)",
        "runtime_sec": round(runtime_sec, 2),
        "char_count": len(report),
        "word_count": len(report.split()) if report else 0,
        "has_summary": has_section(report, "summary"),
        "has_key_regions_sectors": has_section(report, "key regions/sectors"),
        "has_so_what": has_section(report, "so what"),
        "has_whats_next": has_section(report, "what's next"),
        "section_count": sum([
            has_section(report, "summary"),
            has_section(report, "key regions/sectors"),
            has_section(report, "so what"),
            has_section(report, "what's next"),
        ]),
        "non_empty": len(report) > 100,
    }


def run_one(query, dry_run: bool):
    """Run agent once and return (report, runtime_sec)."""
    if dry_run:
        return f"[DRY RUN] Would run with query={query!r}", 0.0
    from agent import run_agent
    start = time.perf_counter()
    report = run_agent(user_query=query)
    elapsed = time.perf_counter() - start
    return report, elapsed


def main():
    ap = argparse.ArgumentParser(description="Run evaluation test cases for ASAN Macro.")
    ap.add_argument("--dry-run", action="store_true", help="Do not call LLM; only validate script and metrics.")
    ap.add_argument("--output", "-o", type=str, default=None, help="Write results JSON here (default: evaluation/evaluation_results.json).")
    ap.add_argument("--max", type=int, default=None, help="Max number of test cases (default: all).")
    args = ap.parse_args()

    ensure_db()
    out_path = Path(args.output) if args.output else PROJECT_ROOT / "evaluation" / "evaluation_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    queries = TEST_QUERIES[: args.max] if args.max else TEST_QUERIES
    results = []
    for i, q in enumerate(queries):
        print(f"  [{i+1}/{len(queries)}] query={q!r} ...", flush=True)
        report, runtime = run_one(q, args.dry_run)
        metrics = extract_metrics(report, runtime, q)
        metrics["report_preview"] = (report[:500] + "...") if report and len(report) > 500 else (report or "")
        results.append(metrics)

    # Aggregate metrics
    n = len(results)
    agg = {
        "n_runs": n,
        "total_runtime_sec": round(sum(r["runtime_sec"] for r in results), 2),
        "avg_runtime_sec": round(sum(r["runtime_sec"] for r in results) / n, 2) if n else 0,
        "avg_char_count": round(sum(r["char_count"] for r in results) / n, 0) if n else 0,
        "avg_word_count": round(sum(r["word_count"] for r in results) / n, 0) if n else 0,
        "pct_has_summary": round(100 * sum(r["has_summary"] for r in results) / n, 1) if n else 0,
        "pct_has_key_regions_sectors": round(100 * sum(r["has_key_regions_sectors"] for r in results) / n, 1) if n else 0,
        "pct_has_so_what": round(100 * sum(r["has_so_what"] for r in results) / n, 1) if n else 0,
        "pct_has_whats_next": round(100 * sum(r["has_whats_next"] for r in results) / n, 1) if n else 0,
        "pct_all_four_sections": round(100 * sum(1 for r in results if r["section_count"] >= 4) / n, 1) if n else 0,
        "pct_non_empty": round(100 * sum(r["non_empty"] for r in results) / n, 1) if n else 0,
    }

    payload = {
        "dry_run": args.dry_run,
        "aggregate_metrics": agg,
        "per_run": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n--- Aggregate metrics ---")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    print(f"\nResults written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
