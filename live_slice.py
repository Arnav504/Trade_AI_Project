"""Fetch a Comtrade slice for one parsed question and store it. Never fills a miss with the synthetic seed."""
import sqlite3
from pathlib import Path

from config import get_db_path
from database import SAMPLE_TRADE, init_db
from focus import COUNTRY_CODES, plan_focus, trade_pairs


def _only_seed() -> bool:
    from analytics import load_flows

    sample = {
        (year, reporter, partner, sector, flow): value
        for year, _quarter, reporter, partner, sector, flow, value in SAMPLE_TRADE
    }
    rows = load_flows()
    if not rows:
        return False
    for row in rows:
        key = (row["year"], row["reporter"], row["partner"], row["sector"], row["flow_type"])
        official = sample.get(key)
        if official is None or abs(official - (row["value_usd"] or 0)) > 1:
            return False
    return True


def _connect():
    conn = init_db()
    return conn


def _window_covered(spec: dict, year_from: int, year_to: int) -> bool:
    have = _pair_years(spec, year_from, year_to)
    return all(year in have for year in range(year_from, year_to + 1))


def _pair_years(spec: dict, year_from: int, year_to: int) -> set[int]:
    conn = sqlite3.connect(str(get_db_path()))
    try:
        found = conn.execute(
            """
            SELECT DISTINCT year FROM trade_flows
            WHERE sector = ? AND year BETWEEN ? AND ?
              AND (
                    (reporter_region = ? AND partner_region = ?)
                 OR (reporter_region = ? AND partner_region = ?)
              )
            """,
            (
                spec["sector"],
                year_from,
                year_to,
                spec["reporter"],
                spec["partner"],
                spec["partner"],
                spec["reporter"],
            ),
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in found}


def _insert_rows(rows: list[tuple]) -> None:
    conn = _connect()
    try:
        for year, reporter, partner, sector, flow, value in rows:
            conn.execute(
                """
                DELETE FROM trade_flows
                WHERE year = ? AND reporter_region = ? AND partner_region = ?
                  AND sector = ? AND flow_type = ?
                """,
                (year, reporter, partner, sector, flow),
            )
            conn.execute(
                """
                INSERT INTO trade_flows
                    (year, quarter, reporter_region, partner_region, sector, flow_type, value_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (year, None, reporter, partner, sector, flow, value),
            )
        conn.commit()
    finally:
        conn.close()


def _comtrade():
    import importlib.util

    path = Path(__file__).resolve().parent / "scripts" / "fetch_comtrade.py"
    spec = importlib.util.spec_from_file_location("fetch_comtrade", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_fetch(spec: dict, years: list[int]) -> list[tuple]:
    reporter = COUNTRY_CODES.get(spec["reporter"])
    partner = COUNTRY_CODES.get(spec["partner"])
    if not reporter or not partner or not years:
        return []
    try:
        module = _comtrade()
    except Exception:
        return []
    found = []
    for year in years:
        try:
            records = module._fetch_slice(year, reporter, partner, spec["chapter"], spec["flow"])
        except Exception:
            continue
        for rec in records:
            item = dict(rec)
            item["_sector"] = spec["sector"]
            item["_flow"] = spec["flow"]
            row = module._map_comtrade_record(item)
            if row:
                found.append(row)
    if not found:
        return []
    return module.collapse_rows(found)


def _touching(plan: dict) -> bool:
    """Official rows that name one of the question's countries. The synthetic seed does not count."""
    if _only_seed():
        return False
    from analytics import flow_spans

    if plan.get("sectors"):
        sectors = plan["sectors"]
    elif plan.get("merchandise_total"):
        sectors = ["Merchandise"]
    else:
        sectors = None
    return bool(
        flow_spans(
            plan.get("regions") or None,
            sectors,
            plan.get("year_from"),
            plan.get("year_to"),
        )
    )


def _world_specs(plan: dict, query: str | None) -> list[dict]:
    regions = list(plan.get("regions") or [])
    if len(regions) != 1 or plan.get("blocs"):
        return []
    sectors = list(plan.get("sectors") or [])
    if not sectors and plan.get("merchandise_total"):
        sectors = ["Merchandise"]
    from focus import SECTOR_CHAPTERS, _flow_word

    flow = _flow_word(query)
    specs = []
    for sector in sectors[:1]:
        for chapter in SECTOR_CHAPTERS.get(sector, ("TOTAL",)):
            specs.append(
                {
                    "reporter": regions[0],
                    "partner": "World",
                    "sector": sector,
                    "chapter": chapter,
                    "flow": flow,
                }
            )
    return specs


def ensure_question_slice(plan: dict, query: str | None = None, fetch=None) -> dict:
    """Store the question's Comtrade slice when it is missing. An empty pull stays empty."""
    specs = trade_pairs(plan, query)
    seed = _only_seed()
    if not specs and not _touching(plan) and len(plan.get("regions") or []) == 1 and not plan.get("blocs"):
        specs = _world_specs(plan, query)
    if not specs:
        named = bool(plan.get("regions") or plan.get("sectors") or plan.get("blocs"))
        if named and not _touching(plan):
            return {"status": "empty", "note": "No official rows for this question."}
        if named:
            return {"status": "stored", "note": ""}
        return {"status": "panel", "note": ""}

    year_from = int(plan.get("year_from") or 2022)
    year_to = int(plan.get("year_to") or 2024)
    if not seed and all(_window_covered(spec, year_from, year_to) for spec in specs):
        return {"status": "stored", "note": ""}

    fetch = fetch or _default_fetch
    found: list[tuple] = []
    for spec in specs:
        have = set() if seed else _pair_years(spec, year_from, year_to)
        missing = [year for year in range(year_from, year_to + 1) if year not in have]
        if not missing:
            continue
        found.extend(fetch(spec, missing) or [])
    if found:
        _insert_rows(found)
        return {"status": "fetched", "note": ""}
    if not seed and any(_pair_years(spec, year_from, year_to) for spec in specs):
        return {"status": "stored", "note": ""}
    return {"status": "empty", "note": "No official rows for this question."}


def load_question(query: str, fetch=None) -> dict:
    plan = plan_focus(query)
    return ensure_question_slice(plan, query, fetch=fetch)
