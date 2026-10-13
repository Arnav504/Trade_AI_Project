"""Structured trade brief contract, query guard, and disclaimer."""
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


DISCLAIMER = (
    "Machine-generated brief. Figures come from the local trade panel and tool output; "
    "verify them against primary sources before use."
)

MAX_QUERY_CHARS = 200

_INJECTION = re.compile(
    r"("
    r"ignore\s+(all\s+|any\s+|previous\s+|prior\s+|above\s+)?instructions"
    r"|disregard\s+(all\s+|the\s+)?(previous|prior|above|your)"
    r"|reveal\s+(your\s+|the\s+)?(system\s+)?prompt"
    r"|print\s+(your\s+|the\s+)?(system\s+)?prompt"
    r"|output\s+the\s+exact\s+system\s+prompt"
    r"|system\s+prompt"
    r"|you\s+are\s+now"
    r"|jailbreak"
    r"|prompt_leak"
    r"|forget\s+(trade|everything|all|your|previous)"
    r"|write\s+a\s+recipe"
    r"|<\s*/?\s*system\s*>"
    r"|\[\s*system\s*:"
    r")",
    re.IGNORECASE,
)

_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$")


class QueryRejected(ValueError):
    """User focus failed the public query guard."""


class ToolTraceEntry(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0


class TradeBrief(BaseModel):
    summary: str = ""
    key_regions_sectors: str = ""
    so_what: str = ""
    whats_next: str = ""
    bullets: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    focus: Optional[str] = None
    generated_at: str = ""
    full_report: str = ""
    source: str = "llm"
    title: str = ""
    id: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def guard_query(raw: Optional[str]) -> Optional[str]:
    """Return a cleaned focus, or None when the caller asked for a full-panel read.

    Raises QueryRejected for empty, over-long, or instruction-override text.
    """
    if raw is None:
        return None
    cleaned = "".join(ch for ch in raw if ord(ch) >= 32)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise QueryRejected("Enter a short trade focus, such as BRICS or US-China electronics.")
    if len(cleaned) > MAX_QUERY_CHARS:
        raise QueryRejected(f"Focus queries are limited to {MAX_QUERY_CHARS} characters.")
    if _INJECTION.search(cleaned):
        raise QueryRejected(
            "That request asks to override the analyst instructions. Ask a trade question instead."
        )
    return cleaned


def _section_key(title: str) -> Optional[str]:
    t = title.lower().strip(" :\"'")
    if "what" in t and "next" in t:
        return "whats_next"
    if "so what" in t or t.startswith("implication"):
        return "so_what"
    if "key region" in t or "key sector" in t or "regions and sectors" in t or "regions/sectors" in t:
        return "key_regions_sectors"
    if "summary" in t:
        return "summary"
    return None


def extract_delimited(text: str) -> str:
    if "REPORT_START" in text and "REPORT_END" in text:
        start = text.find("REPORT_START") + len("REPORT_START")
        end = text.find("REPORT_END")
        if end > start:
            return text[start:end].strip()
    return (text or "").strip()


def _bullets(text: str, limit: int = 5) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        numbered = re.match(r"^(?:\d+[.)]|[-*])\s+(.+)", line)
        if not numbered:
            continue
        item = re.sub(r"\*+", "", numbered.group(1)).strip()
        if item:
            out.append(item[:200])
        if len(out) >= limit:
            break
    return out


def parse_report(
    text: str,
    focus: Optional[str] = None,
    tool_trace: Optional[list] = None,
    source: str = "llm",
) -> TradeBrief:
    """Parse model text into the four-section brief. Headings are preferred; prose falls back to summary."""
    body = extract_delimited(text)
    if body.endswith(DISCLAIMER):
        body = body[: -len(DISCLAIMER)].strip()

    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    preamble: list[str] = []
    bucket: list[str] = []

    def flush():
        if current:
            sections[current] = "\n".join(bucket).strip()

    for line in body.splitlines():
        match = _HEADING.match(line.strip())
        key = _section_key(match.group(1)) if match else None
        if key:
            if current is None and bucket:
                preamble.extend(bucket)
            else:
                flush()
            current = key
            bucket = []
            continue
        bucket.append(line)
    if current is None:
        preamble.extend(bucket)
    else:
        flush()

    summary = sections.get("summary") or "\n".join(preamble).strip()
    key_regions = sections.get("key_regions_sectors", "")
    so_what = sections.get("so_what", "")
    whats_next = sections.get("whats_next", "")
    bullets = _bullets(key_regions) + _bullets(so_what) + _bullets(whats_next)
    if not bullets and summary:
        bullets = [summary[:300]]

    traces = []
    for item in tool_trace or []:
        if isinstance(item, ToolTraceEntry):
            traces.append(item)
        elif isinstance(item, dict) and item.get("name"):
            traces.append(ToolTraceEntry(**item))

    return TradeBrief(
        summary=summary,
        key_regions_sectors=key_regions,
        so_what=so_what,
        whats_next=whats_next,
        bullets=bullets[:12],
        disclaimer=DISCLAIMER,
        tool_trace=traces,
        focus=focus,
        generated_at=utc_now(),
        source=source,
    )


def render_brief(brief: TradeBrief) -> str:
    """Text form used by the CLI. Empty sections stay visible so the contract is checkable."""

    def block(title: str, body: str) -> str:
        content = (body or "").strip() or "Not provided."
        return f"### {title}\n\n{content}"

    parts = [
        block("Summary", brief.summary),
        block("Key regions and sectors", brief.key_regions_sectors),
        block("So what", brief.so_what),
        block("What's next", brief.whats_next),
        brief.disclaimer,
    ]
    return "\n\n".join(parts).strip()
