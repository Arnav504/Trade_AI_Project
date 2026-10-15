"""Public links for a corridor. They never become a trade value."""
import json
import re
import urllib.parse
import urllib.request


_MONEY = re.compile(
    r"(?:\$\s?\d[\d.,]*|\b\d[\d.,]*\s*(?:trillion|billion|million))(?:\s*(?:trillion|billion|million|bn|mn))?",
    re.IGNORECASE,
)


def _strip_money(text: str) -> str:
    cleaned = _MONEY.sub("", text or "")
    return " ".join(cleaned.split())


def _wikipedia(query: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": query[:120],
            "limit": 3,
            "namespace": 0,
            "format": "json",
        }
    )
    request = urllib.request.Request(
        "https://en.wikipedia.org/w/api.php?" + params,
        headers={"User-Agent": "ASAN-Macro/1.0 (trade brief; context links only)"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode())
    titles = data[1] if len(data) > 1 else []
    urls = data[3] if len(data) > 3 else []
    return [{"title": title, "url": url} for title, url in zip(titles, urls)]


def _duckduckgo(query: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query[:120], "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    request = urllib.request.Request(
        "https://api.duckduckgo.com/?" + params,
        headers={"User-Agent": "ASAN-Macro/1.0 (trade brief; context links only)"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode())
    links = []
    if data.get("AbstractURL") and data.get("Heading"):
        links.append({"title": data["Heading"], "url": data["AbstractURL"]})
    for topic in data.get("RelatedTopics") or []:
        if isinstance(topic, dict) and topic.get("FirstURL"):
            links.append({"title": topic.get("Text") or "Public page", "url": topic["FirstURL"]})
        if len(links) >= 3:
            break
    return links[:3]


def _search(query: str) -> list[dict]:
    links: list[dict] = []
    for finder in (_duckduckgo, _wikipedia):
        try:
            links.extend(finder(query) or [])
        except Exception:
            continue
        if len(links) >= 3:
            break
    return links[:3]


def public_notes(query: str, search=None) -> dict:
    """Up to three links. Titles are prose, not a source of chart dollars."""
    finder = search or _search
    try:
        raw = finder(query) or []
    except Exception:
        raw = []
    links = []
    for item in raw:
        url = str(item.get("url") or "")
        title = _strip_money(str(item.get("title") or "Public page"))
        if url.startswith("http") and title:
            links.append({"title": title, "url": url})
        if len(links) == 3:
            break
    if not links:
        return {"summary": "", "links": []}
    return {
        "summary": (
            "What people are saying is context only. "
            "These links are public pages. They are not the source of any figure in the chart."
        ),
        "links": links,
    }
