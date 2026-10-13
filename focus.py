"""Map a focus query onto analyst tools so local models do not always see the same pack."""
import re

import tools as T
from tracing import traced_call


_REGION_WORDS = (
    ("south africa", "South Africa"),
    ("united states", "USA"),
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
)

_SECTOR_WORDS = (
    ("electronics", "Electronics"),
    ("minerals", "Minerals"),
    ("energy", "Energy"),
    ("textiles", "Textiles"),
    ("textile", "Textiles"),
    ("manufacturing", "Manufacturing"),
)

BRICS_REGIONS = ("Brazil", "Russia", "India", "China", "South Africa")


def _has(text: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", text) is not None


def plan_focus(query: str | None) -> dict:
    """Regions and sectors implied by a focus string. Empty lists mean a full-panel read."""
    q = (query or "").lower()
    regions: list[str] = []
    sectors: list[str] = []

    def add_region(name: str) -> None:
        if name not in regions:
            regions.append(name)

    def add_sector(name: str) -> None:
        if name not in sectors:
            sectors.append(name)

    if _has(q, "brics"):
        for name in BRICS_REGIONS:
            add_region(name)
    for needle, name in _REGION_WORDS:
        if _has(q, needle):
            add_region(name)
    if _has(q, "us-china") or _has(q, "us china") or _has(q, "china"):
        add_region("China")
    if _has(q, "us") or _has(q, "usa") or _has(q, "u.s.") or _has(q, "united states"):
        add_region("USA")
    for needle, name in _SECTOR_WORDS:
        if _has(q, needle):
            add_sector(name)
    return {"regions": regions, "sectors": sectors}


def gather_context(user_query: str | None) -> str:
    """Call analyst tools for this focus and return their text. Records a tool trace when one is active."""
    plan = plan_focus(user_query)
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
        add("query_trade_flows", T.query_trade_flows, year_from=2022, limit=30)
        add("get_yoy_growth", T.get_yoy_growth, year_from=2022, year_to=2024)
        add("get_top_flows", T.get_top_flows, n=10, year_from=2022)
        add("get_trade_trends", T.get_trade_trends, limit=10)
        return "\n\n".join(parts)

    for region in regions:
        add("get_region_summary", T.get_region_summary, region=region)
        add("get_trade_trends", T.get_trade_trends, region=region, limit=8)
    for sector in sectors:
        add("get_sector_summary", T.get_sector_summary, sector=sector)
        add("get_yoy_growth", T.get_yoy_growth, sector=sector, year_from=2022, year_to=2024)
    if regions and not sectors:
        add("get_yoy_growth", T.get_yoy_growth, region=regions[0], year_from=2022, year_to=2024)
    if len(regions) >= 2 and sectors:
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[0],
            partner=regions[1],
            sector=sectors[0],
            year_from=2022,
            limit=20,
        )
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[1],
            partner=regions[0],
            sector=sectors[0],
            year_from=2022,
            limit=20,
        )
    elif len(regions) == 1 and sectors:
        add(
            "query_trade_flows",
            T.query_trade_flows,
            reporter=regions[0],
            sector=sectors[0],
            year_from=2022,
            limit=20,
        )
    elif sectors:
        add("query_trade_flows", T.query_trade_flows, sector=sectors[0], year_from=2022, limit=20)
    return "\n\n".join(parts)
