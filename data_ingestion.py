"""
Dynamic data ingestion for ASAN Macro.
Supports: local CSV, CSV from URL, and optional JSON API (e.g. UN Comtrade-style).
Makes the project's data gathering dynamic and pipeline-ready for LinkedIn/demo.
"""
import csv
import ipaddress
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from config import PROJECT_ROOT, get_data_url_allowlist, get_db_path

# Optional: requests for nicer URL handling (pip install requests)
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _get_conn():
    return sqlite3.connect(str(get_db_path()))


def _insert_flow(cur, year: int, reporter: str, partner: str, sector: str, flow_type: str, value_usd: float):
    """Insert one trade flow row (idempotent optional: check duplicates if needed)."""
    cur.execute(
        """INSERT INTO trade_flows (year, reporter_region, partner_region, sector, flow_type, value_usd)
           VALUES (?,?,?,?,?,?)""",
        (year, reporter.strip(), partner.strip(), sector.strip(), flow_type.strip(), value_usd),
    )


def load_csv_path(csv_path: Path) -> int:
    """
    Load a local CSV into the database.
    Expected columns: year, reporter_region, partner_region, sector, flow_type, value_usd.
    Returns number of rows inserted.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    conn = _get_conn()
    cur = conn.cursor()
    count = 0
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    year = int(row.get("year", 0))
                    reporter = (row.get("reporter_region") or "").strip()
                    partner = (row.get("partner_region") or "").strip()
                    sector = (row.get("sector") or "").strip()
                    flow_type = (row.get("flow_type") or "export").strip()
                    val = float(row.get("value_usd", 0))
                except (ValueError, KeyError):
                    continue
                if not reporter or not partner or not sector:
                    continue
                _insert_flow(cur, year, reporter, partner, sector, flow_type, val)
                count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def assert_public_https_url(url: str) -> str:
    """Allow only https URLs whose host is on DATA_URL_ALLOWLIST. Rejects IPs, localhost, and credentials."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https":
        raise ValueError("Only https URLs are allowed for data ingest.")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL host is missing.")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ValueError("Local hosts are not allowed.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses are not allowed.")
    allowed = get_data_url_allowlist()
    if host not in allowed:
        raise ValueError(f"Host {host} is not on DATA_URL_ALLOWLIST.")
    return url.strip()


def load_csv_url(url: str) -> int:
    """
    Load CSV from an allowlisted https URL into the database.
    Same column expectations as load_csv_path.
    Returns number of rows inserted.
    """
    url = assert_public_https_url(url)
    if HAS_REQUESTS:
        resp = requests.get(url, timeout=30, allow_redirects=False)
        if resp.is_redirect:
            raise ValueError("Redirects are not allowed for data URLs.")
        resp.raise_for_status()
        text = resp.text
    else:
        with urlopen(url, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")
    conn = _get_conn()
    cur = conn.cursor()
    count = 0
    try:
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            try:
                year = int(row.get("year", 0))
                reporter = (row.get("reporter_region") or "").strip()
                partner = (row.get("partner_region") or "").strip()
                sector = (row.get("sector") or "").strip()
                flow_type = (row.get("flow_type") or "export").strip()
                val = float(row.get("value_usd", 0))
            except (ValueError, KeyError):
                continue
            if not reporter or not partner or not sector:
                continue
            _insert_flow(cur, year, reporter, partner, sector, flow_type, val)
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def load_json_api(url: str = None, api_key_env: str = "COMTRADE_API_KEY") -> int:
    """
    Load trade data from a JSON API endpoint (e.g. UN Comtrade-style).
    If url is None, reads COMTRADE_JSON_URL from env (you can point to your own JSON).
    JSON expected: list of objects with year, reporter_region, partner_region, sector, flow_type, value_usd
    (or map from Comtrade fields in _map_comtrade_row).
    Returns number of rows inserted.
    """
    import json
    target_url = url or os.environ.get("COMTRADE_JSON_URL", "").strip()
    if not target_url:
        return 0
    target_url = assert_public_https_url(target_url)
    api_key = os.environ.get(api_key_env, "").strip()
    headers = {}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key  # Comtrade-style
    if HAS_REQUESTS:
        resp = requests.get(target_url, headers=headers, timeout=60, allow_redirects=False)
        if resp.is_redirect:
            raise ValueError("Redirects are not allowed for data URLs.")
        resp.raise_for_status()
        data = resp.json()
    else:
        req = __import__("urllib.request").request.Request(target_url, headers=headers)
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list):
        data = data.get("data", data.get("results", []))
    conn = _get_conn()
    cur = conn.cursor()
    count = 0
    try:
        for item in data:
            row = _map_api_row(item)
            if not row:
                continue
            year, reporter, partner, sector, flow_type, value_usd = row
            _insert_flow(cur, year, reporter, partner, sector, flow_type, value_usd)
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def _map_api_row(item: dict):
    """
    Map a JSON object to (year, reporter_region, partner_region, sector, flow_type, value_usd).
    Supports our canonical names or Comtrade-style (reporterCode -> reporter, etc.).
    """
    if isinstance(item, (list, tuple)) and len(item) >= 6:
        return (int(item[0]), str(item[1]), str(item[2]), str(item[3]), str(item[4]), float(item[5]))
    if not isinstance(item, dict):
        return None
    year = item.get("year") or item.get("period") or item.get("refYear")
    reporter = (item.get("reporter_region") or item.get("reporter") or item.get("reporterDesc") or "").strip()
    partner = (item.get("partner_region") or item.get("partner") or item.get("partnerDesc") or "").strip()
    sector = (item.get("sector") or item.get("cmdCode") or item.get("aggLevel") or "General").strip()
    flow = (item.get("flow_type") or item.get("flowCode") or "export").strip()
    if flow in ("M", "1", "import"):
        flow = "import"
    elif flow in ("X", "2", "export"):
        flow = "export"
    value = item.get("value_usd") or item.get("primaryValue") or item.get("netWgt") or 0
    try:
        year = int(year)
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not reporter or not partner:
        return None
    return (year, reporter, partner, sector, flow, value)


def ingest_all(data_path: Path = None, data_url: str = None, json_url: str = None) -> dict:
    """
    Run all configured ingestion sources and return counts.
    Call from main.py with --data path, --data-url url, and/or env COMTRADE_JSON_URL.
    """
    counts = {}
    if data_path and Path(data_path).exists():
        counts["csv_path"] = load_csv_path(Path(data_path))
    if data_url:
        try:
            counts["csv_url"] = load_csv_url(data_url)
        except Exception as e:
            counts["csv_url_error"] = str(e)
    if json_url or os.environ.get("COMTRADE_JSON_URL"):
        try:
            counts["json_api"] = load_json_api(json_url)
        except Exception as e:
            counts["json_api_error"] = str(e)
    return counts
