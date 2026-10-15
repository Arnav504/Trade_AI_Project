"""Live World Bank merchandise totals and IMF current-account series.

These are country accounts, not bilateral HS flows, so they stay in macro_series.
UN Comtrade rows stay in trade_flows. Both tables live in the same SQLite file.
"""
import json
import urllib.request

from database import init_db

# ISO3 codes for every country the question parser can name.
COUNTRIES = {
    "BRA": "Brazil",
    "RUS": "Russia",
    "IND": "India",
    "CHN": "China",
    "ZAF": "South Africa",
    "USA": "USA",
    "MEX": "Mexico",
    "VNM": "Vietnam",
    "DEU": "Germany",
    "FRA": "France",
    "ITA": "Italy",
    "ESP": "Spain",
    "NLD": "Netherlands",
    "POL": "Poland",
    "BEL": "Belgium",
    "SWE": "Sweden",
    "IRL": "Ireland",
    "AUT": "Austria",
    "PRT": "Portugal",
    "GRC": "Greece",
    "DNK": "Denmark",
    "FIN": "Finland",
    "CZE": "Czechia",
    "HUN": "Hungary",
    "ROU": "Romania",
    "GBR": "United Kingdom",
    "JPN": "Japan",
    "CAN": "Canada",
    "AUS": "Australia",
    "IDN": "Indonesia",
    "THA": "Thailand",
    "MYS": "Malaysia",
    "SGP": "Singapore",
    "PHL": "Philippines",
    "MMR": "Myanmar",
    "KHM": "Cambodia",
    "LAO": "Laos",
    "BRN": "Brunei",
    "KOR": "South Korea",
    "SAU": "Saudi Arabia",
    "ARE": "United Arab Emirates",
    "TUR": "Turkey",
    "ARG": "Argentina",
    "NGA": "Nigeria",
    "EGY": "Egypt",
}

# The saved gallery only refreshes the original corridor countries.
GALLERY_ISO = ("BRA", "RUS", "IND", "CHN", "ZAF", "USA", "MEX", "VNM")
_NAMES = {name: code for code, name in COUNTRIES.items()}
_checked: set[tuple] = set()

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


def parse_imf(payload, series_id: str, year_from: int | None = None, year_to: int | None = None) -> list[dict]:
    name, unit = IMF_INDICATORS[series_id]
    start = YEARS[0] if year_from is None else int(year_from)
    end = YEARS[1] if year_to is None else int(year_to)
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
            if year < start or year > end:
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
    codes = ";".join(GALLERY_ISO)
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


def _has_indicator(country: str, indicator: str, year_from: int, year_to: int) -> bool:
    for row in load_macro_rows():
        if row["country"] == country and row["indicator"] == indicator and year_from <= row["year"] <= year_to:
            return True
    return False


def _upsert_macro(rows: list[dict]) -> None:
    if not rows:
        return
    conn = init_db()
    try:
        for row in rows:
            conn.execute(
                """DELETE FROM macro_series
                   WHERE source = ? AND indicator = ? AND country = ? AND year = ?""",
                (row["source"], row["indicator"], row["country"], row["year"]),
            )
            conn.execute(
                """INSERT INTO macro_series (source, indicator, country, year, value, unit)
                   VALUES (?,?,?,?,?,?)""",
                (row["source"], row["indicator"], row["country"], row["year"], row["value"], row["unit"]),
            )
        conn.commit()
    finally:
        conn.close()


def ensure_macro(countries: list[str] | None, year_from: int | None, year_to: int | None, get=None) -> None:
    """Load World Bank and IMF rows for this question when those years are not stored yet.

    A failed request is remembered for this process and does not raise. These figures
    stay in macro_series. They are not written into trade_flows.
    """
    start = int(year_from or YEARS[0])
    end = int(year_to or YEARS[1])
    if start > end:
        start, end = end, start
    names = []
    for name in countries or []:
        if name in _NAMES and name not in names:
            names.append(name)
    if not names:
        return
    getter = get or _get
    need_bank = [
        name
        for name in names
        if ("world_bank", name, start, end) not in _checked
        and not _has_indicator(name, "merchandise_exports", start, end)
    ]
    if need_bank:
        codes = ";".join(_NAMES[name] for name in need_bank)
        found = []
        try:
            for code, indicator in WB_INDICATORS.items():
                url = (
                    "https://api.worldbank.org/v2/country/"
                    f"{codes}/indicator/{code}?date={start}:{end}&format=json&per_page=500"
                )
                found.extend(parse_world_bank(getter(url), indicator))
        except Exception as exc:
            print(f"World Bank: {exc}", flush=True)
            found = []
        keep = [row for row in found if row["country"] in need_bank and start <= row["year"] <= end]
        _upsert_macro(keep)
        for name in need_bank:
            if not _has_indicator(name, "merchandise_exports", start, end):
                _checked.add(("world_bank", name, start, end))
    need_imf = [
        name
        for name in names
        if ("imf", name, start, end) not in _checked
        and not _has_indicator(name, "current_account", start, end)
    ]
    if not need_imf:
        return
    found = []
    try:
        for series_id in IMF_INDICATORS:
            url = f"https://www.imf.org/external/datamapper/api/v1/{series_id}"
            found.extend(parse_imf(getter(url), series_id, start, end))
    except Exception as exc:
        print(f"IMF: {exc}", flush=True)
        found = []
    keep = [row for row in found if row["country"] in need_imf]
    _upsert_macro(keep)
    for name in need_imf:
        if not _has_indicator(name, "current_account", start, end):
            _checked.add(("imf", name, start, end))


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
