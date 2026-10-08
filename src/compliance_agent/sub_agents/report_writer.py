"""Report writer: turns both researchers' findings into the final report.

Has no tools. Its instruction is built per turn from session state: the two
researchers' findings plus a numbered source list, so the citation numbers
it returns line up with the "Sources Consulted" table.

It returns JSON matching ComplianceReport (output_schema), not markdown;
the render_final_report callback turns that into the markdown report plus
sources table. See compliance_agent._report for why.
"""

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types

from compliance_agent._callbacks import render_final_report
from compliance_agent._prompts import REPORT_WRITER_TEMPLATE
from compliance_agent._report import ComplianceReport
from compliance_agent._sources import KIND_LABEL, get_sources, source_kind
from compliance_agent.config import load_config
from compliance_agent.sub_agents.pdf_researcher import FINDINGS_KEY as PDF_FINDINGS_KEY
from compliance_agent.sub_agents.web_researcher import FINDINGS_KEY as WEB_FINDINGS_KEY


def _build_instruction(ctx: ReadonlyContext) -> str:
    """Fill the report prompt with this turn's research and sources.

    Args:
        ctx: Read-only context exposing the current session state.

    Returns:
        The complete system instruction for this turn.
    """
    state = ctx.state
    return REPORT_WRITER_TEMPLATE.format(
        pdf_findings=state.get(PDF_FINDINGS_KEY) or "(no findings)",
        web_findings=state.get(WEB_FINDINGS_KEY) or "(no findings)",
        source_list="\n".join(
            f"[{i}] {source[0]} ({KIND_LABEL[source_kind(source)]})"
            for i, source in enumerate(get_sources(state), start=1)
        )
        or "(no sources were retrieved this turn)",
    )


report_writer = Agent(
    name="report_writer",
    model=load_config().model_name,
    description="Writes the final compliance report.",
    instruction=_build_instruction,
    output_schema=ComplianceReport,
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=8192,
        thinking_config=types.ThinkingConfig(thinking_budget=2048),
    ),
    after_model_callback=render_final_report,
)
