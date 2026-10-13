"""
ASAN Macro - Main entry point.
Takes raw input (optional CSV path and/or focus query) and outputs a trade sentiment report
without additional manual intervention (input/output completeness).
"""
import argparse
import re
import sys
from html import escape
from pathlib import Path

# Load .env first so OPENAI_API_KEY is set before the agent runs
_script_dir = Path(__file__).resolve().parent
_env_path = _script_dir / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_path), override=True)
    except Exception:
        pass

from config import PROJECT_ROOT, get_db_path
from database import ensure_db, clear_trade_flows
from agent import last_brief, run_agent
from report_contract import DISCLAIMER


def main():
    parser = argparse.ArgumentParser(
        description="ASAN Macro: Analyze trade data and produce a sentiment/synthesis report."
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default=None,
        help="Optional focus query (e.g. 'BRICS', 'US-China electronics'). If omitted, full analysis.",
    )
    parser.add_argument(
        "--data",
        "-d",
        type=str,
        default=None,
        help="Optional path to CSV (columns: year, reporter_region, partner_region, sector, flow_type, value_usd). Loaded into DB before analysis.",
    )
    parser.add_argument(
        "--data-url",
        type=str,
        default=None,
        help="Optional URL of a CSV to fetch and load into the DB (dynamic data source).",
    )
    parser.add_argument(
        "--replace-data",
        action="store_true",
        help="Clear existing trade_flows before loading --data/--data-url (use only dynamic data).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path for the report. Default: report_<timestamp>.txt in project root.",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["text", "html", "linkedin", "json"],
        default="text",
        help="Output format: text (default), html, linkedin (report + one-liner), or json (structured for dashboards).",
    )
    args = parser.parse_args()

    # Ensure database exists
    ensure_db()

    # Optional: clear hardcoded seed data so only dynamic data is used
    if getattr(args, "replace_data", False):
        clear_trade_flows()
        print("Cleared trade_flows (using dynamic data only).", file=sys.stderr)

    # Dynamic data ingestion: local CSV, CSV URL
    try:
        from data_ingestion import load_csv_path, load_csv_url
        if args.data:
            data_path = Path(args.data)
            if data_path.exists():
                n = load_csv_path(data_path)
                print(f"Loaded {n} rows from CSV: {data_path}", file=sys.stderr)
            else:
                print(f"Warning: data file not found: {data_path}", file=sys.stderr)
        if getattr(args, "data_url", None):
            n = load_csv_url(args.data_url)
            print(f"Loaded {n} rows from URL: {args.data_url}", file=sys.stderr)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ImportError:
        if args.data:
            data_path = Path(args.data)
            if data_path.exists():
                _load_csv_into_db(data_path)
            else:
                print(f"Warning: data file not found: {data_path}", file=sys.stderr)

    # Run agent: DB + optional query -> report
    report = run_agent(user_query=args.query)

    out_path = args.output
    if not out_path:
        from datetime import datetime
        out_path = PROJECT_ROOT / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    else:
        out_path = Path(out_path)

    fmt = getattr(args, "format", "text")
    if fmt == "html":
        out_path = out_path.with_suffix(".html")
        out_path.write_text(_report_to_html(report), encoding="utf-8")
    elif fmt == "linkedin":
        out_path.write_text(report, encoding="utf-8")
        one_liner = _linkedin_one_liner(report)
        summary_path = out_path.parent / "LINKEDIN_SUMMARY.txt"
        summary_path.write_text(one_liner, encoding="utf-8")
        print("LinkedIn one-liner written to:", summary_path, file=sys.stderr)
    elif fmt == "json":
        out_path = out_path.with_suffix(".json")
        import json
        structured = _report_to_json(report)
        out_path.write_text(json.dumps(structured, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        out_path.write_text(report, encoding="utf-8")

    print("Report written to:", out_path)
    print("\n--- Report ---\n")
    print(report)
    if fmt == "linkedin":
        print("\n--- LinkedIn one-liner ---\n")
        print(_linkedin_one_liner(report))
    return 0


def _report_to_html(report: str) -> str:
    """Wrap report text in a minimal HTML page for sharing."""
    escaped = escape(report)
    body = "<br>\n".join(escaped.split("\n"))
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ASAN Macro – Trade Sentiment Report</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    h1 { font-size: 1.25rem; }
  </style>
</head>
<body>
  <h1>ASAN Macro – Trade Sentiment Report</h1>
  <div class="report">""" + body + """</div>
</body>
</html>"""


def _linkedin_one_liner(report: str, max_chars: int = 280) -> str:
    """Produce a short LinkedIn-ready summary (first meaningful sentences)."""
    kept = []
    for line in (report or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == DISCLAIMER:
            continue
        kept.append(stripped)
    report = " ".join(kept).strip()
    if not report:
        return "Trade sentiment analysis by ASAN Macro."
    para = report.split("\n\n")[0].strip()
    sentences = re.split(r"(?<=[.!?])\s+", para)
    one_liner = ""
    for s in sentences:
        if len(one_liner) + len(s) + 1 <= max_chars:
            one_liner += (" " if one_liner else "") + s
        else:
            break
    if not one_liner:
        one_liner = report[: max_chars - 3].rstrip() + "..."
    return one_liner or "Trade sentiment analysis by ASAN Macro."


def _report_to_json(report: str) -> dict:
    """Prefer the structured brief from the agent. Fall back to heading splits."""
    from datetime import datetime

    brief = last_brief()
    if brief is not None:
        payload = brief.model_dump()
        payload["full_report"] = report
        return payload

    report = report.strip()
    if not report:
        return {"summary": "", "key_regions_sectors": "", "so_what": "", "whats_next": "", "bullets": [], "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "full_report": ""}

    # Split by ### Header lines (case-insensitive)
    parts = re.split(r"\n\s*###\s+", report, flags=re.IGNORECASE)
    summary = key_regions = so_what = whats_next = ""
    for i, block in enumerate(parts):
        block = block.strip()
        if not block:
            continue
        first_line, _, rest = block.partition("\n")
        first_lower = first_line.lower().strip(":\"\' ")
        if i == 0 and "summary" not in first_lower and "key" not in first_lower and "so what" not in first_lower and "what" not in first_lower:
            summary = block
            continue
        if "summary" in first_lower:
            summary = rest.strip()
        elif "key region" in first_lower or "key sector" in first_lower:
            key_regions = rest.strip()
        elif "so what" in first_lower:
            so_what = rest.strip()
        elif "what" in first_lower and "next" in first_lower:
            whats_next = rest.strip()

    if not summary and parts:
        summary = parts[0].strip()[: 2000]

    # Bullets: lines starting with "1." or "**Title**:"
    def extract_bullets(text, limit=5):
        out = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\d+[.)]\s*\*\*(.+?)\*\*:\s*(.*)", line)
            if m:
                out.append(m.group(1).strip() + ": " + m.group(2).strip()[: 150])
            else:
                m2 = re.match(r"^\d+[.)]\s*(.+)", line)
                if m2:
                    out.append(m2.group(1).strip()[: 200])
            if len(out) >= limit:
                break
        return out

    bullets = []
    bullets.extend(extract_bullets(key_regions, 5))
    bullets.extend(extract_bullets(so_what, 5))
    bullets.extend(extract_bullets(whats_next, 5))
    if not bullets and summary:
        bullets = [summary[: 300]]

    return {
        "summary": summary,
        "key_regions_sectors": key_regions,
        "so_what": so_what,
        "whats_next": whats_next,
        "bullets": bullets[: 15],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "full_report": report,
    }


def _load_csv_into_db(csv_path: Path):
    """Load a CSV with trade data into the database. Columns: year, reporter_region, partner_region, sector, flow_type, value_usd."""
    import csv
    import sqlite3
    conn = sqlite3.connect(str(get_db_path()))
    cur = conn.cursor()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    year = int(row.get("year", 0))
                    reporter = row.get("reporter_region", "").strip()
                    partner = row.get("partner_region", "").strip()
                    sector = row.get("sector", "").strip()
                    flow_type = row.get("flow_type", "export").strip()
                    val = float(row.get("value_usd", 0))
                except (ValueError, KeyError):
                    continue
                if not reporter or not partner or not sector:
                    continue
                cur.execute(
                    "INSERT INTO trade_flows (year, reporter_region, partner_region, sector, flow_type, value_usd) VALUES (?,?,?,?,?,?)",
                    (year, reporter, partner, sector, flow_type, val),
                )
        conn.commit()
        print(f"Loaded CSV rows into DB: {csv_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
