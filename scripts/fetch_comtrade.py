#!/usr/bin/env python3
"""
Fetch trade data from UN Comtrade (free tier) and load into ASAN Macro DB.
Maps Comtrade JSON to our schema: year, reporter_region, partner_region, sector, flow_type, value_usd.

Usage:
  python scripts/fetch_comtrade.py
  python scripts/fetch_comtrade.py --years 2022 2023 2024 --reporters 156 842 --save-csv
  COMTRADE_API_KEY=your_key python scripts/fetch_comtrade.py

Requires: requests. Optional: COMTRADE_API_KEY in .env for higher limits.
See DOC_COMTRADE.md for API key and rate limits.
"""
import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_env = PROJECT_ROOT / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env), override=True)
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("Install requests: pip install requests", file=sys.stderr)
    sys.exit(1)

DEFAULT_BASE = "https://comtradeplus.un.org/api/get"


def _base_url():
    return os.environ.get("COMTRADE_BASE_URL", DEFAULT_BASE).strip() or DEFAULT_BASE


def _api_key():
    return os.environ.get("COMTRADE_API_KEY", "").strip()


M49 = {
    "156": "China", "842": "USA", "076": "Brazil", "356": "India", "643": "Russia",
    "710": "South Africa", "484": "Mexico", "704": "Vietnam", "818": "Egypt",
    "360": "Indonesia", "784": "United Arab Emirates", "0": "World",
}

_COUNTRY_ALIASES = {
    "united states": "USA",
    "united states of america": "USA",
    "usa": "USA",
    "viet nam": "Vietnam",
    "vietnam": "Vietnam",
    "russian federation": "Russia",
    "russia": "Russia",
    "china": "China",
    "india": "India",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "south africa": "South Africa",
}

HS_SECTOR = {
    "26": "Minerals",
    "27": "Energy",
    "61": "Textiles",
    "62": "Textiles",
    "84": "Manufacturing",
    "85": "Electronics",
    "87": "Manufacturing",
}

# Reporter, partner, HS chapter, stored sector, and flow for the public panel.
CORRIDORS = (
    {"reporter": "356", "partner": "643", "cmd": "27", "sector": "Energy", "flow": "import"},
    {"reporter": "076", "partner": "156", "cmd": "26", "sector": "Minerals", "flow": "export"},
    {"reporter": "710", "partner": "156", "cmd": "26", "sector": "Minerals", "flow": "export"},
    {"reporter": "156", "partner": "842", "cmd": "85", "sector": "Electronics", "flow": "export"},
    {"reporter": "704", "partner": "842", "cmd": "61", "sector": "Textiles", "flow": "export"},
    {"reporter": "704", "partner": "842", "cmd": "62", "sector": "Textiles", "flow": "export"},
    {"reporter": "484", "partner": "842", "cmd": "84", "sector": "Manufacturing", "flow": "export"},
    {"reporter": "484", "partner": "842", "cmd": "87", "sector": "Manufacturing", "flow": "export"},
)


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return str(value).strip()


def _normalize_country(name: str) -> str:
    text = " ".join(_text(name).replace(".", "").split())
    if not text:
        return ""
    return _COUNTRY_ALIASES.get(text.lower(), text)


def _country_name(code) -> str:
    if code is None or _text(code) == "":
        return "Unknown"
    key = _text(code)
    if key.isdigit():
        key = "0" if key == "0" else key.zfill(3)
    return _normalize_country(M49.get(key, key))


def _cmd_digits(value) -> str:
    text = _text(value)
    try:
        number = float(text)
        if number == int(number):
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return "".join(ch for ch in text if ch.isdigit())


def _sector_from_record(rec: dict) -> str:
    forced = _text(rec.get("_sector"))
    if forced:
        return forced
    digits = _cmd_digits(rec.get("cmdCode"))
    chapter = digits[:2] if len(digits) >= 2 else ""
    if chapter in HS_SECTOR:
        return HS_SECTOR[chapter]
    return _text(rec.get("cmdDesc") or rec.get("cmdCode") or rec.get("aggLevel") or "TOTAL") or "TOTAL"


def _flow_from_record(rec: dict) -> str:
    forced = _text(rec.get("_flow")).lower()
    if forced in ("import", "export"):
        return forced
    flow_raw = _text(rec.get("flowDesc") or rec.get("rgDesc"))
    code = _text(rec.get("flowCode"))
    if flow_raw.lower().startswith("i") or code in ("1", "M"):
        return "import"
    return "export"


def _map_comtrade_record(rec: dict) -> tuple:
    """Map one Comtrade API record to (year, reporter_region, partner_region, sector, flow_type, value_usd)."""
    year = rec.get("period") or rec.get("refYear") or rec.get("year") or (_text(rec.get("pfDate"))[:4] or 0)
    try:
        year = int(year) if year else 0
    except (TypeError, ValueError):
        return None
    reporter = _normalize_country(rec.get("reporterDesc") or rec.get("reporter") or _country_name(rec.get("reporterCode")))
    partner = _normalize_country(rec.get("partnerDesc") or rec.get("partner") or _country_name(rec.get("partnerCode")))
    sector = _sector_from_record(rec)
    flow = _flow_from_record(rec)
    value = rec.get("primaryValue") or rec.get("customsValue") or rec.get("netWgt") or 0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not reporter or not partner or not year:
        return None
    return (year, reporter, partner, sector, flow, value)


def collapse_rows(rows: list) -> list:
    """Sum HS lines that share a year, pair, sector, and flow."""
    totals = {}
    for year, reporter, partner, sector, flow, value in rows:
        key = (year, reporter, partner, sector, flow)
        totals[key] = totals.get(key, 0.0) + float(value)
    return [(*key, value) for key, value in totals.items()]


def _dataframe_row_to_record(row) -> dict:
    """Convert a comtradeapicall DataFrame row (Series or dict) to a dict _map_comtrade_record understands."""
    if isinstance(row, dict):
        return row
    d = {}
    for col in ["period", "refYear", "year", "reporterCode", "reporterDesc", "reporter",
                "partnerCode", "partnerDesc", "partner", "cmdCode", "cmdDesc", "aggLevel",
                "flowCode", "flowDesc", "rgDesc", "primaryValue", "customsValue", "netWgt"]:
        try:
            if hasattr(row, "get") and row.get(col) is not None:
                d[col] = row.get(col)
            elif hasattr(row, "__getitem__") and col in row:
                d[col] = row[col]
        except Exception:
            pass
    return d


def _records_from_frame(df) -> list:
    records = []
    if df is None or (hasattr(df, "empty") and df.empty):
        return records
    if hasattr(df, "iterrows"):
        for _, row in df.iterrows():
            rec = dict(row) if hasattr(row, "index") else (row if isinstance(row, dict) else _dataframe_row_to_record(row))
            if rec:
                records.append(rec)
    elif isinstance(df, list):
        for row in df:
            records.append(row if isinstance(row, dict) else _dataframe_row_to_record(row))
    return records


def _chapter_rows(records: list, chapter: str) -> list:
    """Prefer the chapter aggregate so child lines are not added on top of it."""
    chapter = str(chapter)
    exact = [rec for rec in records if _cmd_digits(rec.get("cmdCode")) == chapter]
    return exact or list(records)


def fetch_comtrade_via_package(
    years=None,
    reporters=None,
    partner_code=None,
    max_records=500,
    api_key=None,
    cmd_code="TOTAL",
    flow_codes=("X", "M"),
) -> list:
    """
    Fetch using official comtradeapicall package (pip install comtradeapicall).
    Uses previewFinalData (no key, 500/request) or getFinalData (with key, 2500/request).
    Returns list of raw record dicts for _map_comtrade_record / load_into_db.
    """
    try:
        import comtradeapicall
    except ImportError:
        return []

    years = years or [2022, 2023, 2024]
    # Reporter M49 codes: 156=China, 842=USA, 076=Brazil, 356=India, 643=Russia, 710=South Africa, 484=Mexico, 704=Viet Nam
    reporters = reporters or ["156", "842", "076", "356", "643", "710", "484", "704"]
    api_key = api_key or _api_key()
    all_records = []
    for year in years:
        for rep in reporters:
            for flow_code in flow_codes:
                try:
                    if api_key:
                        df = comtradeapicall.getFinalData(
                            api_key,
                            typeCode="C",
                            freqCode="A",
                            clCode="HS",
                            period=str(year),
                            reporterCode=str(rep),
                            cmdCode=str(cmd_code),
                            flowCode=flow_code,
                            partnerCode=partner_code,
                            partner2Code=None,
                            customsCode=None,
                            motCode=None,
                            maxRecords=max_records,
                            format_output="JSON",
                            aggregateBy=None,
                            breakdownMode="classic",
                            countOnly=None,
                            includeDesc=True,
                        )
                    else:
                        df = comtradeapicall.previewFinalData(
                            typeCode="C",
                            freqCode="A",
                            clCode="HS",
                            period=str(year),
                            reporterCode=str(rep),
                            cmdCode=str(cmd_code),
                            flowCode=flow_code,
                            partnerCode=partner_code,
                            partner2Code=None,
                            customsCode=None,
                            motCode=None,
                            maxRecords=min(max_records, 500),
                            format_output="JSON",
                            aggregateBy=None,
                            breakdownMode="classic",
                            countOnly=None,
                            includeDesc=True,
                        )
                except Exception as e:
                    print(f"comtradeapicall request failed (year={year}, reporter={rep}, flow={flow_code}): {e}", file=sys.stderr)
                    continue
                all_records.extend(_records_from_frame(df))
                time.sleep(1)
    return all_records


def fetch_comtrade(
    years=None,
    reporters=None,
    partner="0",
    flow="all",
    commodity="TOTAL",
    max_records=5000,
    base_url=None,
    api_key=None,
) -> list:
    years = years or [2022, 2023, 2024]
    reporters = reporters or ["156", "842", "076", "356", "643", "710", "484", "704"]
    base_url = base_url or _base_url()
    api_key = api_key or _api_key()
    headers = {}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key

    all_records = []
    for year in years:
        for rep in reporters:
            for rg in ([1, 2] if flow == "all" else [2 if flow == "export" else 1]):
                params = {
                    "type": "C", "freq": "A", "px": "HS", "ps": year,
                    "r": rep, "p": partner, "rg": rg, "cc": commodity,
                    "fmt": "json", "maxRecords": min(max_records, 50000),
                }
                try:
                    r = requests.get(base_url, params=params, headers=headers, timeout=60)
                    if r.status_code == 429:
                        time.sleep(60)
                        r = requests.get(base_url, params=params, headers=headers, timeout=60)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    print(f"API request failed (year={year}, reporter={rep}): {e}", file=sys.stderr)
                    continue
                records = data if isinstance(data, list) else data.get("data", data.get("results", []))
                if not records and isinstance(data, dict):
                    records = data.get("dataset", [])
                for rec in records:
                    if isinstance(rec, dict):
                        all_records.append(rec)
                time.sleep(1)
    return all_records


def _fetch_slice(year, reporter, partner, cmd, flow, api_key=None) -> list:
    """One reporter, partner, HS chapter, and flow. Package first, then the HTTP API."""
    flow_code = "M" if flow == "import" else "X"
    http_flow = "import" if flow == "import" else "export"
    records = fetch_comtrade_via_package(
        years=[year],
        reporters=[str(reporter)],
        partner_code=str(partner),
        max_records=500,
        api_key=api_key,
        cmd_code=str(cmd),
        flow_codes=(flow_code,),
    )
    if not records:
        records = fetch_comtrade(
            years=[year],
            reporters=[str(reporter)],
            partner=str(partner),
            flow=http_flow,
            commodity=str(cmd),
            max_records=500,
            api_key=api_key,
        )
    return _chapter_rows(records, str(cmd))


def fetch_corridors(years=None, api_key=None) -> list:
    """Pull the public HS corridors. Returns raw records tagged with sector and flow."""
    years = years or [2022, 2023, 2024]
    api_key = _api_key() or None if api_key is None else (api_key or None)
    found = []
    for corridor in CORRIDORS:
        expected = _country_name(corridor["partner"])
        for year in years:
            matched = []
            other = []
            for rec in _fetch_slice(
                year,
                corridor["reporter"],
                corridor["partner"],
                corridor["cmd"],
                corridor["flow"],
                api_key,
            ):
                item = dict(rec)
                item["_sector"] = corridor["sector"]
                item["_flow"] = corridor["flow"]
                row = _map_comtrade_record(item)
                if not row:
                    continue
                if row[2] == expected:
                    matched.append(item)
                elif row[2] not in {"World", "Unknown"}:
                    other.append(item)
            found.extend(matched or other)
    return found


def load_into_db(records: list, replace: bool = False) -> int:
    from database import init_db

    conn = init_db()
    cur = conn.cursor()
    rows = []
    for rec in records:
        if isinstance(rec, tuple):
            rows.append(rec)
        else:
            row = _map_comtrade_record(rec)
            if row:
                rows.append(row)
    rows = collapse_rows(rows)
    if not rows:
        conn.close()
        return 0
    if replace:
        cur.execute("DELETE FROM trade_flows")
    count = 0
    for year, reporter, partner, sector, flow_type, value_usd in rows:
        cur.execute(
            """INSERT INTO trade_flows (year, reporter_region, partner_region, sector, flow_type, value_usd)
               VALUES (?,?,?,?,?,?)""",
            (year, reporter, partner, sector, flow_type, value_usd),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def save_csv(records: list, path: Path) -> int:
    import csv
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "reporter_region", "partner_region", "sector", "flow_type", "value_usd"])
        for rec in records:
            row = _map_comtrade_record(rec)
            if not row:
                continue
            w.writerow(row)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Fetch UN Comtrade data into ASAN Macro DB.")
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024], help="Years to fetch")
    parser.add_argument("--reporters", nargs="+", default=["156", "842", "076", "356", "643", "710", "484", "704"],
                        help="M49 reporter codes")
    parser.add_argument("--partner", default="0", help="Partner code (0=World)")
    parser.add_argument("--flow", choices=["all", "export", "import"], default="all")
    parser.add_argument("--commodity", default="TOTAL", help="Commodity code")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--no-db", action="store_true", help="Do not load into DB")
    parser.add_argument("--replace", action="store_true", help="Clear trade_flows before loading (use only dynamic data)")
    parser.add_argument("--use-package", action="store_true", help="Use only comtradeapicall package (skip HTTP fallback)")
    parser.add_argument("--corridors", action="store_true", help="Fetch the public HS corridors instead of a broad reporter pull")
    parser.add_argument("--save-csv", type=str, default=None, metavar="PATH", help="Save mapped data to CSV")
    args = parser.parse_args()

    from database import ensure_db
    ensure_db()

    print("Fetching from UN Comtrade ...", file=sys.stderr)
    if args.corridors:
        records = fetch_corridors(years=args.years)
    else:
        records = fetch_comtrade_via_package(
            years=args.years, reporters=args.reporters, partner_code=args.partner if args.partner != "0" else None,
            max_records=min(args.max_records, 2500), api_key=_api_key() or None,
        )
        if records:
            print("Fetched via comtradeapicall package.", file=sys.stderr)
        if not records and not args.use_package:
            records = fetch_comtrade(
                years=args.years, reporters=args.reporters, partner=args.partner,
                flow=args.flow, commodity=args.commodity, max_records=args.max_records,
            )
    print(f"Fetched {len(records)} raw records", file=sys.stderr)

    if not records:
        print("No records returned. Check COMTRADE_BASE_URL and API. See DOC_COMTRADE.md.", file=sys.stderr)
        return 1

    if args.save_csv:
        n = save_csv(records, Path(args.save_csv))
        print(f"Saved {n} rows to {args.save_csv}", file=sys.stderr)

    if not args.no_db:
        n = load_into_db(records, replace=args.replace)
        print(f"Loaded {n} rows into DB", file=sys.stderr)
        if n == 0:
            print("No mapped rows. Database left unchanged.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
