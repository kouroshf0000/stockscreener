from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SectionPattern:
    """Regex boundaries for extracting a named section from a filing."""
    name: str
    start: re.Pattern[str]
    end: re.Pattern[str]
    min_chars: int = 1_500


@dataclass(frozen=True)
class FormProfile:
    """Per-form metadata: what sections exist and how to find them."""
    form: str
    description: str
    supports_risk_factors: bool
    risk_factors_patterns: tuple[SectionPattern, ...] = ()


# 10-K and 10-K/A: "Item 1A. Risk Factors" → "Item 1B." or "Item 2."
TEN_K_RISK = SectionPattern(
    name="risk_factors",
    start=re.compile(r"(?i)item\s*1a\s*[\.\s\u2014\-:]*\s*risk\s*factors"),
    end=re.compile(r"(?i)item\s*(?:1b|2)\s*[\.\s\u2014\-:]"),
)

# 10-Q Part II: "Item 1A. Risk Factors" (often shorter, references 10-K)
TEN_Q_RISK = SectionPattern(
    name="risk_factors",
    start=re.compile(r"(?i)item\s*1a\s*[\.\s\u2014\-:]*\s*risk\s*factors"),
    end=re.compile(r"(?i)item\s*(?:1b|2|3|4|5|6)\s*[\.\s\u2014\-:]"),
    min_chars=500,
)

# 20-F: "Item 3. Key Information" → subsection "D. Risk Factors"
# Also some filers use "Risk Factors" directly as a top-level section.
TWENTY_F_RISK_STANDARD = SectionPattern(
    name="risk_factors",
    start=re.compile(
        r"(?i)(?:item\s*3[\.\s\u2014\-:]*\s*key\s*information[\s\S]{0,500}?)?"
        r"(?:[d3][\.\s\u2014\-:]+)?\s*risk\s*factors"
    ),
    end=re.compile(
        r"(?i)item\s*4\s*[\.\s\u2014\-:]|"
        r"information\s*on\s*the\s*company|"
        r"unresolved\s*staff\s*comments"
    ),
)

# 40-F: Canadian filers — Annual Information Form attached as exhibit; "Risk Factors" heading.
FORTY_F_RISK = SectionPattern(
    name="risk_factors",
    start=re.compile(r"(?i)\brisk\s*factors\b"),
    end=re.compile(
        r"(?i)(?:dividend|distribution)s?\s*(?:policy|record)|"
        r"description\s*of\s*capital\s*structure|"
        r"market\s*for\s*securities"
    ),
)

# S-1 / S-3 / S-4 / F-1 / F-4: "Risk Factors" → "Use of Proceeds" / "Forward-Looking Statements" / "Dilution"
PROSPECTUS_RISK = SectionPattern(
    name="risk_factors",
    start=re.compile(r"(?i)\brisk\s*factors\b"),
    end=re.compile(
        r"(?i)(?:use\s*of\s*proceeds|"
        r"forward[\s-]*looking\s*statements|"
        r"cautionary\s*note|"
        r"dilution|"
        r"capitalization)"
    ),
)

# 8-K uses numbered items: "Item 1.01", "Item 2.01", etc.
EIGHT_K_ANY_ITEM = SectionPattern(
    name="items",
    start=re.compile(r"(?i)item\s*\d+\.\d+\s*[\.\s\u2014\-:]"),
    end=re.compile(r"(?i)signatures?|exhibit\s*index"),
    min_chars=100,
)


# DEF 14A: compensation discussion, security ownership
DEF14A_CD_A = SectionPattern(
    name="compensation_discussion",
    start=re.compile(r"(?i)compensation\s*discussion\s*(?:and|&)\s*analysis"),
    end=re.compile(r"(?i)compensation\s*committee\s*report|summary\s*compensation\s*table"),
)


PROFILES: dict[str, FormProfile] = {
    "10-K": FormProfile("10-K", "Annual report (US domestic)", True, (TEN_K_RISK,)),
    "10-K/A": FormProfile("10-K/A", "Amended annual report", True, (TEN_K_RISK,)),
    "10-KSB": FormProfile("10-KSB", "Small-business annual (retired)", True, (TEN_K_RISK,)),
    "10-Q": FormProfile("10-Q", "Quarterly report (US)", True, (TEN_Q_RISK,)),
    "10-Q/A": FormProfile("10-Q/A", "Amended quarterly report", True, (TEN_Q_RISK,)),
    "20-F": FormProfile("20-F", "Annual report (foreign private issuer)", True, (TWENTY_F_RISK_STANDARD,)),
    "20-F/A": FormProfile("20-F/A", "Amended 20-F", True, (TWENTY_F_RISK_STANDARD,)),
    "40-F": FormProfile("40-F", "Annual (Canadian MJDS filer)", True, (FORTY_F_RISK, PROSPECTUS_RISK)),
    "40-F/A": FormProfile("40-F/A", "Amended 40-F", True, (FORTY_F_RISK, PROSPECTUS_RISK)),
    "S-1": FormProfile("S-1", "Registration (IPO)", True, (PROSPECTUS_RISK,)),
    "S-1/A": FormProfile("S-1/A", "Amended S-1", True, (PROSPECTUS_RISK,)),
    "S-3": FormProfile("S-3", "Shelf registration", True, (PROSPECTUS_RISK,)),
    "S-4": FormProfile("S-4", "Registration (M&A)", True, (PROSPECTUS_RISK,)),
    "F-1": FormProfile("F-1", "Foreign IPO registration", True, (PROSPECTUS_RISK,)),
    "F-3": FormProfile("F-3", "Foreign shelf", True, (PROSPECTUS_RISK,)),
    "F-4": FormProfile("F-4", "Foreign M&A registration", True, (PROSPECTUS_RISK,)),
    "424B1": FormProfile("424B1", "Prospectus", True, (PROSPECTUS_RISK,)),
    "424B2": FormProfile("424B2", "Prospectus", True, (PROSPECTUS_RISK,)),
    "424B3": FormProfile("424B3", "Prospectus", True, (PROSPECTUS_RISK,)),
    "424B4": FormProfile("424B4", "Prospectus", True, (PROSPECTUS_RISK,)),
    "424B5": FormProfile("424B5", "Prospectus", True, (PROSPECTUS_RISK,)),
    "8-K": FormProfile("8-K", "Current report (material events)", False, ()),
    "8-K/A": FormProfile("8-K/A", "Amended current report", False, ()),
    "6-K": FormProfile("6-K", "Foreign interim update", False, ()),
    "DEF 14A": FormProfile("DEF 14A", "Definitive proxy", False, ()),
    "PRE 14A": FormProfile("PRE 14A", "Preliminary proxy", False, ()),
}


ANNUAL_FORMS: tuple[str, ...] = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
QUARTERLY_FORMS: tuple[str, ...] = ("10-Q", "10-Q/A")
PERIODIC_FORMS: tuple[str, ...] = (*ANNUAL_FORMS, *QUARTERLY_FORMS)
CURRENT_FORMS: tuple[str, ...] = ("8-K", "8-K/A", "6-K")
PROSPECTUS_FORMS: tuple[str, ...] = ("S-1", "S-1/A", "S-3", "S-4", "F-1", "F-3", "F-4")

RISK_FACTOR_FORMS: tuple[str, ...] = (
    *PERIODIC_FORMS,
    *PROSPECTUS_FORMS,
)


def profile_for(form: str) -> FormProfile | None:
    return PROFILES.get(form)
