"""Callbacks for moving research data between ADK pipeline stages.

Research agents' final text is stored in temporary session state instead of
being shown directly to the user. This allows the report-writing agent to use
the research without exposing the researchers' raw responses.

Tool/function-call parts are kept in the response so the UI can still show
research activity such as searches.

The report writer's JSON output is rendered into the final markdown report,
followed by a sources table listing everything collected during the research
stage: PDF file names from search_regulations and web links (official
regulator sites and other sources) from Google Search grounding metadata.
"""

import uuid
from collections.abc import Callable

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions.state import State
from google.genai import types
from pydantic import ValidationError

from compliance_agent._report import ComplianceReport, render_report
from compliance_agent._sources import (
    add_sources,
    get_sources,
    is_official,
    source_kind,
    sources_table,
)

# Type for an ADK after_model_callback.
ModelCallback = Callable[
    [CallbackContext, LlmResponse],
    LlmResponse | None,
]


def make_findings_capture(findings_state_key: str) -> ModelCallback:
    """Create a callback that saves a researcher's final findings to state.

    The researcher's text is removed from the response so it is not streamed
    to the user. Function calls are preserved so the UI can still show
    tool activity.

    Args:
        findings_state_key: State key where the final research findings
            should be stored.

    Returns:
        A callback suitable for LlmAgent.after_model_callback.
    """

    def capture_research_findings(
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:

        state = callback_context.state
        response = llm_response
        content = response.content

        # Nothing to process.
        if content is None or not content.parts:
            return None

        # When the model has finished responding, save any Google Search
        # sources that were used during this turn.
        if not response.partial:
            save_web_sources(
                state=state,
                grounding_metadata=response.grounding_metadata,
            )

        # Extract normal model text, excluding model thoughts.
        research_text = extract_visible_text(content)

        if not research_text:
            return None

        # If the response contains a function call, the text is usually
        # just a preamble such as "Let me search for that."
        contains_function_call = any(part.function_call for part in content.parts)

        # Only save completed responses that contain actual findings.
        # Google Search answers keep only sentences backed by a web page.
        if not response.partial and not contains_function_call:
            state[findings_state_key] = (
                grounded_findings(response.grounding_metadata)
                if response.grounding_metadata
                else research_text
            )

        # Remove text from the response before it reaches the UI.
        # Keep function calls so the UI can still display tool activity.
        non_text_parts = [part for part in content.parts if not part.text]

        # A final reply that is now empty must also drop finish_reason: ADK
        # (non-streaming) flags "STOP with no content" as MODEL_RETURNED_NO_CONTENT,
        # but silently skips a reply with no content and no finish_reason.
        if not non_text_parts and not response.partial:
            return response.model_copy(update={"content": None, "finish_reason": None})

        return replace_response_parts(
            response=response,
            parts=non_text_parts,
            role=content.role,
        )

    return capture_research_findings


def extract_visible_text(content: types.Content) -> str:
    """Extract model text while ignoring thought/reasoning parts."""

    return "".join(
        part.text for part in content.parts or [] if part.text and not part.thought
    )


def replace_response_parts(
    response: LlmResponse,
    parts: list[types.Part],
    role: str | None,
) -> LlmResponse:
    """Return a copy of the response with the supplied content parts."""

    return response.model_copy(
        update={
            "content": types.Content(
                role=role,
                parts=parts,
            )
        }
    )


def render_final_report(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    """Turn the report writer's JSON into the markdown report plus sources table.

    The report writer returns ComplianceReport JSON (see compliance_agent._report);
    this replaces it with rendered markdown so the user never sees raw JSON.
    Partial (streaming) chunks are emptied for the same reason, so the report
    appears once, complete, in the final response.
    """

    response = llm_response
    content = response.content
    if content is None or not content.parts:
        return None

    if response.partial:
        return replace_response_parts(response=response, parts=[], role=content.role)

    sources = get_sources(callback_context.state.to_dict())
    try:
        report_markdown = render_report(
            ComplianceReport.model_validate_json(extract_visible_text(content)),
            source_kinds=[source_kind(s) for s in sources],
        )
    except ValidationError:
        # Malformed or truncated JSON: say so rather than show a broken report.
        report_markdown = (
            "_The report could not be generated completely. Please try again._"
        )

    return replace_response_parts(
        response=response,
        parts=[types.Part(text=report_markdown + "\n\n" + sources_table(sources))],
        role=content.role,
    )


def save_web_sources(
    state: State,
    grounding_metadata: types.GroundingMetadata | None,
) -> None:
    """Save Google Search grounding sources into ADK session state.

    All results are kept; the sources table groups them into official and
    other web sources (see compliance_agent._sources).
    """

    if grounding_metadata is None or not grounding_metadata.grounding_chunks:
        return

    web_sources = [
        (
            chunk.web.domain or chunk.web.title or "",
            chunk.web.uri or "",
        )
        for chunk in grounding_metadata.grounding_chunks
        if chunk.web is not None
    ]

    add_sources(
        state,
        f"web:{uuid.uuid4().hex}",
        web_sources,
    )


def grounded_findings(grounding_metadata: types.GroundingMetadata) -> str:
    """Rebuild web findings from only the sentences a web page supports.

    Gemini writes much of a Google Search answer without linking it to any
    page. Grounding supports map each backed sentence to the pages behind
    it, so keeping only those sentences means every web claim the report
    writer sees is traceable, and each is labelled official or not.

    Args:
        grounding_metadata: Grounding metadata from the web researcher's reply.

    Returns:
        One bullet per page-backed sentence, labelled with its domains and
        whether any of them is an official regulator site.
    """
    chunks = grounding_metadata.grounding_chunks or []
    lines: list[str] = []
    for support in grounding_metadata.grounding_supports or []:
        domains: set[str] = set()
        for index in support.grounding_chunk_indices or []:
            web = chunks[index].web if index < len(chunks) else None
            if web and (web.domain or web.title):
                domains.add(web.domain or web.title or "")
        if domains and support.segment and support.segment.text:
            label = "official" if any(is_official(d) for d in domains) else "other"
            lines.append(
                f"- {support.segment.text} (source: {', '.join(sorted(domains))}; {label})"
            )
    return "\n".join(lines) or "No page-backed findings from the web search."
