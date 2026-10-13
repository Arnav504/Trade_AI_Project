"""Build the public gallery from the seeded trade panel. Charts and brief figures share one SQL read."""
import json
from pathlib import Path

from analytics import flow_spans, load_flows
from config import GALLERY_PATH, PROJECT_ROOT
from database import ensure_db
from focus import gather_context
from report_contract import DISCLAIMER, ToolTraceEntry, TradeBrief, render_brief, utc_now
from tracing import begin_trace, current_trace, end_trace


PRESETS = [
    {
        "id": "brics",
        "title": "BRICS",
        "query": "BRICS minerals and energy",
        "kicker": "Minerals and energy",
        "regions": ["Brazil", "Russia", "India", "China", "South Africa"],
        "sectors": ["Minerals", "Energy"],
    },
    {
        "id": "us-china-electronics",
        "title": "US–China electronics",
        "query": "US-China electronics",
        "kicker": "One sector, two directions of travel",
        "regions": ["USA", "China"],
        "sectors": ["Electronics"],
    },
    {
        "id": "nearshoring",
        "title": "Vietnam and Mexico",
        "query": "Vietnam and Mexico textiles and manufacturing",
        "kicker": "Supply into the United States",
        "regions": ["Vietnam", "Mexico"],
        "sectors": ["Textiles", "Manufacturing"],
    },
]


def _money(value: float) -> str:
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000:
        return f"{sign}${number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{sign}${number / 1_000_000:.1f}M"
    return f"{sign}${number:,.0f}"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _subject(span: dict) -> str:
    sector = span["sector"].lower()
    if span["flow_type"] == "export":
        return f"{span['reporter']} {sector} exports to {span['partner']}"
    return f"{span['reporter']} {sector} imports from {span['partner']}"


def _clause(span: dict) -> str:
    subject = _subject(span)
    if span["span_pct"] is None:
        return f"{subject} are {_money(span['last_value'])} in {span['last_year']}."
    latest = ""
    if (
        span["yoy_pct"] is not None
        and span["prev_year"] is not None
        and span["prev_year"] != span["first_year"]
    ):
        latest = f" The {span['last_year']} step versus {span['prev_year']} is {_pct(span['yoy_pct'])}."
    return (
        f"{subject} move from {_money(span['first_value'])} in {span['first_year']} "
        f"to {_money(span['last_value'])} in {span['last_year']} ({_pct(span['span_pct'])}).{latest}"
    )


def _chart_levels(spans: list[dict], limit: int = 6) -> list[dict]:
    rows = sorted(spans, key=lambda span: span["last_value"], reverse=True)[:limit]
    return [
        {
            "label": span["label"],
            "value": span["last_value"],
            "display": f"{_money(span['last_value'])} ({span['last_year']})",
            "year": span["last_year"],
        }
        for span in rows
    ]


def _chart_yoy(spans: list[dict], limit: int = 8) -> list[dict]:
    rows = [span for span in spans if span["yoy_pct"] is not None]
    rows.sort(key=lambda span: abs(span["yoy_pct"]), reverse=True)
    rows = rows[:limit]
    rows.sort(key=lambda span: span["yoy_pct"])
    return [
        {
            "label": f"{span['label']} · {span['last_year']}",
            "value": span["yoy_pct"],
            "display": _pct(span["yoy_pct"]),
            "year": span["last_year"],
        }
        for span in rows
    ]


def live_note(flow_count: int, world_bank_count: int = 0, imf_count: int = 0) -> str:
    """Source line after a live refresh. Only names a source when that pull returned rows."""
    parts = [
        "UN Comtrade annual merchandise. "
        "HS 26 minerals, HS 27 energy, HS 85 electronics, HS 61 and 62 textiles, HS 84 and 87 manufacturing. "
        f"{flow_count} flows"
    ]
    if world_bank_count:
        parts.append(f"World Bank merchandise exports and imports ({world_bank_count} observations)")
    if imf_count:
        parts.append(f"IMF WEO current account ({imf_count} observations)")
    return ". ".join(parts) + f". Retrieved {utc_now()}. Not a forecast."


def comtrade_note(row_count: int) -> str:
    """Source line for a gallery built from the HS corridor pull."""
    return (
        "UN Comtrade annual merchandise. "
        "HS 26 minerals, HS 27 energy, HS 85 electronics, HS 61 and 62 textiles, HS 84 and 87 manufacturing. "
        f"{row_count} flows. Retrieved {utc_now()}. Not a forecast."
    )


def charts_for_focus(query: str | None) -> dict:
    """Bars for the same region and sector filter the tools use."""
    from focus import plan_focus

    plan = plan_focus(query)
    spans = flow_spans(plan["regions"] or None, plan["sectors"] or None)
    return {"top_flows": _chart_levels(spans), "yoy": _chart_yoy(spans)}


def _compose(preset: dict, spans: list[dict], trace: list[dict], official: bool = False) -> dict:
    ranked = sorted(spans, key=lambda span: abs(span["span_pct"] or 0), reverse=True)
    lead = ranked[:3] or spans[:3]
    summary = " ".join(_clause(span) for span in lead)
    if not summary:
        summary = (
            "This focus has no matching rows in the current panel."
            if official
            else "This focus has no matching rows in the seeded panel."
        )
    key_lines = [_clause(span) for span in spans[:6]]
    key_regions = " ".join(key_lines) if key_lines else "No matching flows."
    macro = ""
    if official:
        from macro_data import render_macro

        macro = render_macro(preset["regions"])
    ups = [span for span in spans if (span["span_pct"] or 0) > 0]
    downs = [span for span in spans if (span["span_pct"] or 0) < 0]
    up_names = ", ".join(_subject(span) for span in ups[:3])
    down_names = ", ".join(_subject(span) for span in downs[:3])
    if ups and downs:
        movement = f"higher paths are {up_names}. Lower paths are {down_names}."
    elif ups:
        movement = f"the filtered flows are higher over the period: {up_names}."
    elif downs:
        movement = f"the filtered flows are lower over the period: {down_names}."
    else:
        movement = "the filtered rows do not show a first-to-last change."
    if official:
        so_what = (
            f"In this UN Comtrade slice, {movement} "
            "That is a change in the selected HS chapters, not a full trade balance or a forecast."
        )
    else:
        so_what = (
            f"Inside this illustrative panel, {movement} "
            "That is a partner shift in the seeded rows, not an official trade balance or a forecast."
        )
    watch = ranked[0]["label"] if ranked else "the same reporter–partner pairs"
    whats_next = (
        f"The next point that would change this brief is another year of {watch}. "
        "Until that row exists, the chart and this text describe the same database values."
    )
    bullets = [_clause(span).rstrip(".") for span in lead]
    brief = TradeBrief(
        id=preset["id"],
        title=preset["title"],
        summary=summary,
        key_regions_sectors=key_regions,
        so_what=so_what,
        whats_next=whats_next,
        bullets=bullets,
        disclaimer=DISCLAIMER,
        tool_trace=[ToolTraceEntry(**item) for item in trace],
        focus=preset["query"],
        generated_at=utc_now(),
        source="tool_output",
    )
    rendered = render_brief(brief)
    brief.full_report = rendered
    payload = brief.model_dump()
    payload["kicker"] = preset["kicker"]
    payload["macro"] = macro
    payload["charts"] = {"top_flows": _chart_levels(spans), "yoy": _chart_yoy(spans)}
    return payload


def _trace_for(query: str) -> list[dict]:
    token = begin_trace()
    try:
        gather_context(query)
        return list(current_trace())
    finally:
        end_trace(token)


def build_gallery(data_note: str | None = None) -> dict:
    """Compose three briefs and the chart series from the current database."""
    ensure_db()
    official = data_note is not None
    all_spans = flow_spans()
    briefs = []
    for preset in PRESETS:
        spans = flow_spans(preset["regions"], preset["sectors"])
        briefs.append(_compose(preset, spans, _trace_for(preset["query"]), official=official))
    note = data_note or (
        f"Illustrative synthetic trade panel ({len(load_flows())} flows, 2022–2024). "
        "Not official UN Comtrade statistics."
    )
    return {
        "data_note": note,
        "disclaimer": DISCLAIMER,
        "generated_at": utc_now(),
        "how_it_works": {
            "tools": [
                "list_regions",
                "list_sectors",
                "query_trade_flows",
                "get_region_summary",
                "get_sector_summary",
                "get_yoy_growth",
                "get_top_flows",
                "get_trade_trends",
                "get_macro_context",
                "rag_retrieve",
            ],
            "backends": (
                "OpenAI runs a multi-turn tool loop. Ollama and Gemini receive a focus-specific "
                "tool pack, then write the brief in one call."
            ),
        },
        "charts": {"top_flows": _chart_levels(all_spans), "yoy": _chart_yoy(all_spans)},
        "briefs": briefs,
    }


def write_gallery(payload: dict | None = None) -> Path:
    payload = payload or build_gallery()
    GALLERY_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    GALLERY_PATH.write_text(text, encoding="utf-8")
    web_copy = PROJECT_ROOT / "web" / "data" / "gallery.json"
    web_copy.parent.mkdir(parents=True, exist_ok=True)
    web_copy.write_text(text, encoding="utf-8")
    return GALLERY_PATH
