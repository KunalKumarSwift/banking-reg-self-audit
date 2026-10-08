"""Web researcher: finds current regulatory material with Google Search.

Runs in parallel with the PDF researcher, to catch guidance newer than the
curated corpus. It has google_search as its ONLY tool because Gemini won't
combine built-in tools with function tools in one agent.

It searches the open web, preferring official regulator sites. Every web
source is kept but classified official or other (OFFICIAL_DOMAINS in
_sources.py); the report groups them separately and marks citations of
other sources with †. At most 3 searches: an uncapped prompt made Gemini
issue ~38 queries and take up to 3 minutes.

Its final text is moved into session state (FINDINGS_KEY), and the source
URLs are taken from the response's grounding metadata, both by the shared
after_model_callback; see compliance_agent._callbacks.
"""

from google.adk.agents import Agent
from google.adk.tools import google_search
from google.genai import types

from compliance_agent._callbacks import make_findings_capture
from compliance_agent._prompts import WEB_RESEARCHER_INSTRUCTION
from compliance_agent._sources import OFFICIAL_DOMAINS
from compliance_agent.config import load_config

# The report writer reads this researcher's findings from here; `temp:` = this turn only.
FINDINGS_KEY = "temp:findings:web"

web_researcher = Agent(
    name="web_researcher",
    model=load_config().model_name,
    description="Searches official regulator websites for current guidance.",
    instruction=WEB_RESEARCHER_INSTRUCTION.format(domains=", ".join(OFFICIAL_DOMAINS)),
    tools=[google_search],
    # Capped thinking: uncapped, one search turn varied from 10s to 3 minutes.
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=512)
    ),
    after_model_callback=make_findings_capture(FINDINGS_KEY),
)
