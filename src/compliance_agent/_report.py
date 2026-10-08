"""The compliance report's structure, and its rendering to markdown.

The report writer returns JSON matching ComplianceReport (via ADK's
output_schema) instead of writing markdown itself. Gemini 2.5 Flash
repeatedly degenerated when writing markdown tables (a single separator or
padded row grew to 100k+ characters until the token limit cut the report
off), so all table syntax is produced here, in code.
"""

from typing import Literal

from pydantic import BaseModel, Field

from compliance_agent._sources import SourceKind


class GuidelineRow(BaseModel):
    """One regulatory requirement that applies to the feature."""

    guideline: str = Field(description="Guideline or law name, e.g. 'OSFI B-13'.")
    requirement: str = Field(description="What it requires, in one or two sentences.")
    sources: list[int] = Field(description="Citation numbers from the numbered sources list.")


class GapRow(BaseModel):
    """One way the feature may fall short of a requirement."""

    gap: str = Field(description="The potential gap, in one sentence.")
    severity: Literal["High", "Medium", "Low"]
    related_guideline: str = Field(description="Guideline or law name.")
    sources: list[int] = Field(description="Citation numbers from the numbered sources list.")


class ComplianceReport(BaseModel):
    """The full pre-audit compliance report."""

    summary: str = Field(description="Two or three sentences answering the request.")
    applicable_guidelines: list[GuidelineRow]
    potential_gaps: list[GapRow] = Field(description="Empty for a pure Q&A request.")
    recommendations: list[str] = Field(description="Concrete engineering actions.")
    open_questions: list[str] = Field(description="Questions for the formal audit.")
    currency_check: str = Field(
        description="Does the web research show anything newer than, or conflicting "
        "with, the internal corpus? 'No newer guidance found' if not."
    )


def render_report(report: ComplianceReport, source_kinds: list[SourceKind]) -> str:
    """Render the report as GitHub-flavoured markdown.

    Guideline and gap rows without at least one valid citation are dropped:
    every regulatory claim in the tables must trace to a consulted source.
    Citations of non-official web sources are marked † (e.g. [7†]).

    Args:
        report: The validated report from the report writer.
        source_kinds: Kind of each row in the sources table; source_kinds[i]
            is citation number i + 1.

    Returns:
        Markdown with the Summary through Currency Check sections and the
        advisory disclaimer (the sources table is appended separately).
    """

    def cite(numbers: list[int]) -> str:
        valid = [n for n in dict.fromkeys(numbers) if 1 <= n <= len(source_kinds)]
        return "".join(
            f"[{n}†]" if source_kinds[n - 1] == "other" else f"[{n}]" for n in valid
        )

    lines = ["### Summary", report.summary, "", "### Applicable Guidelines"]
    lines += _table(
        ["Guideline", "Requirement", "Source"],
        [
            [r.guideline, r.requirement, cite(r.sources)]
            for r in report.applicable_guidelines
            if cite(r.sources)
        ],
    )
    lines += ["", "### Potential Gaps"]
    lines += _table(
        ["Gap", "Severity", "Related Guideline", "Source"],
        [
            [r.gap, r.severity, r.related_guideline, cite(r.sources)]
            for r in report.potential_gaps
            if cite(r.sources)
        ],
    )
    lines += ["", "### Recommendations"]
    lines += [f"{i}. {rec}" for i, rec in enumerate(report.recommendations, start=1)]
    lines += ["", "### Open Questions for Formal Audit"]
    lines += [f"- {q}" for q in report.open_questions]
    lines += ["", "### Currency Check", report.currency_check, ""]
    lines += ["*Advisory only. This does not replace formal compliance or audit review.*"]
    return "\n".join(lines)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Build markdown table lines, or a placeholder line if there are no rows."""
    if not rows:
        return ["_None identified._"]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out


def _cell(text: str) -> str:
    """Make text safe inside a markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")

