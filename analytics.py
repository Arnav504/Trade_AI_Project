"""Row-level trade aggregates for charts. Figures come from SQLite, not from model prose."""
import sqlite3
from config import get_db_path


def _connect():
    return sqlite3.connect(str(get_db_path()))


def load_flows() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT year, reporter_region, partner_region, sector, flow_type, value_usd
            FROM trade_flows
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "year": row[0],
            "reporter": row[1],
            "partner": row[2],
            "sector": row[3],
            "flow_type": row[4],
            "value_usd": row[5] or 0,
        }
        for row in rows
    ]


def _matches(row: dict, regions: list[str] | None, sectors: list[str] | None) -> bool:
    if sectors and row["sector"] not in sectors:
        return False
    if regions and row["reporter"] not in regions and row["partner"] not in regions:
        return False
    return True


def _money(value: float) -> str:
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000:
        return f"{sign}${number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{sign}${number / 1_000_000:.1f}M"
    return f"{sign}${number:,.0f}"


def describe_spans(spans: list[dict]) -> str:
    """Start value, end value, and percent change for the leading paths."""
    parts = []
    for span in spans[:3]:
        if span["span_pct"] is None or span["first_year"] == span["last_year"]:
            parts.append(f"{span['label']} is {_money(span['last_value'])} in {span['last_year']}.")
            continue
        parts.append(
            f"{span['label']} went from {_money(span['first_value'])} in {span['first_year']} "
            f"to {_money(span['last_value'])} in {span['last_year']} ({span['span_pct']:+.1f}%)."
        )
    return " ".join(parts)


def flow_spans(
    regions: list[str] | None = None,
    sectors: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict]:
    """Every year, plus the first-to-last change, for each flow pair."""
    buckets: dict[tuple, list] = {}
    for row in load_flows():
        if year_from is not None and row["year"] < year_from:
            continue
        if year_to is not None and row["year"] > year_to:
            continue
        if not _matches(row, regions, sectors):
            continue
        key = (row["reporter"], row["partner"], row["sector"], row["flow_type"])
        buckets.setdefault(key, []).append(row)
    spans = []
    for (reporter, partner, sector, flow_type), raw in buckets.items():
        by_year: dict[int, float] = {}
        for item in raw:
            by_year[item["year"]] = by_year.get(item["year"], 0) + item["value_usd"]
        points = [{"year": year, "value_usd": by_year[year]} for year in sorted(by_year)]
        first, last = points[0], points[-1]
        prev = points[-2] if len(points) > 1 else None
        span_pct = None
        if first["year"] != last["year"] and first["value_usd"]:
            span_pct = round(100.0 * (last["value_usd"] - first["value_usd"]) / first["value_usd"], 1)
        yoy_pct = None
        if prev and prev["value_usd"]:
            yoy_pct = round(100.0 * (last["value_usd"] - prev["value_usd"]) / prev["value_usd"], 1)
        spans.append(
            {
                "reporter": reporter,
                "partner": partner,
                "sector": sector,
                "flow_type": flow_type,
                "first_year": first["year"],
                "first_value": first["value_usd"],
                "last_year": last["year"],
                "last_value": last["value_usd"],
                "prev_year": prev["year"] if prev else None,
                "prev_value": prev["value_usd"] if prev else None,
                "span_pct": span_pct,
                "yoy_pct": yoy_pct,
                "points": points,
                "label": f"{reporter} → {partner} · {sector} · {flow_type}",
            }
        )
    spans.sort(key=lambda item: item["last_value"], reverse=True)
    return spans
