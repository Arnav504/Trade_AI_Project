"""Map a plain trade question onto countries, blocs, sectors, and a year window."""
import re

import tools as T
from tracing import traced_call


_REGION_WORDS = (
    ("south africa", "South Africa"),
    ("united arab emirates", "United Arab Emirates"),
    ("united kingdom", "United Kingdom"),
    ("united states", "USA"),
    ("czech republic", "Czechia"),
    ("south korea", "South Korea"),
    ("north korea", ""),
    ("saudi arabia", "Saudi Arabia"),
    ("u.s.", "USA"),
    ("usa", "USA"),
    ("us-china", "USA"),
    ("us china", "USA"),
    ("china", "China"),
    ("brazil", "Brazil"),
    ("india", "India"),
    ("russia", "Russia"),
    ("vietnam", "Vietnam"),
    ("mexico", "Mexico"),
    ("germany", "Germany"),
    ("france", "France"),
    ("italy", "Italy"),
    ("spain", "Spain"),
    ("netherlands", "Netherlands"),
    ("poland", "Poland"),
    ("belgium", "Belgium"),
    ("sweden", "Sweden"),
    ("ireland", "Ireland"),
    ("austria", "Austria"),
    ("portugal", "Portugal"),
    ("greece", "Greece"),
    ("denmark", "Denmark"),
    ("finland", "Finland"),
    ("czechia", "Czechia"),
    ("hungary", "Hungary"),
    ("romania", "Romania"),
    ("japan", "Japan"),
    ("canada", "Canada"),
    ("australia", "Australia"),
    ("indonesia", "Indonesia"),
    ("thailand", "Thailand"),
    ("malaysia", "Malaysia"),
    ("singapore", "Singapore"),
    ("philippines", "Philippines"),
    ("myanmar", "Myanmar"),
    ("cambodia", "Cambodia"),
    ("laos", "Laos"),
    ("brunei", "Brunei"),
    ("turkey", "Turkey"),
    ("argentina", "Argentina"),
    ("nigeria", "Nigeria"),
    ("egypt", "Egypt"),
    ("britain", "United Kingdom"),
    ("uae", "United Arab Emirates"),
    ("korea", "South Korea"),
    ("uk", "United Kingdom"),
)

# Short member lists. A question uses the first few, not every economy in the bloc.
EU_MEMBERS = (
    "Germany", "France", "Italy", "Netherlands", "Spain", "Poland",
    "Belgium", "Sweden", "Ireland", "Austria", "Portugal", "Greece",
    "Denmark", "Finland", "Czechia", "Hungary", "Romania",
)
ASEAN_MEMBERS = (
    "Vietnam", "Indonesia", "Thailand", "Malaysia", "Singapore", "Philippines",
    "Myanmar", "Cambodia", "Laos", "Brunei",
)
USMCA_MEMBERS = ("USA", "Mexico", "Canada")
G7_MEMBERS = ("USA", "Japan", "Germany", "United Kingdom", "France", "Italy", "Canada")
BRICS_REGIONS = ("Brazil", "Russia", "India", "China", "South Africa")

_BLOCS = (
    ("european union", "EU", EU_MEMBERS),
    ("asean", "ASEAN", ASEAN_MEMBERS),
    ("usmca", "USMCA", USMCA_MEMBERS),
    ("g-7", "G7", G7_MEMBERS),
    ("g7", "G7", G7_MEMBERS),
    ("brics", "BRICS", BRICS_REGIONS),
    ("eu", "EU", EU_MEMBERS),
)

SECTOR_CHAPTERS = {
    "Minerals": ("26",),
    "Energy": ("27",),
    "Electronics": ("85",),
    "Textiles": ("61", "62"),
    "Manufacturing": ("84", "87"),
    "Merchandise": ("TOTAL",),
}

_SECTOR_WORDS = (
    ("electronics", "Electronics"),
    ("minerals", "Minerals"),
    ("energy", "Energy"),
    ("textiles", "Textiles"),
    ("textile", "Textiles"),
    ("manufacturing", "Manufacturing"),
)

COUNTRY_CODES = {
    "China": "156",
    "USA": "842",
    "Brazil": "076",
    "India": "356",
    "Russia": "643",
    "South Africa": "710",
    "Mexico": "484",
    "Vietnam": "704",
    "Germany": "276",
    "France": "251",
    "Italy": "380",
    "Spain": "724",
    "Netherlands": "528",
    "Poland": "616",
    "Belgium": "056",
    "Sweden": "752",
    "Ireland": "372",
    "Austria": "040",
    "Portugal": "620",
    "Greece": "300",
    "Denmark": "208",
    "Finland": "246",
    "Czechia": "203",
    "Hungary": "348",
    "Romania": "642",
    "United Kingdom": "826",
    "Japan": "392",
    "Canada": "124",
    "Australia": "036",
    "Indonesia": "360",
    "Thailand": "764",
    "Malaysia": "458",
    "Singapore": "702",
    "Philippines": "608",
    "Myanmar": "104",
    "Cambodia": "116",
    "Laos": "418",
    "Brunei": "096",
    "South Korea": "410",
    "Saudi Arabia": "682",
    "United Arab Emirates": "784",
    "Turkey": "792",
    "Argentina": "032",
    "Nigeria": "566",
    "Egypt": "818",
    "World": "0",
}

_MAX_PAIRS = 6


def _has(text: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", text) is not None


def _members_for(query: str, canon: str, members: tuple[str, ...]) -> list[str]:
    limit = len(members) if canon == "BRICS" else 4
    named = [name for name in members if _has(query, name.lower())]
    chosen: list[str] = []
    for name in list(members[:limit]) + named:
        if name not in chosen:
            chosen.append(name)
    return chosen[:6]


def _year_window(query: str) -> tuple[int, int]:
    match = re.search(r"\b(20\d{2})\s*(?:to|through|–|-)\s*(20\d{2})\b", query)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
    else:
        match = re.search(r"\b(?:since|from)\s+(20\d{2})\b", query)
        if match:
            start, end = int(match.group(1)), 2024
        else:
            match = re.search(r"\bin\s+(20\d{2})\b", query)
            if match:
                year = int(match.group(1))
                start = end = year
            else:
                start, end = 2022, 2024
    if start > end:
        start, end = end, start
    if end - start > 5:
        start = end - 5
    return start, end


def plan_focus(query: str | None) -> dict:
    """Countries, blocs, sectors, and years in a question. No sector means total merchandise."""
    q = (query or "").lower()
    regions: list[str] = []
    sectors: list[str] = []
    blocs: list[str] = []
    member_set: set[str] = set()

    def add_region(name: str) -> None:
        if name and name not in regions:
            regions.append(name)

    def add_sector(name: str) -> None:
        if name not in sectors:
            sectors.append(name)

    for needle, name in _REGION_WORDS:
        if needle == "korea" and _has(q, "north korea"):
            continue
        if _has(q, needle):
            add_region(name)
    if _has(q, "us-china") or _has(q, "us china") or _has(q, "china"):
        add_region("China")
    if _has(q, "us") or _has(q, "usa") or _has(q, "u.s.") or _has(q, "united states"):
        add_region("USA")
    for needle, canon, members in _BLOCS:
        if _has(q, needle):
            if canon not in blocs:
                blocs.append(canon)
            for name in _members_for(q, canon, members):
                member_set.add(name)
                add_region(name)
    if blocs:
        partners = [name for name in regions if name not in member_set]
        members = [name for name in regions if name in member_set]
        regions = partners + members
    for needle, name in _SECTOR_WORDS:
        if _has(q, needle):
            add_sector(name)
    year_from, year_to = _year_window(q)
    sector_named = bool(sectors)
    return {
        "regions": regions,
        "sectors": sectors,
        "blocs": blocs,
        "year_from": year_from,
        "year_to": year_to,
        "sector_named": sector_named,
        "merchandise_total": (not sector_named) and bool(regions or blocs),
    }


def _flow_word(query: str | None) -> str:
    text = (query or "").lower()
    if _has(text, "import") or _has(text, "imports"):
        if not (_has(text, "export") or _has(text, "exports")):
            return "import"
    return "export"


def trade_pairs(plan: dict, query: str | None = None) -> list[dict]:
    """Reporter–partner slices for one question. A bloc is capped at its members plus one partner."""
    regions = list(plan.get("regions") or [])
    blocs = list(plan.get("blocs") or [])
    member_set: set[str] = set()
    for _needle, canon, members in _BLOCS:
        if canon in blocs:
            member_set.update(_members_for((query or "").lower(), canon, members))
    partners = [name for name in regions if name not in member_set]
    members = [name for name in regions if name in member_set][:4]
    pairs: list[tuple[str, str]] = []
    if blocs and partners:
        partner = partners[0]
        pairs = [(member, partner) for member in members]
    elif len(regions) >= 2 and not blocs:
        pairs = [(regions[0], regions[1])]
    elif len(regions) == 1 and not blocs:
        return []
    sectors = list(plan.get("sectors") or [])
    if not sectors and plan.get("merchandise_total"):
        sectors = ["Merchandise"]
    if not sectors or not pairs:
        return []
    flow = _flow_word(query)
    specs: list[dict] = []
    for reporter, partner in pairs:
        for sector in sectors[:2]:
            for chapter in SECTOR_CHAPTERS.get(sector, ("TOTAL",)):
                specs.append(
                    {
                        "reporter": reporter,
                        "partner": partner,
                        "sector": sector,
                        "chapter": chapter,
                        "flow": flow,
                    }
                )
                if len(specs) >= _MAX_PAIRS:
                    return specs
    return specs


def spans_for_plan(plan: dict, query: str | None = None) -> list[dict]:
    """Year paths for this question. A named pair does not pick up a different corridor."""
    from analytics import flow_spans

    if plan.get("sectors"):
        sectors = plan["sectors"]
    elif plan.get("merchandise_total"):
        sectors = ["Merchandise"]
    else:
        sectors = None
    spans = flow_spans(
        plan.get("regions") or None,
        sectors,
        plan.get("year_from"),
        plan.get("year_to"),
    )
    specs = trade_pairs(plan, query)
    if not specs:
        return spans
    wanted = {(spec["reporter"], spec["partner"], spec["sector"]) for spec in specs}
    chosen = []
    for span in spans:
        forward = (span["reporter"], span["partner"], span["sector"])
        backward = (span["partner"], span["reporter"], span["sector"])
        if forward in wanted or backward in wanted:
            chosen.append(span)
    return chosen


def gather_context(user_query: str | None) -> str:
    """Call analyst tools for this focus and return their text. Records a tool trace when one is active."""
    plan = plan_focus(user_query)
    year_from = plan["year_from"]
    year_to = plan["year_to"]
    regions = plan["regions"][:5]
    sectors = plan["sectors"][:3]
    parts: list[str] = []

    def add(name: str, fn, **kwargs) -> None:
        parts.append(str(traced_call(name, fn, **kwargs)))

    add("list_regions", T.list_regions)
    add("list_sectors", T.list_sectors)
    add("rag_retrieve", T.rag_retrieve, query=user_query or "BRICS decoupling trade", limit=5)
    if not user_query:
        add("rag_retrieve", T.rag_retrieve, query="US China electronics", limit=5)

    if not regions and not sectors:
        add("query_trade_flows", T.query_trade_flows, year_from=year_from, year_to=year_to, limit=30)
        add("get_yoy_growth", T.get_yoy_growth, year_from=year_from, year_to=year_to)
        add("get_top_flows", T.get_top_flows, n=10, year_from=year_from, year_to=year_to)
        add("get_trade_trends", T.get_trade_trends, limit=10)
        add("get_macro_context", T.get_macro_context)
        return "\n\n".join(parts)

    for region in regions:
        add("get_region_summary", T.get_region_summary, region=region)
        add("get_trade_trends", T.get_trade_trends, region=region, limit=8)
        add("get_macro_context", T.get_macro_context, region=region)
    for sector in sectors:
        add("get_sector_summary", T.get_sector_summary, sector=sector)
        add("get_yoy_growth", T.get_yoy_growth, sector=sector, year_from=year_from, year_to=year_to)
    if regions and not sectors:
        add("get_yoy_growth", T.get_yoy_growth, region=regions[0], year_from=year_from, year_to=year_to)
    specs = trade_pairs(plan, user_query)
    if specs:
        for spec in specs[:4]:
            add(
                "query_trade_flows",
                T.query_trade_flows,
                reporter=spec["reporter"],
                partner=spec["partner"],
                sector=spec["sector"],
                year_from=year_from,
                year_to=year_to,
                limit=20,
            )
    elif len(regions) >= 2 and sectors:
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[0],
            partner=regions[1],
            sector=sectors[0],
            year_from=year_from,
            year_to=year_to,
            limit=20,
        )
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[1],
            partner=regions[0],
            sector=sectors[0],
            year_from=year_from,
            year_to=year_to,
            limit=20,
        )
    elif len(regions) == 1 and sectors:
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[0],
            sector=sectors[0],
            year_from=year_from,
            year_to=year_to,
            limit=20,
        )
    elif sectors:
        add(
            "query_trade_flows",
            T.query_trade_flows,
            sector=sectors[0],
            year_from=year_from,
            year_to=year_to,
            limit=20,
        )
    from analytics import describe_spans

    spans = spans_for_plan(plan, user_query)
    if spans:
        note = "The question did not name a sector, so this path is total merchandise. " if plan["merchandise_total"] else ""
        parts.append(note + "Year path, use only these figures: " + describe_spans(spans))
    elif regions or sectors or plan["blocs"]:
        parts.append("No official rows for this question.")
    return "\n\n".join(parts)
