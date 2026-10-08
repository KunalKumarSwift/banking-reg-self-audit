"""The compliance self-audit agent: router plus audit pipeline.

Shape:

    compliance_assistant (router)    tools=[search_regulations]
      └─ audit_pipeline (SequentialAgent)
           ├─ research (ParallelAgent)
           │    ├─ pdf_researcher   sub_agents/pdf_researcher.py
           │    └─ web_researcher   sub_agents/web_researcher.py
           └─ report_writer         sub_agents/report_writer.py

The router runs the full pipeline only to audit something new. Follow-ups
on an audit ("how do we fix these gaps?", "rewrite FR-04") are answered by
the router directly, in free form rather than the report format, using
search_regulations for any regulatory fact not already in the conversation.
After the
pipeline finishes, the next user message returns to the router, because ADK
only resumes on the last agent if it can transfer back to its parent, and
agents under a SequentialAgent can't.

SequentialAgent/ParallelAgent are deprecated in ADK 2.x in favour of
Workflow, but Workflow can't yet be an LlmAgent sub-agent (needed for the
router), so we stay on them for now.

ADK and Agent Engine discover the agent through the `root_agent` name.
"""

import warnings

from google.adk.agents import Agent, ParallelAgent, SequentialAgent

from compliance_agent._prompts import ROUTER_INSTRUCTION
from compliance_agent.config import load_config
from compliance_agent.sub_agents import pdf_researcher, report_writer, web_researcher
from compliance_agent.sub_agents.pdf_researcher import search_regulations

with warnings.catch_warnings():
    # Deprecated in favour of Workflow; see module docstring for why we stay.
    warnings.simplefilter("ignore", DeprecationWarning)
    _research = ParallelAgent(
        name="research",
        sub_agents=[pdf_researcher, web_researcher],
    )
    _audit_pipeline = SequentialAgent(
        name="audit_pipeline",
        description=(
            "Researches the internal regulatory corpus and the web, then "
            "writes a structured compliance report with cited sources."
        ),
        sub_agents=[_research, report_writer],
    )

root_agent = Agent(
    name="compliance_assistant",
    model=load_config().model_name,
    description="Pre-audit compliance assistant for Canadian banking features.",
    instruction=ROUTER_INSTRUCTION,
    # For follow-ups that need one quick lookup, without the full pipeline.
    tools=[search_regulations],
    sub_agents=[_audit_pipeline],
)
