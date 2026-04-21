from __future__ import annotations

import html
import re
from typing import NamedTuple

from backend.filings.taxonomy import PROFILES, SectionPattern, profile_for

_TAG_RE = re.compile(r"(?is)<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
_IX_HIDDEN_RE = re.compile(r"(?is)<ix:header[^>]*>.*?</ix:header>")
_WS_RE = re.compile(r"[\s\u00a0]+")

MAX_SECTION_CHARS = 120_000


class SectionExtraction(NamedTuple):
    text: str | None
    reason: str
    chars: int


def clean_text(raw: str) -> str:
    text = _IX_HIDDEN_RE.sub(" ", raw)
    text = _SCRIPT_RE.sub(" ", text)
    text = _STYLE_RE.sub(" ", text)
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def extract_with_pattern(clean: str, pattern: SectionPattern) -> str | None:
    """
    Find all matches of `start`. For each, locate nearest subsequent `end`.
    Return the longest candidate whose body exceeds `pattern.min_chars`.
    This defeats TOC-vs-body confusion in modern inline-XBRL filings.
    """
    starts = [m.end() for m in pattern.start.finditer(clean)]
    if not starts:
        return None
    best: str | None = None
    for start in starts:
        end_match = pattern.end.search(clean, pos=start + 10)
        end = end_match.start() if end_match else min(start + MAX_SECTION_CHARS, len(clean))
        section = clean[start:end].strip()
        if len(section) < pattern.min_chars:
            continue
        if best is None or len(section) > len(best):
            best = section
    return best[:MAX_SECTION_CHARS] if best else None


def extract_risk_factors(form: str, doc_html: str) -> SectionExtraction:
    profile = profile_for(form)
    if profile is None or not profile.supports_risk_factors:
        return SectionExtraction(None, f"form_not_supported:{form}", 0)

    clean = clean_text(doc_html)
    if len(clean) < 1_000:
        return SectionExtraction(None, "document_too_small", len(clean))

    for pattern in profile.risk_factors_patterns:
        section = extract_with_pattern(clean, pattern)
        if section:
            return SectionExtraction(section, "ok", len(section))

    return SectionExtraction(None, "section_not_found_in_document", 0)


def extract_section(form: str, section_name: str, doc_html: str) -> SectionExtraction:
    """Extract any named section using the form's taxonomy."""
    profile = profile_for(form)
    if profile is None:
        return SectionExtraction(None, f"form_not_supported:{form}", 0)
    patterns: list[SectionPattern] = []
    if section_name == "risk_factors" and profile.supports_risk_factors:
        patterns = list(profile.risk_factors_patterns)
    if not patterns:
        return SectionExtraction(None, f"section_not_available_for_form:{form}/{section_name}", 0)
    clean = clean_text(doc_html)
    for p in patterns:
        if p.name != section_name:
            continue
        s = extract_with_pattern(clean, p)
        if s:
            return SectionExtraction(s, "ok", len(s))
    return SectionExtraction(None, "section_not_found_in_document", 0)


_EIGHT_K_ITEM_RE = re.compile(
    r"(?is)item\s*(\d+\.\d+)\s*[\.\s\u2014\-:]*\s*([^\.\n]{0,200}?)(?=\s*item\s*\d+\.\d+|\s*signatures?|\s*exhibit\s*index|$)"
)


def extract_8k_items(doc_html: str) -> dict[str, str]:
    """Extract the body of each numbered item in an 8-K. Returns {item_number: body_snippet}."""
    clean = clean_text(doc_html)
    out: dict[str, str] = {}
    for m in _EIGHT_K_ITEM_RE.finditer(clean):
        item_no = m.group(1)
        body = m.group(2).strip()
        if item_no and body and item_no not in out:
            out[item_no] = body[:500]
    return out


def supported_forms_for(section: str) -> list[str]:
    out: list[str] = []
    for form, profile in PROFILES.items():
        if section == "risk_factors" and profile.supports_risk_factors:
            out.append(form)
    return out
