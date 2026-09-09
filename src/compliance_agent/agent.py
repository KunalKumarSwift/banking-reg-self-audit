"""The compliance self-audit agent definition.

Wires the VertexSearchProvider in as a callable tool for an ADK agent.
"""

from google.adk.agents import Agent

from compliance_agent._prompts import SYSTEM_INSTRUCTION
from compliance_agent._providers.vertex_search import VertexSearchProvider
from compliance_agent.config import load_config

_config = load_config()
_search_provider = VertexSearchProvider(
    project_id=_config.project_id,
    location=_config.search_location,
    engine_id=_config.search_engine_id,
)


def search_regulations(query: str) -> str:
    """Search Canadian banking regulatory guidelines for relevant guidance.

    Use this tool whenever you need to answer a regulatory question or
    check a feature against compliance requirements. Never answer
    regulatory specifics without calling this tool first.

    Args:
        query: A natural-language search query describing what regulatory
            guidance is needed (e.g. "biometric authentication requirements").

    Returns:
        A grounded answer with citation markers, generated from the
        regulatory document store.
    """
    return _search_provider.search(query)


root_agent = Agent(
    name="compliance_self_audit_agent",
    model=_config.model_name,
    description="Pre-audit compliance assistant for Canadian banking features.",
    instruction=SYSTEM_INSTRUCTION,
    tools=[search_regulations],
)
