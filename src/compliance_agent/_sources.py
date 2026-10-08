"""Tracks which sources were consulted this turn and renders them as tables.

A source is a (name, url) pair: PDFs are (file name, "") and web results are
(domain, link). Each source falls into one of three kinds, derived from that
pair: internal PDF (no url), official regulator site (domain on
OFFICIAL_DOMAINS), or other web source (law firms, vendors, news, ...).

Sources are kept in `temp:` state, which ADK clears after every turn. Each
search call writes its own key, because the two researchers run in parallel
and two writers appending to one shared list would drop entries.
"""

from collections.abc import Mapping
from typing import Literal

from google.adk.sessions.state import State

Source = tuple[str, str]
SourceKind = Literal["pdf", "official", "other"]
_PREFIX = "temp:sources:"

# Web results from these sites (subdomains included) count as official.
OFFICIAL_DOMAINS = (
    "osfi-bsif.gc.ca",  # OSFI
    "canada.ca",  # FCAC, Department of Finance
    "fcac-acfc.gc.ca",  # FCAC (legacy site)
    "priv.gc.ca",  # Office of the Privacy Commissioner
    "fintrac-canafe.gc.ca",  # FINTRAC
    "laws-lois.justice.gc.ca",  # federal statutes and regulations
    "bankofcanada.ca",  # Bank of Canada
    "gazette.gc.ca",  # Canada Gazette (where federal regulations are published)
)
# The report lists at most this many web pages of each kind (official, other).
MAX_WEB_SOURCES = 5

KIND_LABEL: dict[SourceKind, str] = {
    "pdf": "Internal document",
    "official": "Official regulator website",
    "other": "Other web source (not authoritative)",
}


def add_sources(state: State, key: str, sources: list[Source]) -> None:
    """Record the sources one search call consulted.

    Args:
        state: ADK session state (tool or callback context `.state`).
        key: Unique per call, e.g. the function-call ID.
        sources: (name, url) pairs; url is "" for internal PDFs.
    """
    state[_PREFIX + key] = sources


def get_sources(state: Mapping[str, object]) -> list[Source]:
    """Return this turn's sources, grouped PDF, official, then other web.

    Every PDF is kept, plus at most MAX_WEB_SOURCES official and
    MAX_WEB_SOURCES other web pages.

    Args:
        state: ADK session state.

    Returns:
        (name, url) pairs without duplicates; list index i is citation number i + 1.
    """
    unique: dict[str, Source] = {}
    for key, value in state.items():
        if key.startswith(_PREFIX) and isinstance(value, list):
            for name, url in value:
                unique.setdefault(url or name, (name, url))
    by_kind: dict[SourceKind, list[Source]] = {"pdf": [], "official": [], "other": []}
    for source in unique.values():
        by_kind[source_kind(source)].append(source)
    return (
        by_kind["pdf"]
        + by_kind["official"][:MAX_WEB_SOURCES]
        + by_kind["other"][:MAX_WEB_SOURCES]
    )


def is_official(domain: str) -> bool:
    """Whether a domain is on OFFICIAL_DOMAINS (subdomains included)."""
    return any(domain == d or domain.endswith("." + d) for d in OFFICIAL_DOMAINS)


def source_kind(source: Source) -> SourceKind:
    """Classify a source as an internal PDF, official site or other web source."""
    name, url = source
    if not url:
        return "pdf"
    return "official" if is_official(name) else "other"


def sources_table(sources: list[Source]) -> str:
    """Render the "Sources Consulted" section, one table per kind of source.

    Args:
        sources: Output of get_sources, in the same order the report writer
            was given; numbering continues across tables so citations match.

    Returns:
        A markdown heading plus up to three numbered tables.
    """
    lines = ["### Sources Consulted"]
    headings: dict[SourceKind, str] = {
        "pdf": "**Internal documents**",
        "official": "**Official regulator websites**",
        "other": "**Other web sources** (marked † in the report; not "
        "authoritative, verify against official guidance)",
    }
    numbered = list(enumerate(sources, start=1))
    for kind, heading in headings.items():
        rows = [(i, s) for i, s in numbered if source_kind(s) == kind]
        if not rows:
            continue
        lines += ["", heading, "", "| # | Source |", "|---|---|"]
        for i, (name, url) in rows:
            lines.append(f"| {i} | [{name}]({url}) |" if url else f"| {i} | {name} |")
    if len(lines) == 1:
        lines += ["", "_No sources were retrieved for this answer._"]
    return "\n".join(lines)
