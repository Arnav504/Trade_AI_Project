"""Live World Bank merchandise totals and IMF current-account series.

These are country accounts, not HS corridors, so they stay out of trade_flows.
"""
import json
import urllib.request

from database import init_db

COUNTRIES = {
    "BRA": "Brazil",
    "RUS": "Russia",
    "IND": "India",
    "CHN": "China",
    "ZAF": "South Africa",
    "USA": "USA",
    "MEX": "Mexico",
    "VNM": "Vietnam",
}

WB_INDICATORS = {
    "TX.VAL.MRCH.CD.WT": "merchandise_exports",
    "TM.VAL.MRCH.CD.WT": "merchandise_imports",
}

IMF_INDICATORS = {
    "BCA": ("current_account", "billions_usd"),
    "BCA_NGDPD": ("current_account_gdp", "percent_gdp"),
}

YEARS = (2022, 2024)


def parse_world_bank(payload, indicator: str) -> list[dict]:
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    parsed = []
    for item in rows or []:
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        country = COUNTRIES.get(item.get("countryiso3code") or "")
        if not country:
            continue
        try:
            year = int(item.get("date"))
            value = float(item["value"])
        except (TypeError, ValueError):
            continue
        parsed.append(
            {
                "source": "world_bank",
                "indicator": indicator,
                "country": country,
                "year": year,
                "value": value,
                "unit": "usd",
            }
        )
    return parsed


def parse_imf(payload, series_id: str) -> list[dict]:
    name, unit = IMF_INDICATORS[series_id]
    series = (payload.get("values") or {}).get(series_id) or {}
    parsed = []
    for code, country in COUNTRIES.items():
        yearly = series.get(code) or {}
        if not isinstance(yearly, dict):
            continue
        for year_text, value in yearly.items():
            if value is None:
                continue
            try:
                year = int(year_text)
                number = float(value)
            except (TypeError, ValueError):
                continue
            if year < YEARS[0] or year > YEARS[1]:
                continue
            parsed.append(
                {
                    "source": "imf",
                    "indicator": name,
                    "country": country,
                    "year": year,
                    "value": number,
                    "unit": unit,
                }
            )
    return parsed


def _get(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode())


def fetch_world_bank() -> list[dict]:
    codes = ";".join(COUNTRIES)
    rows = []
    for code, indicator in WB_INDICATORS.items():
        url = (
            "https://api.worldbank.org/v2/country/"
            f"{codes}/indicator/{code}?date={YEARS[0]}:{YEARS[1]}&format=json&per_page=500"
        )
        rows.extend(parse_world_bank(_get(url), indicator))
    return rows


def fetch_imf() -> list[dict]:
    rows = []
    for series_id in IMF_INDICATORS:
        url = f"https://www.imf.org/external/datamapper/api/v1/{series_id}"
        rows.extend(parse_imf(_get(url), series_id))
    return rows


def fetch_macro() -> list[dict]:
    rows = []
    errors = []
    for name, fn in (("World Bank", fetch_world_bank), ("IMF", fetch_imf)):
        try:
            found = fn()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if not found:
            errors.append(f"{name}: no rows")
            continue
        rows.extend(found)
    for message in errors:
        print(message, flush=True)
    return rows


def load_macro(rows: list[dict]) -> tuple[int, int]:
    """Replace macro_series. Returns (world_bank_count, imf_count)."""
    conn = init_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM macro_series")
    wb = imf = 0
    for row in rows:
        cur.execute(
            """INSERT INTO macro_series (source, indicator, country, year, value, unit)
               VALUES (?,?,?,?,?,?)""",
            (row["source"], row["indicator"], row["country"], row["year"], row["value"], row["unit"]),
        )
        if row["source"] == "world_bank":
            wb += 1
        elif row["source"] == "imf":
            imf += 1
    conn.commit()
    conn.close()
    return wb, imf


def load_macro_rows() -> list[dict]:
    conn = init_db()
    try:
        found = conn.execute(
            "SELECT source, indicator, country, year, value, unit FROM macro_series"
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [
        {
            "source": row[0],
            "indicator": row[1],
            "country": row[2],
            "year": row[3],
            "value": row[4],
            "unit": row[5],
        }
        for row in found
    ]


def _usd(value: float) -> str:
    number = float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000_000:
        return f"{sign}${number / 1_000_000_000_000:.1f}T"
    if number >= 1_000_000_000:
        return f"{sign}${number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{sign}${number / 1_000_000:.1f}M"
    return f"{sign}${number:,.0f}"


def _latest(rows: list[dict], country: str, indicator: str):
    matched = [row for row in rows if row["country"] == country and row["indicator"] == indicator and row["value"] is not None]
    if not matched:
        return None
    return max(matched, key=lambda row: row["year"])


def render_macro(countries: list[str] | None = None) -> str:
    """One sentence each for World Bank goods totals and the IMF current account."""
    rows = load_macro_rows()
    if not rows:
        return ""
    wanted = countries or []
    names = []
    for name in wanted:
        if name and name not in names:
            names.append(name)
    if not names:
        names = []
        for row in rows:
            if row["country"] not in names:
                names.append(row["country"])
    exports = []
    imports = []
    accounts = []
    for name in names:
        export = _latest(rows, name, "merchandise_exports")
        imported = _latest(rows, name, "merchandise_imports")
        account = _latest(rows, name, "current_account")
        ratio = _latest(rows, name, "current_account_gdp")
        if export:
            exports.append(f"{name} {_usd(export['value'])} ({export['year']})")
        if imported:
            imports.append(f"{name} {_usd(imported['value'])} ({imported['year']})")
        if account:
            text = f"{name} {_usd(account['value'] * 1_000_000_000)} ({account['year']})"
            if ratio and ratio["year"] == account["year"]:
                text += f", {ratio['value']:+.1f}% of GDP"
            accounts.append(text)
    parts = []
    if exports:
        parts.append("World Bank merchandise exports: " + "; ".join(exports) + ".")
    if imports:
        parts.append("World Bank merchandise imports: " + "; ".join(imports) + ".")
    if accounts:
        parts.append("IMF WEO current account: " + "; ".join(accounts) + ".")
    return " ".join(parts)
