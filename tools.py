"""
User-created tools called by the LLM for augmentation (required by project rubric).
These tools query the trade database and RAG store so the LLM can ground its analysis.
"""
from database import init_db


def _get_conn():
    return init_db()


def list_regions() -> str:
    """List all reporter and partner regions in the trade database."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT reporter_region FROM trade_flows UNION SELECT DISTINCT partner_region FROM trade_flows ORDER BY 1"
    )
    rows = cur.fetchall()
    conn.close()
    return "Regions: " + ", ".join(r[0] for r in rows)


def list_sectors() -> str:
    """List all sectors in the trade database."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT sector FROM trade_flows ORDER BY 1")
    rows = cur.fetchall()
    conn.close()
    return "Sectors: " + ", ".join(r[0] for r in rows)


def query_trade_flows(
    reporter: str = None,
    partner: str = None,
    sector: str = None,
    year_from: int = None,
    year_to: int = None,
    limit: int = 50,
) -> str:
    """
    Query trade flows. Pass reporter_region, partner_region, sector, year_from, year_to as filters.
    Returns a text summary of matching flows (year, reporter, partner, sector, flow_type, value_usd).
    """
    conn = _get_conn()
    cur = conn.cursor()
    q = "SELECT year, reporter_region, partner_region, sector, flow_type, value_usd FROM trade_flows WHERE 1=1"
    params = []
    if reporter:
        q += " AND reporter_region = ?"
        params.append(reporter)
    if partner:
        q += " AND partner_region = ?"
        params.append(partner)
    if sector:
        q += " AND sector = ?"
        params.append(sector)
    if year_from is not None:
        q += " AND year >= ?"
        params.append(year_from)
    if year_to is not None:
        q += " AND year <= ?"
        params.append(year_to)
    q += " ORDER BY year, value_usd DESC LIMIT ?"
    params.append(limit)
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No trade flows found for the given filters."
    lines = ["year | reporter | partner | sector | flow_type | value_usd"]
    for r in rows:
        lines.append(f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]:.0f}")
    return "\n".join(lines)


def get_region_summary(region: str) -> str:
    """
    Get a summary of trade for one region (as reporter or partner): total flows by year and sector.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT year, sector, flow_type, SUM(value_usd) as total
        FROM trade_flows
        WHERE reporter_region = ? OR partner_region = ?
        GROUP BY year, sector, flow_type
        ORDER BY year, total DESC
        """,
        (region, region),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return f"No data found for region: {region}"
    lines = [f"Trade summary for {region} (year | sector | flow_type | total_usd):"]
    for r in rows:
        lines.append(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]:.0f}")
    return "\n".join(lines)


def get_sector_summary(sector: str) -> str:
    """
    Get a summary of trade for one sector across all regions and years.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT year, reporter_region, partner_region, flow_type, SUM(value_usd) as total
        FROM trade_flows
        WHERE sector = ?
        GROUP BY year, reporter_region, partner_region, flow_type
        ORDER BY year, total DESC
        LIMIT 30
        """,
        (sector,),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return f"No data found for sector: {sector}"
    lines = [f"Sector {sector} (year | reporter | partner | flow_type | total_usd):"]
    for r in rows:
        lines.append(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:.0f}")
    return "\n".join(lines)


def rag_retrieve(query: str, limit: int = 5) -> str:
    """
    Retrieve relevant context from the RAG store (stored trade bulletins/summaries).
    Use a short query like 'BRICS decoupling' or 'US China electronics'.
    """
    conn = _get_conn()
    cur = conn.cursor()
    # Simple keyword retrieval: chunks containing any word from query
    words = [w.strip().lower() for w in query.split() if len(w.strip()) > 1]
    if not words:
        cur.execute("SELECT source, content FROM rag_chunks ORDER BY id LIMIT ?", (limit,))
    else:
        placeholders = " OR ".join("content LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words] + [limit]
        cur.execute(
            f"SELECT source, content FROM rag_chunks WHERE {placeholders} LIMIT ?",
            params,
        )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No relevant RAG chunks found."
    return "\n---\n".join(f"[{r[0]}] {r[1]}" for r in rows)


def get_yoy_growth(region: str = None, sector: str = None, year_from: int = None, year_to: int = None) -> str:
    """
    Compute year-over-year growth in trade value (as reporter or partner).
    Optional filters: region, sector, year_from, year_to. Returns top growth pairs.
    """
    conn = _get_conn()
    cur = conn.cursor()
    year_from = year_from or 2022
    year_to = year_to or 2024
    q = """
    WITH yearly AS (
        SELECT year, reporter_region, partner_region, sector, SUM(value_usd) AS total
        FROM trade_flows
        WHERE year BETWEEN ? AND ?
    """
    params = [year_from, year_to]
    if region:
        q += " AND (reporter_region = ? OR partner_region = ?)"
        params.extend([region, region])
    if sector:
        q += " AND sector = ?"
        params.append(sector)
    q += """
        GROUP BY year, reporter_region, partner_region, sector
    ),
    prev AS (
        SELECT reporter_region, partner_region, sector, year, total,
               LAG(total) OVER (PARTITION BY reporter_region, partner_region, sector ORDER BY year) AS prev_total
        FROM yearly
    )
    SELECT reporter_region, partner_region, sector, year, total, prev_total,
           CASE WHEN prev_total > 0 THEN ROUND(100.0 * (total - prev_total) / prev_total, 1) ELSE NULL END AS pct_growth
    FROM prev
    WHERE prev_total IS NOT NULL AND prev_total > 0
    ORDER BY pct_growth DESC
    LIMIT 15
    """
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No YoY growth data for the given filters."
    lines = ["YoY growth (reporter | partner | sector | year | value_usd | prev_usd | pct_growth):"]
    for r in rows:
        lines.append(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:.0f} | {r[5]:.0f} | {r[6]:.1f}%")
    return "\n".join(lines)


def get_top_flows(n: int = 10, year_from: int = None, year_to: int = None, flow_type: str = None) -> str:
    """
    Get top N trade flows by value (optionally by year range and flow_type).
    """
    conn = _get_conn()
    cur = conn.cursor()
    year_from = year_from or 2022
    year_to = year_to or 2024
    q = """
    SELECT year, reporter_region, partner_region, sector, flow_type, SUM(value_usd) AS total
    FROM trade_flows
    WHERE year BETWEEN ? AND ?
    """
    params = [year_from, year_to]
    if flow_type:
        q += " AND flow_type = ?"
        params.append(flow_type)
    q += " GROUP BY year, reporter_region, partner_region, sector, flow_type ORDER BY total DESC LIMIT ?"
    params.append(n)
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No flows found."
    lines = [f"Top {n} flows (year | reporter | partner | sector | flow_type | value_usd):"]
    for r in rows:
        lines.append(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]:.0f}")
    return "\n".join(lines)


def get_trade_trends(region: str = None, limit: int = 10) -> str:
    """
    Summarize trade trends: which sectors/partners grew or shrank over the last years.
    Optional region filter (reporter or partner).
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT MIN(year), MAX(year) FROM trade_flows")
    row0 = cur.fetchone()
    if not row0 or row0[0] is None:
        conn.close()
        return "No trend data available."
    min_yr, max_yr = row0[0], row0[1]
    if min_yr == max_yr:
        conn.close()
        return "Need at least two years of data for trends."
    q = """
    WITH first_yr AS (
        SELECT reporter_region, partner_region, sector, flow_type, SUM(value_usd) AS total
        FROM trade_flows WHERE year = ?
        GROUP BY reporter_region, partner_region, sector, flow_type
    ),
    last_yr AS (
        SELECT reporter_region, partner_region, sector, flow_type, SUM(value_usd) AS total
        FROM trade_flows WHERE year = ?
        GROUP BY reporter_region, partner_region, sector, flow_type
    )
    SELECT f.reporter_region, f.partner_region, f.sector, f.flow_type, f.total AS first_val, l.total AS last_val
    FROM first_yr f
    JOIN last_yr l ON f.reporter_region = l.reporter_region AND f.partner_region = l.partner_region AND f.sector = l.sector AND f.flow_type = l.flow_type
    WHERE f.total > 0
    """
    params = [min_yr, max_yr]
    if region:
        q += " AND (f.reporter_region = ? OR f.partner_region = ?)"
        params.extend([region, region])
    q += " ORDER BY (l.total - f.total) DESC LIMIT ?"
    params.append(limit)
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "No trend data available."
    lines = [f"Trade trends ({min_yr} vs {max_yr}) (reporter | partner | sector | flow_type | first_yr | last_yr):"]
    for r in rows:
        change = "up" if r[5] > r[4] else "down"
        lines.append(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:.0f} | {r[5]:.0f} ({change})")
    return "\n".join(lines)


def get_macro_context(region: str = "") -> str:
    """World Bank merchandise totals and IMF current account for one country, or the loaded set."""
    from macro_data import render_macro

    text = render_macro([region] if region else None)
    return text or "No World Bank or IMF series are loaded."


# Registry for the agent: name -> (function, description)
TOOLS = [
    ("list_regions", list_regions, "List all regions in the trade database."),
    ("list_sectors", list_sectors, "List all sectors in the trade database."),
    ("query_trade_flows", query_trade_flows, "Query trade flows with optional filters: reporter, partner, sector, year_from, year_to, limit."),
    ("get_region_summary", get_region_summary, "Get trade summary for one region (as reporter or partner). Argument: region name."),
    ("get_sector_summary", get_sector_summary, "Get trade summary for one sector across regions and years. Argument: sector name."),
    ("rag_retrieve", rag_retrieve, "Retrieve relevant context from stored trade bulletins. Argument: short query string (e.g. 'BRICS decoupling')."),
    ("get_yoy_growth", get_yoy_growth, "Get year-over-year growth in trade value. Optional: region, sector, year_from, year_to."),
    ("get_top_flows", get_top_flows, "Get top N trade flows by value. Optional: n (default 10), year_from, year_to, flow_type."),
    ("get_trade_trends", get_trade_trends, "Summarize trade trends (sectors/partners that grew or shrank). Optional: region, limit."),
    ("get_macro_context", get_macro_context, "World Bank merchandise exports and imports, plus the IMF current account. Optional: region."),
]

TOOL_BY_NAME = {name: fn for name, fn, _ in TOOLS}
