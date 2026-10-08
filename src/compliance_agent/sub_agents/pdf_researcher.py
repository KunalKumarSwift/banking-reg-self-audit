"""PDF researcher: searches the bank's curated regulatory PDF corpus.

Runs in parallel with the web researcher. Its final text is moved into
session state (FINDINGS_KEY) for the report writer rather than shown to the
user; see compliance_agent._callbacks.

search_regulations and the provider live at module level on purpose: Agent
Engine pickles root_agent, and module-level functions are pickled by
reference, so the remote side re-imports this module and builds its own
search client instead of trying to pickle the (unpicklable) gRPC one.

search_regulations is async and runs the blocking Vertex Search call in a
worker thread. ADK calls sync tools directly on its event loop (outside live
mode), so a sync version made Gemini's parallel searches run one at a time
and stalled the web researcher running alongside.

Each search uses one Vertex AI Search summary request, and the project quota
is 10 per minute (discoveryengine llm_requests). A quota error is retried
briefly, then reported to the model as text: a raised error would abort the
whole audit instead of letting the report use whatever else was found.
"""

import asyncio

from google.adk.agents import Agent
from google.adk.tools.tool_context import ToolContext
from google.api_core.exceptions import GoogleAPICallError, ResourceExhausted
from google.genai import types

from compliance_agent._callbacks import make_findings_capture
from compliance_agent._contracts.search import SearchResult
from compliance_agent._prompts import PDF_RESEARCHER_INSTRUCTION
from compliance_agent._providers.vertex_search import VertexSearchProvider
from compliance_agent._sources import add_sources
from compliance_agent.config import load_config

# The report writer reads this researcher's findings from here; `temp:` = this turn only.
FINDINGS_KEY = "temp:findings:pdf"

# Seconds to wait before each retry after a quota error.
_QUOTA_RETRY_DELAYS = (5, 15)

_config = load_config()
_search_provider = VertexSearchProvider(
    project_id=_config.project_id,
    location=_config.search_location,
    engine_id=_config.search_engine_id,
)


async def search_regulations(query: str, tool_context: ToolContext) -> str:
    """Search the bank's curated Canadian regulatory PDF corpus.

    Args:
        query: A focused natural-language query
            (e.g. "biometric authentication requirements").

    Returns:
        A grounded answer with [n] citation markers, followed by the
        numbered list of source documents those markers refer to.
    """
    try:
        result = await _search_with_retry(query)
    except ResourceExhausted:
        return "Search unavailable: the search quota is exhausted. Use other results."
    except GoogleAPICallError as error:
        return f"Search failed ({error.code}); use other results."
    add_sources(
        tool_context.state,
        f"pdf:{tool_context.function_call_id}",
        [(name, "") for name in result.sources],
    )
    listing = "\n".join(f"[{i}] {name}" for i, name in enumerate(result.sources, start=1))
    return f"{result.answer}\n\nSources:\n{listing or '(none)'}"


async def _search_with_retry(query: str) -> SearchResult:
    """Run one corpus search off the event loop, retrying on quota errors.

    Raises:
        ResourceExhausted: If the quota is still exhausted after all retries.
        GoogleAPICallError: For any other Vertex AI Search failure.
    """
    for delay in _QUOTA_RETRY_DELAYS:
        try:
            return await asyncio.to_thread(_search_provider.search, query)
        except ResourceExhausted:
            await asyncio.sleep(delay)
    return await asyncio.to_thread(_search_provider.search, query)


pdf_researcher = Agent(
    name="pdf_researcher",
    model=_config.model_name,
    description="Searches the internal regulatory PDF corpus.",
    instruction=PDF_RESEARCHER_INSTRUCTION,
    tools=[search_regulations],
    # Research needs little reasoning; capped thinking keeps each turn fast.
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=512)
    ),
    after_model_callback=make_findings_capture(FINDINGS_KEY),
)
